#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态内容过滤：只保留番剧内容与番剧资讯

分三级判断，避免关键词误命中：
  强特征  —— 明确的集数/季数/影像/制作消息，直接保留
  弱特征  —— 新番/番剧/动画 这类泛词，需要配合内容形态或资讯词
  排除项  —— 广告、日常、账号运营公告；没有强特征时一律剔除
"""
import re

# 强特征：明确指向某一部番的更新或官方消息
STRONG_PATTERNS = [
    r"第\s*\d+\s*[集话話]", r"全\s*\d+\s*[集话話]",
    r"第\s*[一二三四五六七八九十百]+\s*[季期]",
    r"\d+(?:st|nd|rd|th)\s+Season",
    r"\bPV\b", r"预告", r"定档", r"开播", r"放送",
    r"制作决定", r"视觉图", r"声优", r"剧场版", r"OVA", r"OAD",
    r"字幕组", r"连载", r"完结", r"番外", r"总集篇", r"重制",
]

# 弱特征：只有泛称，必须配合其它证据
WEAK_PATTERNS = [r"新番", r"番剧", r"动画", r"动漫", r"番表"]

# 广告与拉流
AD_PATTERNS = [
    r"充电", r"[Bb]币", r"券", r"优惠", r"折扣", r"抽奖", r"团购",
    r"淘宝", r"天猫", r"京东", r"拼多多", r"下单", r"购买", r"链接",
    r"恰饭", r"广告", r"赞助", r"商单", r"福利", r"私信", r"加群",
    r"一键三连", r"点赞投币", r"关注我", r"求关注", r"谢谢支持",
]

# 日常闲聊
DAILY_PATTERNS = [
    r"日常", r"吐槽", r"今天", r"心情", r"吃饭", r"睡觉", r"感冒",
    r"生日", r"旅游", r"加班", r"摸鱼", r"闲聊", r"随便聊聊",
]

# 账号运营 / 平台处置公告（不属于番剧内容）
ACCOUNT_PATTERNS = [
    r"举报", r"被封", r"封号", r"申诉", r"账号", r"限流",
    r"收益", r"补偿", r"维权",
]


def _hit(patterns, text):
    for p in patterns:
        if re.search(p, text, re.I):
            return p
    return None


def classify(text, dtype="", title=""):
    """返回 (keep, reason)"""
    body = ("%s %s" % (title or "", text or "")).strip()
    if not body:
        return False, "空内容"

    strong = _hit(STRONG_PATTERNS, body)
    weak = _hit(WEAK_PATTERNS, body)
    ad = _hit(AD_PATTERNS, body)
    daily = _hit(DAILY_PATTERNS, body)
    account = _hit(ACCOUNT_PATTERNS, body)

    # 1) 强特征：确实指向某部番的更新或官方消息
    if strong:
        note = []
        if ad:
            note.append("含推广词")
        if account:
            note.append("含账号词")
        return True, "番剧内容(%s)%s" % (strong, ("；" + "、".join(note)) if note else "")

    # 2) 账号/平台公告：没有强特征就剔除
    if account:
        return False, "账号运营公告(%s)" % account

    # 3) 广告、日常：没有强特征就剔除
    if ad:
        return False, "广告(%s)" % ad
    if daily:
        return False, "日常(%s)" % daily

    # 4) 弱特征：投稿视频带集数/季数才算；文字动态需带资讯词
    if weak:
        if dtype == "DYNAMIC_TYPE_AV" and re.search(r"[集话話季]", body):
            return True, "投稿视频(%s)" % weak
        return False, "仅泛称无实据(%s)" % weak

    return False, "无番剧特征"
