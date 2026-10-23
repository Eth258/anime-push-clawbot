#!/usr/bin/env bash
# 导出当前状态，用于迁移到另一台机器
# 用法： ./export.sh [输出文件名]
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/aio-dynamic-push}"
ANIME_DIR="${ANIME_DIR:-/root/anime_push}"
OUT="${1:-anime-push-state-$(date +%Y%m%d-%H%M).tar.gz}"
TMP="$(mktemp -d)"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

mkdir -p "$TMP/state/openclaw-weixin" "$TMP/state/data" "$TMP/state/anime_push"

echo "收集配置与状态…"

# 微信通道凭证（含 bot token / context token，等价于账号密码，务必妥善保管）
cp -a /root/.openclaw/openclaw.json              "$TMP/state/" 2>/dev/null || true
cp -a /root/.openclaw/openclaw-weixin/accounts   "$TMP/state/openclaw-weixin/" 2>/dev/null || true
cp -a /root/.openclaw/openclaw-weixin/accounts.json "$TMP/state/openclaw-weixin/" 2>/dev/null || true

# 监控配置与运行状态
cp -a "$APP_DIR/config.yml"  "$TMP/state/" 2>/dev/null || true
cp -a "$APP_DIR/data/."      "$TMP/state/data/" 2>/dev/null || true

# 放送表的人工确认结果与缓存
cp -a "$ANIME_DIR/title_overrides.json" "$TMP/state/anime_push/" 2>/dev/null || true
cp -a "$ANIME_DIR/meta_cache.json"      "$TMP/state/anime_push/" 2>/dev/null || true

# 定时器状态（可选）
cp -a /var/log/wx_session.log "$TMP/state/" 2>/dev/null || true

tar -czf "$OUT" -C "$TMP" state

echo
echo "已导出： $OUT  ($(du -h "$OUT" | cut -f1))"
echo
echo "⚠️  该文件包含微信登录凭证与 API Key，等同于账号密码："
echo "    - 不要提交到 git，不要发到群里"
echo "    - 迁移完成后及时删除"
echo
echo "在新机器上："
echo "   tar -xzf $OUT -C /"
echo "   # 把 state/openclaw.json 放回 /root/.openclaw/"
echo "   # 把 state/openclaw-weixin/* 放回 /root/.openclaw/openclaw-weixin/"
echo "   # 把 state/config.yml 放回 $APP_DIR/"
echo "   # 把 state/data/* 放回 $APP_DIR/data/"
echo "   systemctl restart openclaw-gateway aio-dynamic-push"
