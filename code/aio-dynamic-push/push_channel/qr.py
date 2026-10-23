"""B站链接构造：分P视频自动定位到最新一集"""
import requests

CK_FILE = "/root/.bili_cookie"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0"
_cache = {}


def _cookie():
    try:
        with open(CK_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def view_info(bvid):
    """查视频信息（分P数、所属合集），带缓存"""
    if not bvid:
        return {}
    if bvid in _cache:
        return _cache[bvid]
    data = {}
    try:
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/",
                     "Cookie": _cookie()},
            timeout=15,
        )
        data = (r.json() or {}).get("data") or {}
    except Exception:
        data = {}
    if len(_cache) > 500:
        _cache.clear()
    if data:                      # 查询失败不缓存，下次重试
        _cache[bvid] = data
    return data


def _archive(raw):
    major = ((raw.get("modules") or {}).get("module_dynamic") or {}).get("major") or {}
    return major.get("archive") or {}


def qr_content_for(raw, url):
    """兜底：没有 bvid 时用原链接"""
    a = _archive(raw)
    bvid = a.get("bvid")
    if bvid:
        link = "https://www.bilibili.com/video/" + bvid
        n = view_info(bvid).get("videos") or 0
        if n > 1:
            link += "?p=%d" % n
        return link
    if a.get("aid"):
        return "https://www.bilibili.com/video/av%s" % a["aid"]
    return url


def code_text_for(raw):
    """卡片上显示的文字：BV 号 + 分P信息"""
    a = _archive(raw)
    bvid = a.get("bvid") or ""
    if not bvid:
        return ""
    n = view_info(bvid).get("videos") or 0
    if n > 1:
        return "%s  P%d" % (bvid, n)
    return bvid
