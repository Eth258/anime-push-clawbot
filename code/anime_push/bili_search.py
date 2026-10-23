#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B站综合搜索：给番剧找中文译名候选

用法:
  python3 bili_search.py "ごーすと・みーつ・ぎゃる！"
  python3 bili_search.py --json "ごーすと・みーつ・ぎゃる！"

做法:
  1. 用 all/v2 综合搜索（media_bangumi 只收正版, 常为空）
  2. 取视频标题, 清理 【】『』 等修饰符
  3. 拆出含中文的片段, 统计出现次数
  4. 返回按票数排序的候选, 并标注是否有日文原名同时出现
"""
import sys
import json
import re
import html
import uuid
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
API = "https://api.bilibili.com/x/web-interface/search/all/v2?keyword=%s"

CJK = re.compile(r"[\u4e00-\u9fff]")
BRACKETS = re.compile(r"[【】『』\[\]（）()《》<>]")
NOISE = [
    "全12话", "全13话", "全11话", "全24话", "未删减版", "未删减", "超清中字",
    "超清", "4K", "1080P", "简中", "中字", "周更", "合集", "完结", "第1话",
    "更新", "熟肉", "生肉", "字幕组",
]


def _clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return s.strip()


def search_videos(keyword, limit=40):
    url = API % urllib.parse.quote(keyword)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Cookie": "buvid3=%s" % uuid.uuid4(),
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("code") != 0:
        return []
    out = []
    for block in (data.get("data") or {}).get("result") or []:
        if block.get("result_type") != "video":
            continue
        for it in block.get("data") or []:
            t = _clean(it.get("title"))
            if t:
                out.append(t)
            if len(out) >= limit:
                return out
    return out


def _segments(title):
    """把标题拆成候选片段"""
    s = BRACKETS.sub("|", title)
    parts = re.split(r"[|｜/／:：\-—~～,，。!！?？]+", s)
    out = []
    for p in parts:
        p = p.strip()
        for n in NOISE:
            p = p.replace(n, "")
        p = p.strip()
        if not p or not CJK.search(p):
            continue
        if len(p) < 2 or len(p) > 30:
            continue
        out.append(p)
    return out


def candidates(keyword, limit=40):
    titles = search_videos(keyword, limit)
    counts = {}
    for t in titles:
        for seg in _segments(t):
            counts[seg] = counts.get(seg, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return {
        "keyword": keyword,
        "titles_found": len(titles),
        "samples": titles[:6],
        "candidates": [{"name": k, "count": v} for k, v in ranked[:10]],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: python3 bili_search.py <关键词>", file=sys.stderr)
        return 1
    result = candidates(args[0])
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print("搜索: %s | 命中视频 %d 条" % (result["keyword"], result["titles_found"]))
        for c in result["candidates"]:
            print("  %2d 次  %s" % (c["count"], c["name"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
