#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络访问统一入口

本机访问境外站点(unpkg.com / api.bgm.tv / lain.bgm.tv 等)必须走 socks 代理,
直连会超时。所有模块统一从这里取 opener, 不要各自拼 ProxyHandler。

代理地址可用环境变量 BGM_PROXY 覆盖, 设为空字符串表示强制直连。
"""
import os
import urllib.request

UA = "openclaw-anime-push/1.0 (https://github.com/openclaw)"
DEFAULT_PROXY = "socks5h://127.0.0.1:10808"


def proxy_url():
    """当前生效的代理地址; 空字符串表示直连"""
    return os.environ.get("BGM_PROXY", DEFAULT_PROXY)


def opener():
    """返回走代理的 urllib opener"""
    proxy = proxy_url()
    if not proxy:
        return urllib.request.build_opener()
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    return urllib.request.build_opener(handler)


def fetch(url, timeout=30, headers=None):
    """GET 二进制内容, 返回 (body, content_type)"""
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with opener().open(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")
