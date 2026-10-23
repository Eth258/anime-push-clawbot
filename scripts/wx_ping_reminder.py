"""会话保活提醒：24 小时不互动 context_token 会失效，提前在合适时段提醒用户回话"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/aio-dynamic-push")

NODE = "/root/.nvm/versions/node/v24.22.1/bin/node"
OPENCLAW = "/root/.nvm/versions/node/v24.22.1/lib/node_modules/openclaw/openclaw.mjs"
DB = "/root/.openclaw/openclaw-weixin/ref-messages.sqlite"
STATE = "/root/.wx_ping_state.json"
CONFIG = "/opt/aio-dynamic-push/config.yml"

# 允许提醒的时段（本地时间）：避开深夜、凌晨、午休
ALLOWED = [("08:00", "12:00"), ("14:00", "21:30")]
EARLIEST_HOURS = 18   # 最早在最后一条消息后 18 小时提醒
LATEST_HOURS = 23     # 最晚不超过 23 小时（留 1 小时余量）


def _hm(dt):
    return dt.hour * 60 + dt.minute


def _windows():
    out = []
    for a, b in ALLOWED:
        ah, am = map(int, a.split(":"))
        bh, bm = map(int, b.split(":"))
        out.append((ah * 60 + am, bh * 60 + bm))
    return out


def in_allowed(dt):
    m = _hm(dt)
    return any(a <= m < b for a, b in _windows())


def next_allowed(dt):
    """返回不早于 dt 的下一个允许时刻"""
    for _ in range(3):
        if in_allowed(dt):
            return dt
        m = _hm(dt)
        later = [(a, b) for a, b in _windows() if m < a]
        if later:
            a = min(later)[0]
            return dt.replace(hour=a // 60, minute=a % 60, second=0, microsecond=0)
        dt = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


def prev_allowed_before(dt):
    """返回不晚于 dt 的最近一个允许时刻"""
    for _ in range(3):
        if in_allowed(dt):
            return dt
        m = _hm(dt)
        earlier = [(a, b) for a, b in _windows() if b <= m]
        if earlier:
            b = max(earlier)[1]
            return dt.replace(hour=b // 60, minute=max(0, b % 60 - 1), second=0, microsecond=0)
        dt = (dt - timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)
    return dt


def plan_time(last_in_dt):
    """计算应该在什么时候提醒"""
    earliest = last_in_dt + timedelta(hours=EARLIEST_HOURS)
    latest = last_in_dt + timedelta(hours=LATEST_HOURS)
    t = next_allowed(earliest)
    if t <= latest:
        return t
    t2 = prev_allowed_before(latest)
    if t2 > last_in_dt + timedelta(hours=8):
        return t2
    return None


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    try:
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def last_inbound_ms(target):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
        r = con.execute("select max(created_at) from quote_messages where direction='inbound' and conversation_id=?",
                        (target,)).fetchone()
        con.close()
        return int(r[0] or 0) if r else 0
    except Exception:
        return 0


def account_for(target):
    import glob
    try:
        for path in glob.glob("/root/.openclaw/openclaw-weixin/accounts/*-im-bot.json"):
            if "context" in path or "sync" in path:
                continue
            acc = json.load(open(path))
            if str(acc.get("userId", "")).strip() == str(target).strip():
                return os.path.basename(path)[:-5]
    except Exception:
        pass
    return ""


def targets():
    import yaml
    try:
        d = yaml.safe_load(open(CONFIG, encoding="utf-8"))
        for ch in d.get("push_channel", []):
            if ch.get("type") == "clawbot":
                return [t for t in (ch.get("targets") or [ch.get("target")]) if t]
    except Exception:
        pass
    return []


def main():
    st = load_state()
    now = datetime.now()
    for target in targets():
        last_ms = last_inbound_ms(target)
        if not last_ms:
            continue
        last_dt = datetime.fromtimestamp(last_ms / 1000.0)
        age_h = (now - last_dt).total_seconds() / 3600.0
        if age_h >= 24:
            continue  # 已经过期，提醒也没意义
        fire_at = plan_time(last_dt)
        if not fire_at:
            continue
        rec = st.get(target) or {}
        if rec.get("last_in") == last_ms:
            continue  # 本轮已提醒
        if now < fire_at:
            continue
        acct = account_for(target)
        if age_h >= 18:
            msg = ("⏰ 距上次对话已 %.0f 小时，微信会话凭据 24 小时不用就会失效。\n"
                   "回我一句任意消息即可保活。" % age_h)
        else:
            msg = ("🔔 提醒：微信会话凭据每 24 小时要用一次，否则推送通道会断。\n"
                   "上次对话是 %.0f 小时前，现在回我一句就能保活，免得半夜失效。" % age_h)
        cmd = [NODE, OPENCLAW, "message", "send", "--channel", "openclaw-weixin",
               "--target", target, "-m", msg]
        if acct:
            cmd += ["--account", acct]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = p.returncode == 0
        except Exception:
            ok = False
        if ok:
            st[target] = {"last_in": last_ms, "sent_at": int(time.time())}
            save_state(st)
            print("已提醒:", target, "age_h=%.1f" % age_h)
        else:
            print("提醒失败:", target)


if __name__ == "__main__":
    main()
