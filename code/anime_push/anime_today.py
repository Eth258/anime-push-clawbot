#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""今日番剧更新推送 / 查询
用法:
  python3 anime_today.py            打印今天更新
  python3 anime_today.py --day +1   明天 (+N / -N / yyyy-mm-dd)
  python3 anime_today.py --json     输出 JSON（给推送流水线用）
数据源: B站番剧时间表 (api.bilibili.com/pgc/web/timeline)
  说明: Bangumi(api.bgm.tv) 在本机解析到解析到不可用的海外 IP 无法直连,
        如需 bangumi 源请配代理或换镜像。
"""
import json
import sys
import datetime
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
API = "https://api.bilibili.com/pgc/web/timeline?types=1&before=1&after=1"


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def target_date(arg):
    today = datetime.date.today()
    if not arg:
        return today
    if arg.startswith(("+", "-")):
        return today + datetime.timedelta(days=int(arg))
    return datetime.datetime.strptime(arg, "%Y-%m-%d").date()


def get_day(day):
    data = fetch(API)
    if data.get("code") != 0:
        raise RuntimeError("API error: %s" % data.get("message"))
    key = day.strftime("%m-%d")
    for d in data["result"]:
        if d["date"] == key:
            return d["episodes"]
    return []


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    day_arg = None
    if "--day" in args:
        i = args.index("--day")
        if i + 1 < len(args):
            day_arg = args[i + 1]
    day = target_date(day_arg)
    try:
        eps = get_day(day)
    except Exception as e:
        print("拉取失败: %s" % e, file=sys.stderr)
        return 1

    items = []
    for e in eps:
        items.append({
            "time": e.get("pub_time", ""),
            "title": e.get("title", ""),
            "ep": e.get("pub_index", ""),
            "delayed": bool(e.get("delay")),
            "delay_reason": e.get("delay_reason", ""),
            "url": "https://www.bilibili.com/bangumi/play/ep%s" % e.get("episode_id"),
        })
    items.sort(key=lambda x: (x["time"], x["title"]))

    if as_json:
        print(json.dumps({"date": day.isoformat(), "items": items},
                         ensure_ascii=False, indent=2))
        return 0

    weekday = "一二三四五六日"[day.weekday()]
    print("%s 周%s 番剧更新（%d 部）" % (day.isoformat(), weekday, len(items)))
    if not items:
        print("今天没有排播的番剧。")
        return 0
    for it in items:
        flag = " ⚠延期" if it["delayed"] else ""
        if it["delayed"] and it["delay_reason"]:
            flag += "(%s)" % it["delay_reason"]
        print("  %s  %s  %s%s" % (it["time"], it["title"], it["ep"], flag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
