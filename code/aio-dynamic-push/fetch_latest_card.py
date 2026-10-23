#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取指定 UP 主最新一条动态，渲染成卡片（不推送，只落盘）"""
import os
import sys
import json
import time

import requests
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from push_channel.card import render_card
from dynamic_filter import classify

CONFIG = os.path.join(HERE, "config.yml")
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dynamic_card.png"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def load_task(uid=None):
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for t in cfg.get("query_task", []):
        if t.get("type") != "bilibili":
            continue
        if uid is None or str(uid) in [str(u) for u in t.get("uid_list", [])]:
            return t
    return None


def fetch_feed(uid, cookie):
    url = ("https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
           "?host_mid=%s&offset=&my_ts=%d&features=itemOpusStyle"
           % (uid, int(time.time())))
    headers = {
        "User-Agent": UA,
        "Referer": "https://space.bilibili.com/%s/dynamic" % uid,
        "Cookie": cookie or "",
    }
    r = requests.get(url, headers=headers, timeout=25)
    return r.json()


def parse_item(item):
    """从动态条目里抽出卡片需要的字段"""
    dtype = item.get("type")
    author = item["modules"]["module_author"]
    uname = author.get("name", "")
    avatar = author.get("face") or ""
    ts = int(author.get("pub_ts") or time.time())
    md = item.get("modules", {}).get("module_dynamic") or {}

    title_msg, content, pic = "发动态了", "", None

    if dtype == "DYNAMIC_TYPE_DRAW":
        major = md.get("major") or {}
        if major.get("type") == "MAJOR_TYPE_OPUS":
            opus = major.get("opus") or {}
            content = ((opus.get("summary") or {}).get("text") or "").strip()
            if opus.get("title"):
                content = "「%s」%s" % (opus["title"], content)
            pics = opus.get("pics") or []
            if pics:
                pic = pics[0].get("url")
        else:
            content = ((md.get("desc") or {}).get("text") or "").strip()
            items = (major.get("draw") or {}).get("items") or []
            if items:
                pic = items[0].get("src")
    elif dtype == "DYNAMIC_TYPE_WORD":
        content = ((md.get("desc") or {}).get("text") or "").strip()
    elif dtype == "DYNAMIC_TYPE_AV":
        arc = (md.get("major") or {}).get("archive") or {}
        content = arc.get("title") or ""
        pic = arc.get("cover")
        title_msg = "投稿了"
    elif dtype == "DYNAMIC_TYPE_ARTICLE":
        opus = (md.get("major") or {}).get("opus") or {}
        content = opus.get("title") or ""
        pics = opus.get("pics") or []
        if pics:
            pic = pics[0].get("url")
        title_msg = "发了专栏"
    elif dtype == "DYNAMIC_TYPE_FORWARD":
        content = ((md.get("desc") or {}).get("text") or "").strip()
        title_msg = "转发了动态"

    return {
        "type": dtype,
        "uname": uname,
        "avatar": avatar,
        "ts": ts,
        "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)),
        "title": title_msg,
        "content": content,
        "pic": pic,
        "id": item.get("id_str"),
    }


def main():
    uid = sys.argv[1] if len(sys.argv) > 1 else None
    task = load_task(uid)
    if not task:
        print("没有找到对应的 B站任务配置")
        return 1
    uid = str(uid or task["uid_list"][0])
    cookie = task.get("cookie", "")

    data = fetch_feed(uid, cookie)
    if data.get("code") != 0:
        print("接口返回错误: code=%s msg=%s" % (data.get("code"), data.get("message")))
        return 1

    items = data["data"].get("items") or []
    items = [it for it in items
             if ((it.get("modules") or {}).get("module_tag") or {}).get("text") != "置顶"]
    if not items:
        print("没有可用的动态")
        return 1

    # 按发布时间倒序（接口首条可能是置顶旧动态）
    items.sort(key=lambda it: int(((it.get("modules") or {})
                                   .get("module_author") or {}).get("pub_ts") or 0),
               reverse=True)

    if "--list" in sys.argv:
        for it in items[:15]:
            info = parse_item(it)
            keep, why = classify(info["content"], info["type"], info["title"])
            print("%s  %-18s  %s  | %s" % (
                "PASS" if keep else "SKIP", info["type"], info["time"], why))
            print("      ", info["content"][:70].replace("\n", " "))
        return 0

    info = None
    for it in items:
        cand = parse_item(it)
        keep, why = classify(cand["content"], cand["type"], cand["title"])
        if keep:
            info = cand
            print("选中:", why)
            break
        print("跳过:", why, "|", cand["content"][:50].replace("\n", " "))
    if info is None:
        print("近期没有番剧相关动态")
        return 1
    url = "https://t.bilibili.com/%s" % info["id"]

    print(json.dumps(info, ensure_ascii=False, indent=1))
    render_card(info["title"], info["content"], info["uname"], url, OUT,
                cover_url=info["pic"], avatar_url=info["avatar"],
                accent=(255, 92, 141), qr_content=url, style="bleed")
    print("saved:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
