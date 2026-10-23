#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""番剧译名归一化：把不同译名收敛成同一个标准标题，供跨 UP 去重使用"""
import os
import json
import time
import re

import requests

from ai_filter import _api_key

API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-flash"
CACHE = "/opt/aio-dynamic-push/data/title_canon.json"
TTL = 30 * 24 * 3600

SYSTEM = """你是番剧译名归一化工具。给你一个番剧标题（可能来自不同字幕组或不同译法），
输出简体中文的通用译名，用于判断两条动态是否在说同一部作品。

规则：
1. 同一部作品的不同译名，必须输出完全相同的结果。
2. 去掉季数、集数、篇章名、宣传词，季数单独放在 season 字段。
3. 保留作品主标题，不要翻译人名、不要加书名号。
4. 无法确定时，输出你见到的最常见简体译名。

只输出 JSON：
{"title": "标准译名", "season": 2 或 null}"""


def _load():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except Exception:
        pass


def canonical_title(name):
    """返回 {"title":..., "season":...}；失败返回 None"""
    name = (name or "").strip()
    if not name:
        return None

    cache = _load()
    hit = cache.get(name)
    if hit and time.time() - hit.get("ts", 0) < TTL:
        return {"title": hit.get("title"), "season": hit.get("season")}

    key = _api_key()
    if not key:
        return None

    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": name},
                ],
                "temperature": 0,
                "max_tokens": 500,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        title = str(data.get("title") or "").strip()
        season = data.get("season")
        if isinstance(season, str) and season.isdigit():
            season = int(season)
        if not isinstance(season, int):
            season = None
        if not title:
            return None
        cache[name] = {"title": title, "season": season, "ts": time.time()}
        _save(cache)
        return {"title": title, "season": season}
    except Exception:
        return None


PAIR_CACHE = "/opt/aio-dynamic-push/data/title_pairs.json"
PAIR_SYSTEM = """判断两个标题是否指同一部番剧。

可能的情况：不同字幕组译名、简繁差异、副标题有无、标点差异。
注意：同一系列的不同季（第二季 vs 第三季）算不同作品。

只输出 JSON：{"same": true 或 false}"""


def _load_pairs():
    try:
        with open(PAIR_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_pairs(data):
    try:
        os.makedirs(os.path.dirname(PAIR_CACHE), exist_ok=True)
        tmp = PAIR_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, PAIR_CACHE)
    except Exception:
        pass


def ai_same_anime(a, b):
    """让 AI 判断两个标题是否同一部番；失败返回 None"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return None
    if a == b:
        return True
    key = "||".join(sorted([a, b]))
    cache = _load_pairs()
    hit = cache.get(key)
    if hit and time.time() - hit.get("ts", 0) < TTL:
        return bool(hit.get("same"))

    api = _api_key()
    if not api:
        return None
    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": "Bearer " + api,
                     "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": PAIR_SYSTEM},
                    {"role": "user", "content": "A：%s\nB：%s" % (a, b)},
                ],
                "temperature": 0,
                "max_tokens": 400,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        same = bool(data.get("same"))
        cache[key] = {"same": same, "ts": time.time()}
        _save_pairs(cache)
        return same
    except Exception:
        return None
