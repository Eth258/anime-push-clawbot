import glob
import json
import os
import re
import sqlite3
import shutil
import subprocess
import threading
from difflib import SequenceMatcher
import time

import requests
try:
    import opencc
except Exception:
    opencc = None

from common.logger import log
from . import PushChannel
from .qr import qr_content_for, code_text_for
from . import sentlog

def _first_existing(*cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return ""


# 路径全部可用环境变量覆盖，方便迁移到其它机器
WX_DIR = os.environ.get("WX_STATE_DIR", "/root/.openclaw/openclaw-weixin")
NODE = _first_existing(
    os.environ.get("OPENCLAW_NODE", ""),
    "/root/.nvm/versions/node/v24.22.1/bin/node",
    "/usr/local/bin/node",
    "/usr/bin/node",
) or shutil.which("node") or "node"
OPENCLAW = _first_existing(
    os.environ.get("OPENCLAW_ENTRY", ""),
    "/root/.nvm/versions/node/v24.22.1/lib/node_modules/openclaw/openclaw.mjs",
    "/usr/local/lib/node_modules/openclaw/openclaw.mjs",
    "/usr/lib/node_modules/openclaw/openclaw.mjs",
)
DATA_DIR = os.environ.get("AIO_DATA_DIR", "/opt/aio-dynamic-push/data")
OUTBOX = os.path.join(DATA_DIR, "outbox.json")
SEEN = os.path.join(DATA_DIR, "pushed.json")
QUOTA = os.path.join(DATA_DIR, "quota.json")
QUOTAS = os.path.join(DATA_DIR, "quotas.json")
MSG_DB = os.environ.get("WX_MSG_DB", os.path.join(WX_DIR, "ref-messages.sqlite"))
ALERT = os.path.join(DATA_DIR, "quota_alert.json")
DEDUPE = os.path.join(DATA_DIR, "anime_seen.json")
BGM_DATA = os.environ.get("BGM_DATA", "/root/anime_push/bd.json")
_T2S = opencc.OpenCC("t2s") if opencc else None
CN_NUM = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}

EP_RE = re.compile(r"第\s*\d+\s*[集话話]|全\s*\d+\s*[集话話]|第[一二三四五六七八九十]+\s*[集话話]")
NAME_RE = re.compile(r"[【《『「]([^】》』」]{1,60})[】》』」]")
TIME_TAIL_RE = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$")

PROMPT = (
    "你在帮我筛选 B 站 UP 主「{up}」的动态推送。\n"
    "这个 UP 主主要搬运/更新番剧。我只想要【番剧更新、番剧推荐、新番资讯】相关的动态。\n"
    "不要：广告、恰饭、带货、抽奖、直播预告、闲聊、催更、求关注、粉丝互动。\n"
    "注意：这个 UP 主常用中文方括号【】标番剧名。\n"
    "番剧更新通常长这样：【番剧名】第3集 / 【番剧名】全12集 超清中字。\n\n"
    "标题：{title}\n正文：{content}\n\n"
    '只输出 JSON：{{"push": true, "reason": "简短理由"}}'
)


def _raw_text(raw):
    md = (raw.get("modules") or {}).get("module_dynamic") or {}
    if md.get("desc") and md["desc"].get("text"):
        return md["desc"]["text"]
    major = md.get("major") or {}
    if major.get("type") == "MAJOR_TYPE_OPUS":
        o = major.get("opus") or {}
        return ((o.get("summary") or {}).get("text") or "") or o.get("title") or ""
    if major.get("type") == "MAJOR_TYPE_ARCHIVE":
        return (major.get("archive") or {}).get("title") or ""
    return ""


def _ilink_headers(token):
    """iLink 协议要求的完整请求头（缺任何一个都会被判定为 session timeout）"""
    import base64
    import random
    ver = (2 << 16) | (4 << 8) | 10
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": str(ver),
        "X-WECHAT-UIN": base64.b64encode(str(random.randint(1, 2 ** 32 - 1)).encode()).decode(),
        "Authorization": "Bearer " + token,
    }


