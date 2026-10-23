#!/usr/bin/env bash
# 番剧推送全家桶 · 一键安装
# 适用：Ubuntu 22.04 / Debian 12，root 运行
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/aio-dynamic-push}"
ANIME_DIR="${ANIME_DIR:-/root/anime_push}"
NODE_VER="${NODE_VER:-24}"
OPENCLAW_VER="${OPENCLAW_VER:-2026.9.5}"
WEIXIN_PLUGIN="${WEIXIN_PLUGIN:-@tencent-weixin/openclaw-weixin}"
BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

c()   { printf "\033[36m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
die() { printf "\033[31m错误:\033[0m %s\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行"

# ---------- 1. 系统依赖 ----------
c "1/9 安装系统依赖（python3 / 中文字体 / curl）"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip fonts-noto-cjk curl ca-certificates

# ---------- 2. Node.js ----------
c "2/9 检查 Node.js（需要 >= 22）"
need_node=1
if command -v node >/dev/null 2>&1; then
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  [ "$major" -ge 22 ] && need_node=0
fi
if [ "$need_node" -eq 1 ]; then
  if [ ! -s "$HOME/.nvm/nvm.sh" ]; then
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  fi
  # shellcheck disable=SC1090
  . "$HOME/.nvm/nvm.sh"
  nvm install "$NODE_VER"
  nvm alias default "$NODE_VER" >/dev/null
  # shellcheck disable=SC1090
  . "$HOME/.nvm/nvm.sh"
fi
node -v || die "Node 安装失败"

# ---------- 3. OpenClaw ----------
# 注意：默认钉在 2026.9.5。2C2G 的机器升到 latest 后内存吃紧，容易 OOM / 反复重启。
# 要换版本请显式指定：OPENCLAW_VER=2026.9.33 ./install.sh
c "3/9 安装 OpenClaw ${OPENCLAW_VER}"
if [ "$OPENCLAW_VER" != "2026.9.5" ]; then
  printf "\033[33m提示:\033[0m 非默认版本 %s，1~2 GB 内存的机器请先确认内存余量（网关约占 550 MB）\n" "$OPENCLAW_VER"
fi
npm install -g "openclaw@${OPENCLAW_VER}"

# ---------- 4. 微信通道插件 ----------
c "4/9 安装微信通道插件"
openclaw plugins install "$WEIXIN_PLUGIN" || c "  插件可能已安装，继续"
openclaw config set plugins.entries.openclaw-weixin.enabled true || true

# ---------- 5. 主程序 ----------
c "5/9 部署监控程序到 ${APP_DIR}"
mkdir -p "$APP_DIR/data"
cp -a "$BUNDLE/code/aio-dynamic-push/." "$APP_DIR/"

# ---------- 6. Python 依赖 ----------
c "6/9 创建虚拟环境并安装依赖"
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
[ -f "$APP_DIR/requirements.txt" ] && "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
"$APP_DIR/.venv/bin/pip" install -q pillow qrcode requests

# ---------- 7. 放送表子系统 ----------
c "7/9 部署放送表子系统到 ${ANIME_DIR}"
mkdir -p "$ANIME_DIR/covers" "$ANIME_DIR/eps_cache" "$ANIME_DIR/mikan_cache"
cp -a "$BUNDLE/code/anime_push/." "$ANIME_DIR/"

# ---------- 8. systemd ----------
c "8/9 安装运维脚本"
cp -a "$BUNDLE/scripts/wx_watchdog.js"      /root/
cp -a "$BUNDLE/scripts/wx_session_probe.py" /root/
cp -a "$BUNDLE/scripts/wx_ping_reminder.py" /root/
chmod 700 /root/wx_watchdog.js /root/wx_session_probe.py /root/wx_ping_reminder.py

c "9/9 安装 systemd 单元"
cp -a "$BUNDLE/systemd/"*.service "$BUNDLE/systemd/"*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now aio-dynamic-push.service >/dev/null 2>&1 || true
systemctl enable --now wx-watchdog.timer wx-session-probe.timer wx-ping-reminder.timer >/dev/null 2>&1 || true

if [ ! -f "$APP_DIR/config.yml" ]; then
  cp "$BUNDLE/config.example.yml" "$APP_DIR/config.yml"
  chmod 600 "$APP_DIR/config.yml"
  c "已生成 $APP_DIR/config.yml（需要填 key 与 cookie）"
fi

cat <<EOF

============================================================
安装完成。还剩 4 个手动步骤：

1) 填配置
   vim $APP_DIR/config.yml
     - cookie         B站 SESSDATA 等（浏览器登录后复制）
     - deepseek_key   DeepSeek API Key
     - targets        微信 userId（下一步扫码后填）

2) 绑定微信（手机扫码）
   openclaw channels login --channel openclaw-weixin

3) 回填微信 userId
   扫码成功后查看：
     cat /root/.openclaw/openclaw-weixin/accounts/*-im-bot.json
   把里面的 userId 填进 config.yml 的 targets 列表，然后：
     systemctl restart aio-dynamic-push

4) （可选）导入放送表定时任务
   见 README.md「放送表任务」一节

常用命令：
   systemctl status aio-dynamic-push
   journalctl -u aio-dynamic-push -f
============================================================
EOF
