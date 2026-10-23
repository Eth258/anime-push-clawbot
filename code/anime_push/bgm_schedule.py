#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""今日番剧放送表（bangumi-data 数据源，北京时间）

用法:
  python3 bgm_schedule.py                 # 今天(北京时间)
  python3 bgm_schedule.py --day 0         # 偏移天数, 支持 -1 / +1
  python3 bgm_schedule.py --json          # 结构化输出
  python3 bgm_schedule.py --all           # 含子供向/长寿番(默认已排除)
  python3 bgm_schedule.py --season 2026-10

数据源: https://unpkg.com/bangumi-data@0.3/dist/data.json
  字段 broadcast 为 ISO8601 重复规则 R/<起始>/<周期>, 据此推算每周放送时刻。
  时区: 输出一律北京时间 (UTC+8)。
  缓存: 本地 bd.json, 超过 12 小时自动重新下载 (需走代理)。
"""
import json
import os
import sys
import time
import datetime
import urllib.request

import net

DATA_URL = "https://unpkg.com/bangumi-data@0.3/dist/data.json"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bd.json")
CACHE_TTL = 12 * 3600
PROXY = net.proxy_url()
UA = net.UA

BJ = datetime.timezone(datetime.timedelta(hours=8))

# 凌晨分界: 早于该小时(北京时间)的放送归入前一天。
# 用 1 点, 让 00:00-00:59 的深夜档留在当天卡片里, 不会漏。
DAY_CUTOFF_HOUR = 1

# 子供向 / 长寿番 / 特摄（默认排除）
KIDS_KEYS = [
    # 日文原名
    "サザエさん", "アンパンマン", "クレヨンしんちゃん", "ドラえもん",
    "ちびまる子ちゃん", "シルバニアファミリー", "おしりたんてい",
    "プリキュア", "仮面ライダー", "スーパー戦隊", "ウルトラマン",
    "デジモン", "妖怪ウォッチ", "たまごっち", "ポケモン", "ポケットモンスター",
    "ベイブレード", "ゾイド", "カードファイト", "バトルスピリッツ",
    "ガンダムビルド", "ふしぎ駄菓子屋", "忍たま乱太郎",
    "しまじろう", "いないいないばあ", "おかあさんといっしょ",
    "トミカ", "プラレール", "ちいかわ", "ぼのぼの",
    # 中文译名
    "暖暖日记", "蜡笔小新", "哆啦A梦", "樱桃小丸子",
    "面包超人", "海螺小姐", "光之美少女", "假面骑士",
    "超级战队", "奥特曼", "宝可梦", "精灵宝可梦",
    "数码宝贝", "妖怪手表", "面包小偷", "甜甜私房猫",
    "我们这一家", "小丸子", "游乐场", "巧虎",
]

# 长寿番判定: begin 早于今天这么久, 且仍在放送
LONGRUN_YEARS = 3


META_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "meta_cache.json")
META_TTL = 30 * 24 * 3600
_meta = {"data": None, "dirty": False}


def _load_meta():
    if _meta["data"] is not None:
        return _meta["data"]
    try:
        with open(META_CACHE, encoding="utf-8") as f:
            _meta["data"] = json.load(f)
    except Exception:
        _meta["data"] = {}
    return _meta["data"]


def _save_meta():
    if not _meta.get("dirty"):
        return
    try:
        tmp = META_CACHE + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_meta["data"], f, ensure_ascii=False)
        os.replace(tmp, META_CACHE)
        _meta["dirty"] = False
    except Exception:
        pass


def bangumi_meta(subject_id):
    """条目元信息（name_cn / tags），落盘缓存 30 天"""
    if not subject_id:
        return {}
    sid = str(subject_id)
    cache = _load_meta()
    hit = cache.get(sid)
    if hit and time.time() - hit.get("ts", 0) < META_TTL:
        return hit

    data = {}
    try:
        import json as _json
        import net as _net
        body, _ = _net.fetch("https://api.bgm.tv/v0/subjects/%s" % sid, timeout=20)
        data = _json.loads(body.decode("utf-8"))
    except Exception:
        data = {}

    entry = {
        "name_cn": (data.get("name_cn") or "").strip(),
        "tags": [t.get("name") for t in (data.get("tags") or []) if t.get("name")],
        "ts": time.time(),
    }
    if entry["name_cn"] or entry["tags"]:
        cache[sid] = entry
        _meta["dirty"] = True
        _save_meta()
    return entry


# Bangumi 条目标签中表示子供向的词
KIDS_TAGS = {"子供向", "幼儿", "少儿", "亲子", "早教"}
_tag_cache = {}
_cn_cache = {}


def bangumi_tags(subject_id):
    """取 Bangumi 条目标签（落盘缓存 30 天）"""
    entry = bangumi_meta(subject_id)
    return set(entry.get("tags") or [])


def is_kids_show(name, zh, tags=None):
    """子供向/特摄: 关键词(中日双语) + Bangumi 标签"""
    for text in (name or "", zh or ""):
        if any(k in text for k in KIDS_KEYS):
            return True
    if tags and (tags & KIDS_TAGS):
        return True
    return False


def is_longrun(begin_iso, now, years=LONGRUN_YEARS):
    """长寿番: 开播早于 years 年前且仍在播"""
    if not begin_iso:
        return False
    try:
        start = datetime.datetime.fromisoformat(begin_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    return (now - start).days > years * 365


def build_opener():
    """统一走 net.opener(), 代理配置集中在 net.py"""
    return net.opener()


def load_data(force=False):
    need = force or not os.path.exists(CACHE) or (time.time() - os.path.getmtime(CACHE) > CACHE_TTL)
    if need:
        req = urllib.request.Request(DATA_URL, headers={"User-Agent": UA})
        with build_opener().open(req, timeout=60) as r:
            raw = r.read()
        with open(CACHE, "wb") as f:
            f.write(raw)
    with open(CACHE, encoding="utf-8") as f:
        return json.load(f)


def parse_period(br):
    """R/2026-10-07T15:00:00.000Z/P7D -> (start_utc, timedelta)"""
    if not br or not br.startswith("R/"):
        return None, None
    parts = br.split("/")
    if len(parts) < 3:
        return None, None
    try:
        st = datetime.datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
    except ValueError:
        return None, None
    per = parts[2]
    try:
        n = int(per[1:-1])
    except (ValueError, IndexError):
        return None, None
    if per.startswith("P") and per.endswith("D"):
        return st, datetime.timedelta(days=n)
    if per.startswith("P") and per.endswith("W"):
        return st, datetime.timedelta(weeks=n)
    return None, None


def slot_on_day(st, period, day):
    """返回归属于 day 的放送时刻, 无则 None

    「一天」为 day 的 DAY_CUTOFF_HOUR 点到次日 DAY_CUTOFF_HOUR 点,
    凌晨放送(如 00:30)归到前一天。
    """
    day_start = datetime.datetime.combine(
        day, datetime.time(DAY_CUTOFF_HOUR, 0), tzinfo=BJ)
    day_end = day_start + datetime.timedelta(days=1)
    if st > day_end:
        return None
    k = max(0, int((day_start - st).total_seconds() // period.total_seconds()))
    for kk in range(k, k + 3):
        s = st + period * kk
        if day_start <= s < day_end:
            return s
    return None


def title_cn_from_bgm(subject_id):
    """Bangumi 条目的 name_cn（落盘缓存 30 天）"""
    if not subject_id:
        return ""
    entry = bangumi_meta(subject_id)
    return (entry.get("name_cn") or "").strip()


OVERRIDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "title_overrides.json")
_ov_cache = {"data": None, "mtime": 0}


def load_overrides():
    """人工/agent 核实过的中文名, 以 bangumi id 为键"""
    if not os.path.exists(OVERRIDE_PATH):
        return {}
    mtime = os.path.getmtime(OVERRIDE_PATH)
    if _ov_cache["data"] is not None and _ov_cache["mtime"] == mtime:
        return _ov_cache["data"]
    try:
        with open(OVERRIDE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    _ov_cache["data"] = data
    _ov_cache["mtime"] = mtime
    return data


def override_title(subject_id):
    if not subject_id:
        return ""
    entry = load_overrides().get(str(subject_id)) or {}
    return (entry.get("title") or "").strip()


def title_zh(item, subject_id=None):
    """中文标题: 优先 bangumi-data 译文, 缺失时查 Bangumi name_cn"""
    ov = override_title(subject_id)
    if ov:
        return ov
    tr = item.get("titleTranslate") or {}
    for key in ("zh-Hans", "zh-Hant"):
        v = tr.get(key) or []
        if v and v[0].strip():
            return v[0].strip()
    cn = title_cn_from_bgm(subject_id)
    if cn:
        return cn
    return ""


def site_link(item, site):
    for s in item.get("sites", []):
        if s.get("site") == site:
            return s.get("id")
    return None


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    show_all = "--all" in args
    offset = 0
    if "--day" in args:
        i = args.index("--day")
        if i + 1 < len(args):
            offset = int(args[i + 1])
    now_bj = datetime.datetime.now(BJ)
    # 凌晨(未过分界)时, 当前仍算前一天
    if now_bj.hour < DAY_CUTOFF_HOUR:
        now_bj -= datetime.timedelta(days=1)
    target = (now_bj + datetime.timedelta(days=offset)).date()

    try:
        data = load_data(force="--refresh" in args)
    except Exception as e:
        print("拉取 bangumi-data 失败: %s" % e, file=sys.stderr)
        print("提示: 需要代理, 当前 BGM_PROXY=%s" % PROXY, file=sys.stderr)
        return 1

    out = collect(data, target, show_all=show_all)

    if as_json:
        print(json.dumps({
            "date": target.isoformat(),
            "weekday": "一二三四五六日"[target.weekday()],
            "count": len(out),
            "items": out,
        }, ensure_ascii=False, indent=2))
        return 0

    wd = "一二三四五六日"[target.weekday()]
    print("%s 周%s 日本动画放送（北京时间，%d 部）" % (target, wd, len(out)))
    if not out:
        print("  今天没有符合条件的番。")
        return 0
    shown_next = False
    for it in out:
        if it["next_day"] and not shown_next:
            print("  —— 次日凌晨 ——")
            shown_next = True
        tag = ""
        if it["mikan"]:
            tag = "  [蜜柑]"
        elif it["bilibili"]:
            tag = "  [B站]"
        orig = ("  / " + it["orig"]) if it["orig"] else ""
        print("  %s  %s%s%s" % (it["time"], it["title"], orig, tag))
    return 0


def collect(data, target, show_all=False):
    """筛选 target 当天的放送条目, 按 当天→次日凌晨 排序"""
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for it in data["items"]:
        if it.get("lang") != "ja":
            continue
        if it.get("type") != "tv":
            continue
        st, period = parse_period(it.get("broadcast"))
        if not st or not period:
            continue
        # 是否在播
        end_s = it.get("end") or ""
        if st > now:
            continue
        if end_s:
            try:
                if datetime.datetime.fromisoformat(end_s.replace("Z", "+00:00")) < now:
                    continue
            except ValueError:
                pass
        slot = slot_on_day(st, period, target)
        if not slot:
            continue
        bgm_id = site_link(it, "bangumi")
        zh = title_zh(it, bgm_id)
        name = it.get("title", "")
        if not show_all:
            if is_kids_show(name, zh, bangumi_tags(bgm_id)):
                continue
            if is_longrun(it.get("begin"), now):
                continue
        bj = slot.astimezone(BJ)
        out.append({
            "time": bj.strftime("%H:%M"),
            "next_day": bj.date() != target,
            "title": zh or name,
            "orig": name if zh else "",
            "bangumi": bgm_id,
            "mikan": site_link(it, "mikan"),
            "bilibili": site_link(it, "bilibili"),
        })

    # 先按归属日(当天在前, 次日凌晨在后), 再按时刻
    out.sort(key=lambda x: (x["next_day"], x["time"], x["title"]))
    return out


if __name__ == "__main__":
    sys.exit(main())
