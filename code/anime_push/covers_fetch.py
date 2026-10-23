#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面下载与缓存

按 Bangumi subject id 拉取封面, 存到 covers/<id>.jpg。
缓存永久有效; 下载失败不抛异常, 调用方自行降级为占位块。
"""
import os
import time
import urllib.request

import net

HERE = os.path.dirname(os.path.abspath(__file__))
COVER_DIR = os.path.join(HERE, "covers")

BGM_SUBJECT = "https://api.bgm.tv/v0/subjects/%s"
UA = net.UA


def _opener():
    """统一走 net.opener(), 代理配置集中在 net.py"""
    return net.opener()


def cover_path(bid):
    return os.path.join(COVER_DIR, "%s.jpg" % bid)


def fetch_cover_url(bid):
    """查 Bangumi v0 接口取封面地址"""
    req = urllib.request.Request(BGM_SUBJECT % bid, headers={"User-Agent": UA})
    import json
    with _opener().open(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    images = data.get("images") or {}
    return images.get("large") or images.get("common") or images.get("medium")


def ensure_cover(bid, retries=2):
    """确保本地有封面; 返回路径或 None"""
    if not bid:
        return None
    p = cover_path(bid)
    if os.path.exists(p) and os.path.getsize(p) > 1024:
        return p

    os.makedirs(COVER_DIR, exist_ok=True)
    for attempt in range(retries):
        try:
            url = fetch_cover_url(bid)
            if not url:
                return None
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with _opener().open(req, timeout=20) as resp:
                blob = resp.read()
            if len(blob) < 1024:
                return None
            tmp = p + ".part"
            with open(tmp, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, p)
            return p
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def ensure_covers(items, workers=4):
    """批量补齐封面, 返回命中数量"""
    from concurrent.futures import ThreadPoolExecutor
    ids = [i["bangumi"] for i in items if i.get("bangumi")]
    if not ids:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(ensure_cover, ids))
    return sum(1 for r in results if r)


if __name__ == "__main__":
    import sys, json
    items = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    print(ensure_covers(items))