def _parse_iso(text):
    """解析 bangumi-data 的 ISO 时间，返回时间戳；失败返回 None"""
    if not text:
        return None
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


class ClawBot(PushChannel):
    """个人微信 ClawBot 通道：番剧过滤 + 卡片渲染 + 持久化发送队列"""

    def __init__(self, config):
        super().__init__(config)
        self.target = str(config.get("target", ""))
        self.targets = [str(t).strip() for t in (config.get("targets") or [self.target])
                        if str(t).strip()]
        self.api_key = str(config.get("deepseek_key", ""))
        self.model = str(config.get("model", "deepseek-chat"))
        self.api_base = str(config.get("api_base", "https://api.deepseek.com/v1"))
        self.render_card = bool(config.get("render_card", True))
        self.send_link = bool(config.get("send_link", False))
        self.card_style = str(config.get("card_style", "bleed"))
        self.push_image_only = bool(config.get("push_image_only", True))
        self.fail_open = bool(config.get("fail_open", True))
        self.flush_interval = int(config.get("flush_interval", 90))
        self.quota_max = int(config.get("quota_max", 10))
        # 推送必须给对话让路：留 N 条额度给 AI 回复（回复不可恢复，推送可排队）
        self.reserve = max(0, int(config.get("quota_reserve", 2)))
        # 对话活动停止多少秒后才允许推送（一轮对话内的活动间隔可达 20 秒）
        self.chat_idle = max(0, int(config.get("chat_idle_seconds", 45)))
        self.quota_window = int(config.get("quota_window_hours", 24)) * 3600
        self._lock = threading.Lock()
        self._fail_streak = 0
        self._cooldown_until = 0
        self.quotas = self._load_json(QUOTAS, {})
        legacy = self._load_json(QUOTA, {})
        if self.target and self.target not in self.quotas and legacy.get("window_start"):
            self.quotas[self.target] = legacy
            self._save_json(QUOTAS, self.quotas)
        self.dedupe = self._load_json(DEDUPE, {})
        self.seen = self._load_json(SEEN, set())
        self.outbox = self._load_json(OUTBOX, [])
        if self.outbox:
            log.info(f"【推送_{self.name}】检测到 {len(self.outbox)} 条待补发消息")
        if not self.target:
            log.error(f"【推送_{self.name}】缺少 target，推送不可用")
        if self.flush_interval > 0:
            threading.Thread(target=self._flush_loop, daemon=True).start()

    # ---------- 状态存取 ----------
    @staticmethod
    def _load_json(path, default):
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data) if isinstance(default, set) else data
        except Exception as e:
            try:
                bad = path + ".corrupt"
                os.replace(path, bad)
                log.error(f"状态文件损坏已备份为 {bad}: {e}")
            except Exception:
                pass
            return default

    @staticmethod
    def _save_json(path, data):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sorted(data) if isinstance(data, set) else data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:
            log.error(f"状态写入失败 {path}: {e}")

    # ---------- 发送 ----------
    def _account_for(self, target):
        """按 target(userId) 反查对应 bot 账号 id；多账号下必须显式指定"""
        try:
            for path in glob.glob(os.path.join(WX_DIR, "accounts", "*-im-bot.json")):
                if "context" in path or "sync" in path:
                    continue
                with open(path, "r", encoding="utf-8") as fh:
                    acc = json.load(fh)
                if str(acc.get("userId", "")).strip() == str(target).strip():
                    return os.path.basename(path)[:-5]
        except Exception:
            pass
        return ""

    def _send(self, text, media=None, target=None):
        tgt = target or self.target
        cmd = [NODE, OPENCLAW, "message", "send",
               "--channel", "openclaw-weixin", "--target", tgt]
        acct = self._account_for(tgt)
        if acct:
            cmd += ["--account", acct]
        if text:
            cmd += ["-m", text]
        if media:
            cmd += ["--media", media]
        if not OPENCLAW:
            return False, "未找到 openclaw.mjs，请设置 OPENCLAW_ENTRY"
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            ok = p.returncode == 0 and "❌" not in out
            return ok, out
        except Exception as e:
            return False, str(e)


    # ---------- 季度/完结判定 ----------
    def _bgm_items(self):
        """加载 bangumi-data 全量清单（按文件 mtime 缓存）"""
        try:
            mtime = os.path.getmtime(BGM_DATA)
        except Exception:
            return []
        cache = self.__dict__.get("_bgm_cache")
        if cache and cache[0] == mtime:
            return cache[1]
        try:
            with open(BGM_DATA, "r", encoding="utf-8") as f:
                items = (json.load(f) or {}).get("items") or []
        except Exception as e:
            log.error(f"【推送_{self.name}】读取番剧清单失败：{e}")
            items = []
        self._bgm_cache = (mtime, items)
        return items

    def _airing_state(self, name):
        """判断番剧状态：airing（本季在播）/ finished（已完结）/ unknown（查不到）"""
        key = self._norm_name(name)
        if not key:
            return "unknown"
        now = time.time()
        airing = False
        finished = False
        for it in self._bgm_items():
            if it.get("type") not in ("tv", "web", "tv_short", None):
                continue
            names = [it.get("title") or ""]
            names += (it.get("titleTranslate") or {}).get("zh-Hans") or []
            if not any(self._same_anime(self._norm_name(n), key) for n in names if n):
                continue
            try:
                begin = it.get("begin") or ""
                end = it.get("end") or ""
                b = _parse_iso(begin)
                e = _parse_iso(end)
            except Exception:
                continue
            if b and b <= now and (not e or e + 7 * 86400 >= now):
                airing = True
                break
            if e and e < now:
                finished = True
        if airing:
            return "airing"
        return "finished" if finished else "unknown"

    # ---------- 番剧去重（跨 UP） ----------
    def _season_no(self, text):
        """提取季数：第X季 / Season N / Nth Season；没有则 None"""
        t = text or ""
        m = re.search(r"第\s*([一二三四五六七八九十]|\d{1,2})\s*[季期]", t)
        if m:
            v = m.group(1)
            return CN_NUM.get(v, None) if not v.isdigit() else int(v)
        m = re.search(r"Season\s*(\d{1,2})", t, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d{1,2})(?:st|nd|rd|th)\s+Season", t, re.I)
        return int(m.group(1)) if m else None

    def _norm_name(self, name):
        """繁转简 + 去符号/宣传词，用于比较"""
        t = _T2S.convert(name) if _T2S else name
        t = re.sub(r"[第]?\s*[一二三四五六七八九十\d]{1,2}\s*[季期]", "", t)
        t = re.sub(r"Season\s*\d+|\d+(?:st|nd|rd|th)\s+Season", "", t, flags=re.I)
        # 去掉「全三季」「全12话」「第三季」「第2集」这类数量/进度标记
        t = re.sub(r"全\s*[\d一二三四五六七八九十百]+\s*[季期集话話]", "", t)
        t = re.sub(r"[\d一二三四五六七八九十]+\s*[季期]$", "", t)
        t = re.sub(r"[全合]$", "", t)     # 「无职转生 全三季」去掉季数后残留的「全」
        t = re.sub(r"(超清中字|未删减版|未删减|简繁[日內内嵌封]*|周更|合集|完结|1080[pP]|4K|中字|熟肉|全季|全集)", "", t)
        t = re.sub(r"[【】『』《》「」\[\]（）()\s:：·・、,，.。!！?？~～\-—_/\\|]+", "", t)
        t = re.sub(r"[全合]$", "", t)     # 再兜一次：去符号后仍可能残留「全」
        return t.strip().lower()

    def _anime_key(self, text):
        """番剧名归一化后的去重键"""
        m = NAME_RE.search(text or "")
        name = m.group(1) if m else (text or "")[:24]
        return self._norm_name(name)

    def _same_anime(self, a, b):
        if not a or not b:
            return False
        if a == b:
            return True
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) >= 4 and short in long:
            return True
        return SequenceMatcher(None, a, b).ratio() >= 0.8

    def _claim_anime(self, key, uid, did, season=None):
        """登记今天的番剧；同一天同一部番被其它 UP 推过则拒绝"""
        if not key:
            return True, None
        today = time.strftime("%Y-%m-%d")
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400))
        for d in [d for d in self.dedupe if d < cutoff]:
            self.dedupe.pop(d, None)
        day = self.dedupe.setdefault(today, {})

        matched = None
        # 先走规则：精确 / 包含 / 相似度
        for k, prev in list(day.items()):
            if not self._same_anime(k, key):
                continue
            ps = prev.get("season")
            if season is not None and ps is not None and season != ps:
                continue
            matched = (k, prev)
            break

        # 规则判不出来，交给 AI 成对判断（不同译名兜底）
        if matched is None and day:
            try:
                from title_canon import ai_same_anime
                for k, prev in list(day.items())[:8]:
                    ps = prev.get("season")
                    if season is not None and ps is not None and season != ps:
                        continue
                    if ai_same_anime(key, k):
                        matched = (k, prev)
                        break
            except Exception:
                pass

        if matched:
            k, prev = matched
            if prev.get("uid") and str(prev["uid"]) != str(uid):
                return False, prev
            prev.update({"uid": str(uid), "ts": int(time.time()), "id": did})
            if k != key:
                prev.setdefault("aliases", [])
                if key not in prev["aliases"]:
                    prev["aliases"].append(key)
            day[k] = prev
            self._save_json(DEDUPE, self.dedupe)
            return True, prev

        day[key] = {"uid": str(uid), "ts": int(time.time()), "id": did, "season": season}
        self._save_json(DEDUPE, self.dedupe)
        return True, None

    # ---------- 配额 ----------
    def _agent_busy(self):
        """最近 chat_idle 秒内有对话活动（入站 / 模型调用 / agent 直发）→ 正在处理一轮对话"""
        if not self.chat_idle:
            return False
        try:
            last = sentlog.activity_ms()
        except Exception:
            return False
        return last > 0 and (time.time() * 1000 - last) < self.chat_idle * 1000

    def _last_inbound_ms(self, tgt):
        """用户最后一条消息的时间（毫秒），决定额度轮次起点"""
        try:
            con = sqlite3.connect("file:%s?mode=ro" % MSG_DB, uri=True, timeout=5)
            r = con.execute(
                "select max(created_at) from quote_messages where direction='inbound' and conversation_id=?",
                (tgt,)).fetchone()
            con.close()
            return int(r[0] or 0) if r else 0
        except Exception as e:
            log.error(f"【推送_{self.name}】读取入站时间失败：{e}")
            return 0

    def _count_outbound_since(self, since_ms, tgt):
        """统计 since_ms 之后发给该 target 的消息数。

        数据来自 SQLite 发送记录（sentlog），由网关日志增量归集：
        只读新增字节，日志轮转/清理都不影响已归集的历史。
        返回 (条数, 是否可用)；不可用时由调用方退回消息库。
        """
        try:
            sentlog.ingest()
            return sentlog.count_used(tgt, int(since_ms)), True
        except Exception as e:
            log.error(f"【推送_{self.name}】读取发送记录失败：{e}")
            return 0, False

    def _quota_used(self, tgt):
        """真实用量：日志里的成功发送数；日志不可用时退回消息库"""
        last_in = self._last_inbound_ms(tgt)
        if not last_in:
            return 0, 0
        total, ok = self._count_outbound_since(last_in, tgt)
        if not ok:
            try:
                con = sqlite3.connect("file:%s?mode=ro" % MSG_DB, uri=True, timeout=5)
                r = con.execute(
                    "select count(*) from quote_messages where direction='outbound' and conversation_id=? and created_at > ?",
                    (tgt, last_in)).fetchone()
                con.close()
                total = int(r[0] or 0) if r else 0
            except Exception:
                total = 0
        return total, last_in

    def _quota_left(self, target=None):
        """真实剩余额度：统计 bot 发出的全部消息（含聊天回复），以用户最后一条消息为轮次起点"""
        tgt = target or self.target
        now = time.time()
        cache = self.__dict__.setdefault("_quota_cache", {})
        hit = cache.get(tgt)
        if hit and now - hit[0] < 2.0:      # 同一次 flush 内复用，避免反复扫日志
            used, last_in = hit[1], hit[2]
        else:
            used, last_in = self._quota_used(tgt)
            cache[tgt] = (now, used, last_in)
        if used is None:  # 读库失败时退回本地计数
            q = (self.quotas or {}).get(tgt) or {}
            start = float(q.get("window_start") or 0)
            if not start or now - start > self.quota_window:
                return 0
            used = int(q.get("used") or 0)
        if not last_in:
            # 没有入站记录（新装/库重建）时按满额度处理，否则会永久停摆
            if not getattr(self, "_no_inbound_logged", False):
                self._no_inbound_logged = True
                log.info(f"【推送_{self.name}】未找到入站记录，按满额度处理")
            return self.quota_max
        if now - last_in / 1000.0 > self.quota_window:
            return 0  # 超过 24 小时无互动，context_token 已失效
        return max(0, self.quota_max - used)

    def _consume_quota(self, target=None, n=1):
        tgt = target or self.target
        q = self.quotas.get(tgt) or {"window_start": time.time(), "used": 0}
        if not q.get("window_start"):
            q["window_start"] = time.time()
        q["used"] = int(q.get("used") or 0) + n
        self.quotas[tgt] = q
        self._save_json(QUOTAS, self.quotas)

    def _session_ok(self, target=None):
        """探测 iLink 会话是否可用（errcode -14 = 发送会被静默丢弃）"""
        tgt = target or self.target
        now = time.time()
        cache = self.__dict__.setdefault("_probe_cache", {})
        hit = cache.get(tgt)
        if hit and now - hit[0] < 120:
            return hit[1]
        ok = True
        try:
            acct_id = self._account_for(tgt)
            acc_dir = os.path.join(WX_DIR, "accounts")
            path = os.path.join(acc_dir, acct_id + ".json") if acct_id else ""
            if not (path and os.path.exists(path)):
                cands = [p for p in glob.glob(os.path.join(acc_dir, "*-im-bot.json"))
                         if "context" not in p and "sync" not in p]
                path = cands[0] if cands else ""
            if path:
                with open(path, "r", encoding="utf-8") as fh:
                    acc = json.load(fh)
                ctxp = path.replace(".json", ".context-tokens.json")
                ctx = ""
                if os.path.exists(ctxp):
                    with open(ctxp, "r", encoding="utf-8") as fh:
                        ctx = (json.load(fh) or {}).get(acc.get("userId"), "")
                r = requests.post(
                    acc["baseUrl"].rstrip("/") + "/ilink/bot/getconfig",
                    json={"ilink_user_id": acc["userId"], "context_token": ctx,
                          "base_info": {"channel_version": "2.4.10", "bot_agent": "openclaw"}},
                    headers=_ilink_headers(acc["token"]), timeout=10)
                body = r.json() if r.text.strip().startswith("{") else {}
                ok = not body.get("errcode")
        except Exception as e:
            log.error(f"【推送_{self.name}】会话探测异常：{e}")
            ok = True
            cache[tgt] = (now, ok)
        return ok

    def _flush_loop(self):
        while True:
            time.sleep(self.flush_interval)
            try:
                self.flush()
            except Exception as e:
                log.error(f"【推送_{self.name}】后台补发异常：{e}")

    def _label(self, tgt):
        if "o9cq805" in tgt:
            return "微信A"
        if "o9cq808" in tgt:
            return "微信B"
        return "微信" + str(tgt)[:6]

    def _queued_titles(self, tgt):
        titles = []
        for it in self.outbox:
            if (it.get("target") or self.target) != tgt:
                continue
            t = it.get("title") or "番剧更新"
            if t not in titles:
                titles.append(t)
        return titles

    def _quota_warn(self, tgt, left):
        """额度只剩最后 1 条时提醒。

        只在「确实有内容要发、但额度不够」时才消耗这条额度，
        不会因为定时检查而白白烧掉。每轮每个微信号只提醒一次。
        """
        if not self.outbox:
            return
        need = 2 if self.send_link else 1
        if left >= need + self.reserve:
            return          # 额度还够发，不用打扰
        if left < 1:
            return          # 发不出去，告警也发不了
        if self._agent_busy():
            return          # 对话进行中，不抢额度

        titles = self._queued_titles(tgt)
        if not titles:
            return  # 没有待发内容，保留这最后一条额度

        last_in = self._last_inbound_ms(tgt)
        state = self._load_json(ALERT, {})
        rec = state.get(tgt) or {}
        if rec.get("last_in") == last_in:
            return  # 本轮已提醒过

        body = "\n".join("· " + t for t in titles[:6])
        if len(titles) > 6:
            body += "\n· 等共 %d 条" % len(titles)

        msg = ("⚠️ 推送被额度卡住：剩 %d 条，单条需 %d 条，保留 %d 条给对话\n"
               "有 %d 条番剧在排队：\n%s\n"
               "回复任意消息，即可恢复额度并自动补发"
               % (left, need, self.reserve, len(titles), body))

        ok, out = self._send(msg, target=tgt)
        if ok:
            state[tgt] = {"last_in": last_in, "ts": int(time.time())}
            self._save_json(ALERT, state)
            log.info(f"【推送_{self.name}】{self._label(tgt)} 配额见底，已用最后 1 条发出提醒")
        else:
            log.info(f"【推送_{self.name}】{self._label(tgt)} 配额提醒发送失败：{out[:70]}")

    def _check_all_quotas(self):
        """每轮检查所有 target 的余额（有积压或没积压都检查）"""
        for t in (self.targets or [self.target]):
            self._quota_warn(t, self._quota_left(t))

    def flush(self):
        """把队列里的消息尽量发出去；额度用完就停，下次再试"""
        try:
            self._flush_locked()
        except Exception as e:
            log.error(f"【推送_{self.name}】flush 异常：{e}")

    def _flush_locked(self):
        with self._lock:
            if not self.outbox:
                return
            if self._agent_busy():
                if time.time() - getattr(self, "_busy_log_ts", 0) > 600:
                    self._busy_log_ts = time.time()
                    log.info(f"【推送_{self.name}】对话进行中，{len(self.outbox)} 条推送暂缓")
                return
            if not self._session_ok(self.outbox[0].get("target") or self.target if self.outbox else None):
                if time.time() - getattr(self, "_dead_log_ts", 0) > 1800:
                    self._dead_log_ts = time.time()
                    log.info(f"【推送_{self.name}】微信会话不可用（errcode -14），{len(self.outbox)} 条排队中，暂不发送")
                return
            if time.time() < self._cooldown_until:
                return
            self.__dict__.pop("_quota_cache", None)
            def _need(x):
                # 一条完整推送需要：卡片 1 条 + 链接文本 1 条
                link = x.get("link") if (self.send_link and not x.get("link_sent")) else None
                return 1 + (1 if link else 0)

            if not any(self._quota_left(i.get("target") or self.target) >= _need(i) + self.reserve
                       for i in self.outbox):
                left_now = self._quota_left(self.outbox[0].get("target") or self.target)
                log.info(f"【推送_{self.name}】配额不足（剩 {left_now} 条，单条需 {_need(self.outbox[0])} 条），"
                         f"队列保留 {len(self.outbox)} 条，等待回复重置")
                self._check_all_quotas()
                return
            changed = False
            remaining = []
            for item in self.outbox:
                tgt = item.get("target") or self.target
                # 配额逐条检查：不够发完整一条（卡片+链接）就整条保留，绝不发半条
                need = _need(item)
                left = self._quota_left(tgt)
                if left < need + self.reserve:
                    remaining.append(item)
                    log.info(f"【推送_{self.name}】配额 {left} < 需要 {need}，"
                             f"整条排队：{item.get('title', '')[:20]}")
                    continue
                ok = True
                if not item.get("card_sent"):
                    path = item.get("card") or ""
                    # 卡片图丢了（重启/清缓存），尝试重新渲染
                    if not (path and os.path.exists(path)):
                        path = self._rerender(item)
                        item["card"] = path
                        changed = True
                    if path and os.path.exists(path):
                        ok, out = self._send("", path, target=tgt)
                        if ok:
                            item["card_sent"] = True
                            self.__dict__.get("_quota_cache", {}).pop(tgt, None)
                            self._consume_quota(tgt)
                            self._fail_streak = 0
                            changed = True
                            try:
                                os.remove(path)
                            except Exception:
                                pass
                        else:
                            self._fail_streak += 1
                            self._cooldown_until = time.time() + 300
                            log.info(f"【推送_{self.name}】卡片发送失败，5分钟后重试：{out[:80]}")
                    else:
                        # 渲染不了就降级发文本，至少不丢消息
                        ok, out = self._send(item.get("link") or item.get("title", ""), target=tgt)
                        if ok:
                            item["card_sent"] = True
                            item["link_sent"] = True
                            changed = True
                            log.info(f"【推送_{self.name}】降级为文本发送：{item.get('title', '')[:30]}")
                        else:
                            self._fail_streak += 1
                if ok and self.send_link and not item.get("link_sent") and item.get("link"):
                    left = self._quota_left(tgt)
                    if left <= 0:
                        remaining.append(item)
                        changed = True
                        continue
                    after = max(0, left - 1)   # 本条文本发出后剩余
                    if after >= 2:
                        hint = ""
                    elif after == 1:
                        hint = "⚠️ 额度仅剩 1 条，回复任意消息可重置"
                    else:
                        hint = "⚠️ 额度已用尽，后续推送将排队；回复任意消息即可恢复"
                    text = item["link"] + f"\n剩余配额 {after}/{self.quota_max}"
                    if hint:
                        text += "\n" + hint
                    ok2, out2 = self._send(text, target=tgt)
                    if ok2:
                        item["link_sent"] = True
                        self._consume_quota(tgt)
                        self._fail_streak = 0
                        changed = True
                    else:
                        self._fail_streak += 1
                        log.info(f"【推送_{self.name}】额度不足，链接排队中：{out2[:80]}")
                if item.get("card_sent") and (item.get("link_sent") or not self.send_link or not item.get("link")):
                    self.seen.add(item["id"])
                    changed = True
                    log.info(f"【推送_{self.name}】补发完成：{item.get('title', '')[:30]}")
                else:
                    remaining.append(item)
            self.outbox = remaining
            if changed:
                self._save_json(OUTBOX, self.outbox)
                self._save_json(SEEN, self.seen)
            self._check_all_quotas()

    def _rerender(self, item):
        """卡片图丢失时按存档参数重新渲染"""
        p = item.get("payload") or {}
        if not p or not self.render_card:
            return ""
        try:
            from .card import render_card
            path = f"/tmp/clawbot_card_{int(time.time() * 1000)}.png"
            render_card(p.get("title", ""), p.get("content", ""), p.get("up_name", "后宫补番"),
                        p.get("url", ""), path, cover_url=p.get("pic_url"),
                        avatar_url=p.get("avatar"), qr_content=p.get("qr_link") or p.get("link"),
                        code_text=p.get("code_text", ""), style=self.card_style)
            return path
        except Exception as e:
            log.error(f"【推送_{self.name}】补渲染失败：{e}")
            return ""

    def _judge(self, title, content, up_name="该 UP 主"):
        body = {
            "model": self.model,
            "messages": [{"role": "user",
                          "content": PROMPT.format(up=up_name, title=title, content=content[:1200])}],
            "temperature": 0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        r = requests.post(f"{self.api_base}/chat/completions", json=body, timeout=30,
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "Content-Type": "application/json"})
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        return bool(data.get("push")), str(data.get("reason", ""))

    def push(self, title, content, jump_url=None, pic_url=None, extend_data=None):
        extend_data = extend_data or {}
        raw = extend_data.get("dynamic_raw_data") or {}
        did = str(raw.get("id_str") or "")
        if did and did in self.seen:
            return
        if did and any(i.get("id") == did for i in self.outbox):
            return

        text = TIME_TAIL_RE.sub("", content or "").strip()
        full = _raw_text(raw) or text
        blob = f"{title} {full}"
        up_name = str(extend_data.get("up_name") or "该 UP 主")

        if EP_RE.search(blob):
            ok, reason = True, "含集数，判定为番剧更新"
        elif not full.strip():
            ok = self.push_image_only
            reason = "纯图片动态"
        else:
            try:
                ok, reason = self._judge(title, full, up_name)
            except Exception as e:
                log.error(f"【推送_{self.name}】AI 判断失败：{e}")
                ok, reason = self.fail_open, "判断失败，按默认放行"

        if not ok:
            log.info(f"【推送_{self.name}】不推送：{reason}")
            return

        m = NAME_RE.search(full)
        card_title = m.group(1).strip() if m else "番剧更新"

        # 已完结番剧的「第N集 / 全N集」一律视为补档，不推送
        if EP_RE.search(blob):
            state = self._airing_state(card_title)
            if state == "finished":
                log.info(f"【推送_{self.name}】跳过：{card_title} 已完结（补档动态）")
                return

        # 跨 UP 去重：同一部番今天已经有人推过，就不再重复
        raw_uid = str(((raw.get("modules") or {}).get("module_author") or {}).get("mid") or "")
        anime_key = self._anime_key(full)
        season = self._season_no(full)

        with self._lock:
            ok_claim, prev = self._claim_anime(anime_key, raw_uid, did, season)
        if not ok_claim:
            log.info(f"【推送_{self.name}】跳过重复番剧：{anime_key}（今天已由 uid {prev.get('uid')} 推送）")
            return
        url = jump_url or "https://www.bilibili.com"
        # 统一用 B站 直链（分P视频自动带 ?p=最新集），不再走自建短链
        direct = url if "bilibili.com/video/" in (url or "") else ""
        link = direct or qr_content_for(raw, url)
        qr_link = link

        card = ""
        if self.render_card:
            try:
                from .card import render_card
                card = f"/tmp/clawbot_card_{int(time.time() * 1000)}.png"
                render_card(card_title, full, up_name, url, card,
                            cover_url=pic_url, avatar_url=extend_data.get("avatar_url"),
                            qr_content=qr_link, code_text=code_text_for(raw),
                            style=self.card_style)
            except Exception as e:
                log.error(f"【推送_{self.name}】卡片渲染失败：{e}")
                card = ""

        payload = {"title": card_title, "content": full, "up_name": up_name,
                   "url": url, "pic_url": pic_url,
                   "avatar": extend_data.get("avatar_url"),
                   "link": link, "qr_link": qr_link, "code_text": code_text_for(raw)}

        with self._lock:
            # 每个 target 单独一条队列项：各自计数、各自补发
            copied_all = True
            for t in (self.targets or [self.target]):
                cpath = card
                if card and len(self.targets) > 1:
                    cpath = card[:-4] + ("_%d.png" % (abs(hash(t)) % 100000))
                    try:
                        shutil.copy(card, cpath)
                    except Exception:
                        cpath = card
                        copied_all = False
                item = {"id": did or str(time.time()), "target": t,
                        "title": card_title, "card": cpath,
                        "link": f"{card_title}\n{link}",
                        "card_sent": False, "link_sent": False,
                        "ts": int(time.time()), "payload": payload}
                self.outbox.append(item)
            # 分发给多个 target 时，原始卡片已复制，删掉避免 /tmp 堆积
            if copied_all and card and len(self.targets) > 1:
                try:
                    os.remove(card)
                except Exception:
                    pass
            # 队列上限：额度长期为 0 时防止无限增长
            MAX_OUTBOX = 60
            if len(self.outbox) > MAX_OUTBOX:
                drop = len(self.outbox) - MAX_OUTBOX
                self.outbox = self.outbox[-MAX_OUTBOX:]
                log.warning(f"【推送_{self.name}】队列超限，丢弃最旧 {drop} 条")
            # 已推送 id 只保留近期，防止文件无限增长
            if len(self.seen) > 2000:
                self.seen = set(list(self.seen)[-1000:])
            self._save_json(OUTBOX, self.outbox)
        log.info(f"【推送_{self.name}】已入队：{card_title[:30]}（{reason}），队列 {len(self.outbox)} 条")
        self._fail_streak = 0
        self.flush()
