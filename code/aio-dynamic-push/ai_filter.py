#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 AI 判断一条 B站动态是否属于番剧内容/资讯

优先读环境变量 DEEPSEEK_API_KEY，其次读 OpenClaw 配置里的 key。
失败返回 None，由调用方回退到关键词规则。
"""
import os
import json
import re

import requests

OPENCLAW_CFG = "/root/.openclaw/openclaw.json"
API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-flash"
TIMEOUT = 25

SYSTEM = """你是B站番剧账号的内容审核员。用户只关心番剧本身，不想看其它内容。

判定为「保留」的，只有以下两类：
1. 具体番剧的更新：第X集、全X集、某季完结、某集上线。
2. 具体番剧的资讯：开播、定档、延期、停播、PV/预告、制作决定、视觉图、声优公布、剧场版/OVA、版权与下架等与作品相关的消息。

判定为「丢弃」的：
- 广告、恰饭、充电、优惠券、抽奖、引流、加群、求关注；
- 日常吐槽、个人生活、闲聊、感想；
- 账号运营公告：被举报、封号、申诉、限流、收益、维权；
- 与番剧无关的任何内容。

注意：出现「新番」「番剧」字样不代表相关，要看这条动态实际在说什么。

只输出 JSON，不要解释：
{"keep": true 或 false, "category": "番剧更新|番剧资讯|广告|日常|账号公告|其他", "reason": "不超过20字"}"""


def _api_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(OPENCLAW_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        return (cfg.get("models", {}).get("providers", {})
                .get("deepseek", {}).get("apiKey", "")).strip()
    except Exception:
        return ""


def ai_classify(text, dtype="", title="", up_name=""):
    """返回 (keep, reason, category)；调用失败返回 None"""
    key = _api_key()
    if not key:
        return None

    body = (text or "").strip()
    if not body:
        return False, "空内容", "其他"

    user = ("UP主：%s\n动态类型：%s\n标题：%s\n正文：\n%s"
            % (up_name or "未知", dtype or "未知", title or "无", body[:1200]))

    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": 400,
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        keep = bool(data.get("keep"))
        reason = str(data.get("reason") or "")[:40]
        category = str(data.get("category") or "其他")[:12]
        return keep, reason, category
    except Exception:
        # JSON 解析失败时尝试从文本里抠
        try:
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                data = json.loads(m.group(0))
                return bool(data.get("keep")), str(data.get("reason") or "")[:40], \
                    str(data.get("category") or "其他")[:12]
        except Exception:
            pass
        return None
