#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户回复后重置某个微信 target 的推送配额（10 条 / 会话窗口）"""
import argparse
import json
import os
import time

import yaml

DATA = "/opt/aio-dynamic-push/data"
QUOTAS = os.path.join(DATA, "quotas.json")
LEGACY = os.path.join(DATA, "quota.json")
CONFIG = "/opt/aio-dynamic-push/config.yml"


def primary_target():
    try:
        cfg = yaml.safe_load(open(CONFIG, encoding="utf-8"))
        for ch in cfg.get("push_channel", []):
            if ch.get("type") == "clawbot" and ch.get("enable"):
                return str(ch.get("target") or "")
    except Exception:
        pass
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="")
    args = ap.parse_args()

    target = args.target.strip() or primary_target()
    if not target:
        print("no target")
        return 1

    os.makedirs(DATA, exist_ok=True)
    try:
        with open(QUOTAS, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    state = {"window_start": time.time(), "used": 0, "max": 10,
             "reset_reason": "user_reply"}
    data[target] = state

    tmp = QUOTAS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, QUOTAS)

    # 兼容旧脚本读取的单文件
    with open(LEGACY + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(LEGACY + ".tmp", LEGACY)

    print("quota reset for", target, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
