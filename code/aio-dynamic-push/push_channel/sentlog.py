#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发送记录（SQLite）

把网关日志里的「消息起始行」增量归集到 sent 表，作为配额统计的唯一数据源。

为什么不每次扫日志：
  - 日志按天滚动、位于 /tmp，重启或清理即丢
  - 每天 1~5 MB，全量扫描慢且无法回溯跨天会话
  - 位点持久化后只读新增字节，历史行留在库里

三类起始行（每条消息恰好一次）：
  outbound: to=X ... textLen=            agent 发的文本
  sendMessageWeixin: contextToken missing for to=X   CLI 发的文本
  sendImageMessageWeixin: to=X filekey=  图片
"""
import json
import os
import re
import sqlite3
import time
import datetime as _dt

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sent.sqlite")
LOGDIR = "/tmp/openclaw"
RETENTION_DAYS = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS sent (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  target TEXT    NOT NULL,
  kind   TEXT    NOT NULL,
  origin TEXT,
  ts     INTEGER NOT NULL,
  src    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sent_target_ts ON sent(target, ts);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_sent ON sent(target, kind, ts);
CREATE TABLE IF NOT EXISTS cursor (
  file   TEXT PRIMARY KEY,
  offset INTEGER NOT NULL DEFAULT 0,
  mtime  REAL
);
"""

_TGT_RE = re.compile(r"to=([A-Za-z0-9_\-]+@im\.wechat)")


def _conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def _parse(obj):
    """从一条日志对象里判定是否属于「消息起始行」，返回 (target, kind, origin, ts_ms)"""
    msg = str(obj.get("1") or "")
    kind = origin = None
    if "outbound: to=" in msg and "textLen=" in msg:
        kind, origin = "text", "agent"
    elif "sendMessageWeixin: contextToken missing for to=" in msg:
        kind, origin = "text", "cli"
    elif "sendImageMessageWeixin: to=" in msg and "filekey=" in msg:
        kind, origin = "image", "cli"
    if not kind:
        return None
    m = _TGT_RE.search(msg)
    if not m:
        return None
    try:
        ts = obj["_meta"]["date"]
        ms = int(_dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None
    return m.group(1).lower(), kind, origin, ms


def _ingest_file(con, path, force=False):
    try:
        st = os.stat(path)
    except OSError:
        return 0
    row = None if force else con.execute(
        "select offset from cursor where file=?", (path,)).fetchone()
    off = int(row[0]) if row else 0
    if st.st_size < off:          # 文件被截断或重写
        off = 0
    if off >= st.st_size:
        return 0
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    cut = data.rfind(b"\n")
    if cut < 0:
        return 0
    chunk = data[:cut + 1]
    n = 0
    for raw in chunk.split(b"\n"):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        rec = _parse(obj)
        if not rec:
            continue
        con.execute(
            "insert or ignore into sent(target, kind, origin, ts, src) values(?,?,?,?,?)",
            (rec[0], rec[1], rec[2], rec[3], os.path.basename(path)))
        n += 1
    con.execute(
        "insert into cursor(file, offset, mtime) values(?,?,?) "
        "on conflict(file) do update set offset=excluded.offset, mtime=excluded.mtime",
        (path, off + len(chunk), st.st_mtime))
    return n


def ingest(days=2, force=False):
    """归集最近 N 天的日志，返回本次新增条数"""
    con = _conn()
    added = 0
    now = _dt.datetime.now()
    try:
        for delta in range(days):
            day = now - _dt.timedelta(days=delta)
            path = os.path.join(LOGDIR, "openclaw-%s.log" % day.strftime("%Y-%m-%d"))
            added += _ingest_file(con, path, force=force)
        con.commit()
    finally:
        con.close()
    return added


def count_used(target, since_ms):
    """某 target 在 since_ms 之后发出的消息条数"""
    con = _conn()
    try:
        r = con.execute("select count(*) from sent where target=? and ts>?",
                        (str(target).lower(), int(since_ms))).fetchone()
        return int(r[0] or 0)
    finally:
        con.close()


def recent(target=None, limit=20):
    con = _conn()
    try:
        if target:
            rows = con.execute(
                "select ts, kind, origin, src from sent where target=? order by ts desc limit ?",
                (str(target).lower(), limit)).fetchall()
        else:
            rows = con.execute(
                "select target, ts, kind, origin from sent order by ts desc limit ?",
                (limit,)).fetchall()
        return rows
    finally:
        con.close()


def prune(days=RETENTION_DAYS):
    cutoff = int((time.time() - days * 86400) * 1000)
    con = _conn()
    try:
        cur = con.execute("delete from sent where ts < ?", (cutoff,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def reset_cursor(path=None):
    """清空位点（下次全量重读），用于回填或结构变更后重建"""
    con = _conn()
    try:
        if path:
            con.execute("delete from cursor where file=?", (path,))
        else:
            con.execute("delete from cursor")
            con.execute("delete from sent")
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        reset_cursor()
        print("已清空，重新归集:", ingest(days=3, force=True), "条")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        ingest()
        con = _conn()
        for row in con.execute("select target, kind, count(*), datetime(min(ts)/1000,'unixepoch','+8 hours') from sent group by target, kind"):
            print(row)
        con.close()
    else:
        print("本次归集:", ingest(), "条")
