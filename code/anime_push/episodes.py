#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集数三源投票

三个来源各自给出某部番在某天播第几集:
  1. bgm      — Bangumi v0/episodes 分集表, 按 airdate 精确匹配
  2. bgm-data — bangumi-data 的 broadcast 重复规则推算 (UTC 基准)
  3. anilist  — AniList nextAiringEpisode 直接给出集数与开播时间

判定: 至少两个来源一致才采信; 否则返回 None, 由调用方显示 "?"。
缓存: eps_cache/ (分集表 24h) + eps_vote/ (投票结果 12h)
"""
import os
import re
import json
import time
import html as html_module
from collections import Counter
import datetime
import urllib.request

import net

HERE = os.path.dirname(os.path.abspath(__file__))
EP_CACHE = os.path.join(HERE, "eps_cache")
VOTE_CACHE = os.path.join(HERE, "eps_vote")
EP_TTL = 24 * 3600
VOTE_TTL = 12 * 3600
UA = net.UA
BJ = datetime.timezone(datetime.timedelta(hours=8))


# ---------------- 源 1: Bangumi 分集表 ----------------

def _fetch_episodes(subject_id):
    url = ("https://api.bgm.tv/v0/episodes?subject_id=%s&type=0&limit=100"
           % subject_id)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with net.opener().open(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def episodes(subject_id, force=False):
    """返回 [{ep, airdate, name_cn}]"""
    if not subject_id:
        return []
    os.makedirs(EP_CACHE, exist_ok=True)
    path = os.path.join(EP_CACHE, "%s.json" % subject_id)
    if not force and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < EP_TTL:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    try:
        d = _fetch_episodes(subject_id)
        out = []
        for e in d.get("data", []):
            out.append({
                "ep": e.get("ep") or e.get("sort"),
                "airdate": e.get("airdate") or "",
                "name_cn": e.get("name_cn") or e.get("name") or "",
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        return out
    except Exception:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []


def from_bgm(subject_id, date_str, tolerance=1):
    """分集表精确匹配, 允许 ±tolerance 天跨日偏差"""
    if not subject_id:
        return None
    target = datetime.date.fromisoformat(date_str)
    for delta in range(0, tolerance + 1):
        for sign in ((0,) if delta == 0 else (1, -1)):
            probe = (target + datetime.timedelta(days=delta * sign)).isoformat()
            for e in episodes(subject_id):
                if e.get("airdate") == probe and e.get("ep"):
                    return int(e["ep"])
    return None


# ---------------- 源 2: bangumi-data 推算 ----------------

_BD_CACHE = {"items": None, "mtime": 0}


def _bd_items():
    path = os.path.join(HERE, "bd.json")
    if not os.path.exists(path):
        return []
    mtime = os.path.getmtime(path)
    if _BD_CACHE["items"] is not None and _BD_CACHE["mtime"] == mtime:
        return _BD_CACHE["items"]
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except Exception:
        items = []
    _BD_CACHE["items"] = items
    _BD_CACHE["mtime"] = mtime
    return items


def _bd_lookup(subject_id):
    """按 bangumi id 找 bangumi-data 条目, 返回 (entry, mal_id, mikan_id)"""
    for it in _bd_items():
        sites = {s.get("site"): s for s in it.get("sites", [])}
        bgm = sites.get("bangumi", {})
        if str(bgm.get("id") or "") == str(subject_id):
            return (it,
                    sites.get("mal", {}).get("id"),
                    sites.get("mikan", {}).get("id"))
    return None, None, None


def from_last_known(subject_id, date_str, tolerance=1, max_weeks=3):
    """以 Bangumi 已登记的最后几集为基准, 按周推算目标日期是第几集。

    Bangumi 分集表常滞后一两周（新集未录入），此时按每周一集外推,
    比纯 broadcast 算术可靠：它继承真实集号，跳播/停播不会被抹平。
    """
    if not subject_id:
        return None
    target = datetime.date.fromisoformat(date_str)
    limit = target + datetime.timedelta(days=tolerance)
    cands = []
    for e in episodes(subject_id):
        ep = e.get("ep")
        ad = e.get("airdate") or ""
        if not isinstance(ep, int) or not ad:
            continue
        try:
            d = datetime.date.fromisoformat(ad)
        except ValueError:
            continue
        if d <= limit:
            cands.append((d, ep))
    if not cands:
        return None
    last_date, last_ep = max(cands, key=lambda x: (x[0], x[1]))
    delta = (target - last_date).days
    weeks = round(delta / 7.0)
    if weeks < 0 or weeks > max_weeks:
        return None
    return int(last_ep) + weeks


def from_bangumi_data(subject_id, date_str):
    """用 broadcast 的 R/<起始>/P7D 推算集数 (UTC 基准)"""
    entry, _, _ = _bd_lookup(subject_id)
    if not entry:
        return None
    bc = entry.get("broadcast") or ""
    if not bc.startswith("R/") or "/P7D" not in bc:
        return None
    try:
        start_iso = bc.split("/")[1].replace("Z", "+00:00")
        start = datetime.datetime.fromisoformat(start_iso)
    except Exception:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    start_date = start.astimezone(datetime.timezone.utc).date()
    target = datetime.date.fromisoformat(date_str)
    diff = (target - start_date).days
    if diff < 0 or diff % 7 != 0:
        return None
    return diff // 7 + 1


# ---------------- 源 3: AniList ----------------

_ANILIST_Q = """
query($idMal:Int,$idBgm:Int){
  Media(idMal:$idMal,id:$idBgm,type:ANIME){
    id
    status
    episodes
    nextAiringEpisode{ episode airingAt }
  }
}
"""


def _anilist_post(variables):
    payload = json.dumps({"query": _ANILIST_Q, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://graphql.anilist.co", data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA})
    with net.opener().open(req, timeout=25) as r:
        return json.loads(r.read().decode())


MIKAN_DIR = os.path.join(HERE, "mikan_cache")
MIKAN_TTL = 6 * 3600
_EP_BRACKET = re.compile(r"\[(\d{1,4})\]")
_EP_DASH = re.compile(r"\s-\s(\d{1,4})(?:v\d)?(?:\s|\[|\()")


def _mikan_rss(mikan_id, force=False):
    """抓蜜柑 RSS（缓存 6 小时），返回 [(title, pubdate)]"""
    os.makedirs(MIKAN_DIR, exist_ok=True)
    path = os.path.join(MIKAN_DIR, "%s.xml" % mikan_id)
    if not force and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < MIKAN_TTL:
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    url = "https://mikanani.me/RSS/Bangumi?bangumiId=%s" % mikan_id
    body, _ = net.fetch(url, timeout=25,
                        headers={"User-Agent": "Mozilla/5.0"})
    text = body.decode("utf-8", "replace")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    return text


def _parse_rss(text):
    out = []
    for item in re.findall(r"<item>(.*?)</item>", text, re.S):
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        p = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if not t:
            continue
        title = html_module.unescape(t.group(1))
        pub = p.group(1)[:10] if p else ""
        out.append((title, pub))
    return out


def from_mikan(subject_id, date_str, back=1, forward=3, calib_days=2):
    """蜜柑发布记录（字幕组集号通常是跨季累计，需要按日期对齐换算）

    1. 用同日期的 Bangumi 分集与蜜柑集号求偏移（绝对集号 - 当季集号）
    2. 取出现最多的偏移作为校准值
    3. 目标日期附近的蜜柑集号减去偏移, 得到当季集号
    """
    _, _, mikan_id = _bd_lookup(subject_id)
    if not mikan_id:
        return None
    try:
        rss = _parse_rss(_mikan_rss(mikan_id))
    except Exception:
        return None

    mikan_pairs = []
    for title, pub in rss:
        if not pub:
            continue
        try:
            d = datetime.date.fromisoformat(pub)
        except ValueError:
            continue
        m = _EP_BRACKET.search(title) or _EP_DASH.search(title)
        if not m:
            continue
        ep = int(m.group(1))
        if 0 < ep < 10000:
            mikan_pairs.append((d, ep))
    if not mikan_pairs:
        return None

    bgm_pairs = []
    for e in episodes(subject_id):
        ep = e.get("ep")
        ad = e.get("airdate") or ""
        if not isinstance(ep, int) or not ad:
            continue
        try:
            bgm_pairs.append((datetime.date.fromisoformat(ad), ep))
        except ValueError:
            continue

    # 按日期对齐求偏移：取最近一次发布日，用该日最大集号对齐当季集号
    pairs = []
    for md, mep in mikan_pairs:
        best = None
        for bd, bep in bgm_pairs:
            diff = abs((md - bd).days)
            if diff <= calib_days:
                if best is None or diff < best[0] or (diff == best[0] and bep > best[1]):
                    best = (diff, bep)
        if best is not None and mep >= best[1]:
            pairs.append((md, mep, best[1]))
    if not pairs:
        return None

    latest_date = max(p[0] for p in pairs)
    same_day = [p for p in pairs if p[0] == latest_date]
    mep, bep = max(same_day, key=lambda x: x[1])[1], None
    # 该发布日对应的 Bangumi 集号取同批里最小的（即当前进度）
    bep = min(p[2] for p in same_day)
    offset = mep - bep

    target = datetime.date.fromisoformat(date_str)
    cands = []
    for md, mep in mikan_pairs:
        delta = (md - target).days
        # 发布一般晚于播出 0~3 天；早于播出超过 1 天的视为上一集
        if delta < -back or delta > forward:
            continue
        ep = mep - offset
        if ep > 0:
            cands.append(ep)
    return max(cands) if cands else None


def from_anilist(subject_id, date_str, mal_id=None):
    """用 nextAiringEpisode 推算目标日期那一集的编号"""
    v = {}
    if mal_id:
        v["idMal"] = int(mal_id)
    else:
        v["idBgm"] = None
    try:
        j = _anilist_post({"idMal": int(mal_id)} if mal_id else {})
        media = (j.get("data") or {}).get("Media")
        if not media:
            return None
        nxt = media.get("nextAiringEpisode")
        if not nxt:
            return None
        air_date = datetime.datetime.fromtimestamp(
            nxt["airingAt"], datetime.timezone.utc).astimezone(BJ).date()
        target = datetime.date.fromisoformat(date_str)
        weeks = (target - air_date).days / 7.0
        if abs(weeks - round(weeks)) > 0.15:
            return None
        return int(nxt["episode"] + round(weeks))
    except Exception:
        return None


# ---------------- 投票 ----------------

def vote(subject_id, date_str, use_cache=True):
    """三源投票

    返回 {"ep": int|None, "votes": {source: int|None}, "agree": n}
    ep 为 None 表示未能达成两票一致。
    """
    if not subject_id:
        return {"ep": None, "votes": {}, "agree": 0}

    os.makedirs(VOTE_CACHE, exist_ok=True)
    path = os.path.join(VOTE_CACHE, "%s_%s.json" % (subject_id, date_str))
    if use_cache and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < VOTE_TTL:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    _, mal_id, _ = _bd_lookup(subject_id)
    votes = {
        "bgm": from_bgm(subject_id, date_str),
        "bgm-last": from_last_known(subject_id, date_str),
        "mikan": from_mikan(subject_id, date_str),
        "bgm-data": from_bangumi_data(subject_id, date_str),
        "anilist": from_anilist(subject_id, date_str, mal_id),
    }

    counts = {}
    for val in votes.values():
        if val is not None:
            counts[val] = counts.get(val, 0) + 1
    best, agree = None, 0
    for val, cnt in counts.items():
        if cnt > agree:
            best, agree = val, cnt

    # ---- 优先级 ----
    # 1) Bangumi 精确命中（有明确 airdate 的那一集）
    # 2) 蜜柑发布记录：字幕组已放出 == 这一集确实存在, 能识破停播/延期
    # 3) 已登记集号外推：数据滞后时的兜底, 但无法感知延期
    # 4) 其余来源两票以上一致
    ep = None
    conflict = False

    if votes["bgm"] is not None:
        ep = votes["bgm"]
    elif votes["mikan"] is not None:
        ep = votes["mikan"]
        # 与其它来源不一致时留痕，便于事后核对
        others = [v for k, v in votes.items()
                  if k in ("bgm-data", "anilist") and v is not None]
        if others and ep not in others:
            conflict = True
    elif votes["bgm-last"] is not None:
        ep = votes["bgm-last"]
    else:
        indep = Counter(v for k, v in votes.items()
                        if k in ("mikan", "bgm-data", "anilist") and v is not None)
        majority, mcount = (indep.most_common(1)[0] if indep else (None, 0))
        ep = majority if mcount >= 2 else None

    result = {
        "ep": ep,
        "votes": votes,
        "agree": agree,
        "conflict": conflict,
    }

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass
    return result


def episode_on(subject_id, date_str):
    """对外入口: 返回集数 (int) 或 None"""
    return vote(subject_id, date_str).get("ep")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 episodes.py <subject_id> <YYYY-MM-DD>")
        sys.exit(1)
    r = vote(sys.argv[1], sys.argv[2], use_cache=False)
    print(json.dumps(r, ensure_ascii=False, indent=1))
