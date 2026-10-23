#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本季度全量预热缓存：封面 / 分集表 / 条目元信息"""
import os
import sys
import json
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bgm_schedule as m
import episodes as eps
import covers_fetch

LOG = os.path.join(HERE, "precache.log")
BD = os.path.join(HERE, "bd.json")
WORKERS = 6

stats = {"cover": 0, "eps": 0, "meta": 0, "fail": []}
lock = __import__("threading").Lock()


def log(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def bangumi_id(item):
    for s in item.get("sites", []):
        if s.get("site") == "bangumi":
            return s.get("id")
    return None


def season_ids():
    with open(BD, encoding="utf-8") as f:
        items = json.load(f)["items"]
    now = datetime.datetime.now(datetime.timezone.utc)
    ids = {}
    for it in items:
        if it.get("lang") != "ja" or it.get("type") != "tv":
            continue
        begin = (it.get("begin") or "")[:10]
        ongoing = begin < "2026-10-01" and (
            not it.get("end") or it.get("end") > now.isoformat())
        new_season = begin[:7] in ("2026-10", "2026-11", "2026-12")
        if not (ongoing or new_season):
            continue
        sid = bangumi_id(it)
        if sid:
            ids[sid] = it.get("title")
    return ids


def work(sid, title):
    got = {"cover": False, "eps": False, "meta": False}
    try:
        got["cover"] = bool(covers_fetch.ensure_cover(sid))
    except Exception:
        pass
    try:
        lst = eps.episodes(sid)
        got["eps"] = len(lst) > 0
    except Exception:
        pass
    try:
        meta = m.bangumi_meta(sid)
        got["meta"] = bool(meta.get("name_cn") or meta.get("tags"))
    except Exception:
        pass

    with lock:
        stats["cover"] += int(got["cover"])
        stats["eps"] += int(got["eps"])
        stats["meta"] += int(got["meta"])
        if not all(got.values()):
            stats["fail"].append({
                "id": sid, "title": title,
                "missing": [k for k, v in got.items() if not v],
            })
    return sid, got


def main():
    open(LOG, "w").close()
    ids = season_ids()
    log("开始预热：%d 部（并发 %d）" % (len(ids), WORKERS))
    t0 = time.time()

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, sid, title) for sid, title in ids.items()]
        for fut in as_completed(futures):
            sid, got = fut.result()
            done += 1
            if done % 10 == 0 or done == len(ids):
                log("进度 %d/%d | 封面 %d 分集 %d 元信息 %d | 用时 %.0fs"
                    % (done, len(ids), stats["cover"], stats["eps"],
                       stats["meta"], time.time() - t0))

    log("完成：%d 部 | 封面 %d | 分集 %d | 元信息 %d | 失败 %d | 总用时 %.0fs"
        % (len(ids), stats["cover"], stats["eps"], stats["meta"],
           len(stats["fail"]), time.time() - t0))
    if stats["fail"]:
        with open(os.path.join(HERE, "precache_fail.json"), "w",
                  encoding="utf-8") as f:
            json.dump(stats["fail"], f, ensure_ascii=False, indent=1)
        log("失败清单已写入 precache_fail.json")


if __name__ == "__main__":
    main()
