#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""今日番剧推送（Bangumi 数据源）

用法:
  python3 bgm_today.py                # 今天
  python3 bgm_today.py --day 3        # 指定星期几 (1=周一 ... 7=周日)
  python3 bgm_today.py --json         # 输出 JSON（给推送流水线用）
  python3 bgm_today.py --min-score 6  # 只要评分 >= 6 的
  python3 bgm_today.py --sort rating  # 按评分排序（默认按追番人数）

数据源: https://api.bgm.tv/calendar （需走代理, 见下方 PROXY）
"""
import json
import os
import sys
import datetime
import urllib.request

import net

API = "https://api.bgm.tv/calendar"
PROXY = net.proxy_url()
UA = net.UA


def build_opener():
    """统一走 net.opener(), 代理配置集中在 net.py"""
    return net.opener()


def fetch_calendar():
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with build_opener().open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(item):
    name_cn = (item.get("name_cn") or "").strip()
    name = (item.get("name") or "").strip()
    title = name_cn or name
    rating = item.get("rating") or {}
    score = rating.get("score") or 0
    doing = (item.get("collection") or {}).get("doing") or 0
    return {
        "id": item.get("id"),
        "title": title,
        "orig": name if name_cn and name != name_cn else "",
        "score": score,
        "rating_count": rating.get("total") or 0,
        "doing": doing,
        "url": "https://bgm.tv/subject/%s" % item.get("id"),
    }


def main():
    args = sys.argv[1:]

    def arg_val(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    as_json = "--json" in args
    min_score = float(arg_val("--min-score", 0))
    sort_key = arg_val("--sort", "doing")

    # Bangumi: 1=周一 ... 7=周日;  Python weekday(): 0=周一 ... 6=周日
    weekday = int(arg_val("--day", datetime.date.today().isoweekday()))

    try:
        data = fetch_calendar()
    except Exception as e:
        print("拉取 Bangumi 失败: %s" % e, file=sys.stderr)
        print("提示: 需要代理, 当前 BGM_PROXY=%s" % PROXY, file=sys.stderr)
        return 1

    day = next((d for d in data if d["weekday"]["id"] == weekday), None)
    if not day:
        print("没找到星期 %d 的数据" % weekday, file=sys.stderr)
        return 1

    items = [norm(i) for i in day.get("items", [])]
    if min_score > 0:
        items = [i for i in items if i["score"] >= min_score]
    keymap = {"rating": "score", "score": "score", "doing": "doing", "title": "title"}
    k = keymap.get(sort_key, "doing")
    items.sort(key=lambda x: (x[k], x["title"]), reverse=(k != "title"))

    if as_json:
        print(json.dumps({
            "weekday": day["weekday"]["cn"],
            "count": len(items),
            "items": items,
        }, ensure_ascii=False, indent=2))
        return 0

    print("%s 番剧表 · 共 %d 部" % (day["weekday"]["cn"], len(items)))
    for it in items:
        score = ("%.1f" % it["score"]) if it["score"] else "--"
        extra = "  [%s]" % it["orig"] if it["orig"] else ""
        print("  %-4s  追番%-5d  %s%s" % (score, it["doing"], it["title"], extra))
    return 0


if __name__ == "__main__":
    sys.exit(main())
