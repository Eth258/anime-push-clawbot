# anime-push-clawbot

把 B站 UP 主的番剧动态、以及每日番剧放送表，自动推送到个人微信。

基于 [aio-dynamic-push](https://github.com/kaixinol/aio-dynamic-push) + [OpenClaw](https://openclaw.ai) + 腾讯官方微信通道插件 `@tencent-weixin/openclaw-weixin`。

> 🧪  **vibe coding 项目**
> 个人自用优先，没做过系统性的工程评审与完整测试。

> **OpenClaw 版本固定 2026.9.5**
> 2C2G 实测：升到最新版（2026.10.x）后网关内存压不住，会 OOM、反复重启；停在 2026.9.5 时网关稳定在约 **550 MB**
> （1.7 GB 机器可用仅 700 MB 左右）。`install.sh` 已默认钉住该版本，详见「版本选择」一节。

---

## 一、它做什么

| 功能 | 说明 |
|---|---|
| **动态监控** | 轮询指定 UP 的 B站动态，识别番剧更新并推送卡片 |
| **内容过滤** | 三级规则 + AI 判定，剔除广告、日常、账号公告、非番剧内容（见下） |
| **完结过滤** | 已完结番剧的「第N集/全N集」视为补档，不推送 |
| **跨 UP 去重** | 同一部番 3 天内被不同 UP 推过，只发一次 |
| **卡片渲染** | 满幅封面 + 标题 + 二维码，1000×1240 PNG |
| **每日放送表** | 每天 09:00 生成当日新番表并推送，自动排除子供向/特摄/长寿番 |
| **多微信号** | 一个网关绑定多个微信，各自独立 agent 与会话 |
| **配额管理** | 按微信真实额度（每条用户消息后可发 10 条）排队、预警、积压提醒 |
| **保活提醒** | 24 小时不互动前，在合适时段提醒你回一句话 |

### 卡片示例

<img src="docs/card-demo.jpg" alt="番剧推送卡片示例" width="380">

卡片尺寸 1000×1240：封面满幅 + 品牌胶囊 + 番剧名 + 正文 + BV 号 / 分P + 二维码。

- 示例中的 **UP 名、BV 号、二维码** 均为占位：二维码只指向站点首页，不含任何真实 UP 或视频链接
- 封面为该番剧的公开宣传图，**版权归原权利人**，此处仅用于展示卡片效果；如涉权请联系删除
- 封面抓取失败时会退化为渐变色块占位，不影响其余排版

### 放送表示例

<img src="docs/schedule-demo.jpg" alt="每日放送表示例" width="420">

每天 09:00 推送的「今日放送」卡片（1080×2058）：

- 表格三列：**放送时间 / 番剧名 / 集数**（集数取三源投票结果，判不出一致时显示 `?`）
- 已按时间排序，午夜后的条目单独归入 `NEXT DAY` 区块，不会漏掉深夜档
- 子供向、特摄、开播超过 3 年的长寿番默认不列入
- 封面与番剧名来自 bangumi 公开数据，版权归原权利人，仅作效果展示

### 过滤规则明细

**动态推送**（`dynamic_filter.py` + `ai_filter.py` + `clawbot.py`）：

| 层级 | 判定 | 处理 |
|---|---|---|
| 强特征 | 集数（第N集/全N集）、季数、PV/预告、定档、开播、放送、制作决定、视觉图、声优、剧场版、OVA/OAD、字幕组、连载、完结、番外、总集篇、重制 | **保留** |
| 弱特征 | 新番、番剧、动画、动漫、番表等泛称 | 投稿视频须带集数/季数，文字动态须带资讯词，否则丢弃 |
| 广告 | 充电、B币、优惠券、折扣、抽奖、淘宝/天猫/京东/拼多多、下单、恰饭、商单、赞助、私信、加群、一键三连、求关注 | **丢弃** |
| 日常 | 日常、吐槽、今天、心情、吃饭、睡觉、生日、旅游、加班、摸鱼、闲聊 | **丢弃** |
| 账号公告 | 举报、被封、封号、申诉、限流、收益、补偿、维权 | **丢弃** |
| AI 复核 | DeepSeek 判断是否属于「番剧更新 / 番剧资讯」 | 其余类别丢弃 |
| 补档 | 番剧已完结（bangumi 起止日期）且内容是「第N集/全N集」 | **跳过** |
| 转发 | 转发他人动态（`skip_forward: true`） | 跳过 |
| 去重 | 同一部番 3 天内已被其它 UP 推过（含季数区分、AI 译名兜底） | 跳过 |

**放送表**（`anime_push/bgm_schedule.py`）：

| 规则 | 说明 |
|---|---|
| 子供向 / 特摄 | 内置中日双语关键词表（蜡笔小新、哆啦A梦、面包超人、光之美少女、假面骑士、奥特曼、宝可梦、数码宝贝、小丸子等约 40 项）+ Bangumi 标签「子供向/幼儿/少儿/亲子/早教」 |
| 长寿番 | 开播时间早于 3 年且仍在放送（如常驻长篇），默认排除 |
| 深夜档归属 | 北京时间 1 点前播出的归入前一天，避免漏项 |
| 译名补全 | 日文原名缺中文译名时，用 B站搜索交叉验证，需至少 2 条视频标题命中才采纳 |

> 说明：子供向/长寿番的排除目前只作用于**放送表**；动态推送侧依赖上游 UP 本身的内容，
> 若某个 UP 会发子供向内容，可在配置里关掉该 UP 或补充 `dynamic_filter.py` 的关键词。

---

## 二、架构

```
                    ┌──────────────────────────────┐
   B站动态 API ────▶ │  aio-dynamic-push (Python)   │
                    │  轮询 → 过滤 → 去重 → 渲染卡片 │
                    └──────────────┬───────────────┘
                                   │ CLI: openclaw message send
                                   ▼
                    ┌──────────────────────────────┐
                    │  OpenClaw Gateway (Node)     │  ← agent 对话、cron 任务
                    │  + openclaw-weixin 插件       │
                    └──────────────┬───────────────┘
                                   │ iLink 协议
                                   ▼
                            个人微信（可多个）
```

辅助定时器：

| 单元 | 周期 | 作用 |
|---|---|---|
| `wx-watchdog.timer` | 3 分钟 | 入站有消息但长时间无回复 → 判定分发卡死 → 重启网关 |
| `wx-session-probe.timer` | 30 分钟 | 只读探测微信会话健康，写 `/var/log/wx_session.log` |
| `wx-ping-reminder.timer` | 20 分钟 | 24 小时到期前，在 08:00–12:00 / 14:00–21:30 提醒回话 |

### 番剧信息源

番剧数据（放送表、译名、集数、封面、完结判定）来自以下几个公开数据源，不依赖 B站 的番剧库：

| 数据源 | 提供什么 | 具体字段 / 接口 |
|---|---|---|
| **bangumi-data**（主源） | 番剧清单、开播与完结日期、每周放送时刻、中文译名 | `unpkg.com/bangumi-data@0.3/dist/data.json`：`title`、`titleTranslate.zh-Hans`、`begin`、`end`、`broadcast`（ISO8601 重复规则 `R/起始/周期`）、`sites`、`type` |
| **Bangumi API** | 中文名、分类标签、封面、分集表 | `/v0/subjects/{id}` → `name_cn`、`tags`、`images`；`/v0/episodes?subject_id=…` → 每集 `airdate` |
| **AniList** | 下一集集数与播出时间 | `graphql.anilist.co` 的 `nextAiringEpisode` |
| **Mikan（蜜柑）** | 字幕组资源与更新 | `mikanani.me/RSS/Bangumi`，用于集数兜底与封面缓存 |
| **B站番剧时间线** | 备用当日番剧表 | `api.bilibili.com/pgc/web/timeline` |

各数据源的职责划分：

| 用途 | 取值顺序 |
|---|---|
| 今日放送（番名 + 时刻） | bangumi-data 的 `broadcast` 推算 → 换算北京时间 |
| 中文译名 | bangumi-data 的 `titleTranslate` → Bangumi `name_cn` → B站搜索交叉验证（≥2 条标题命中才采纳） |
| 集数（今天播第几集） | **三源投票**：Bangumi 分集表 / bangumi-data 推算 / AniList，**至少两源一致才采信**，否则显示 `?` |
| 完结判定 | bangumi-data 的 `end`（早于当前时间即视为完结） |
| 封面 | Bangumi `images.large` → Mikan 缓存 |

本地缓存：`bd.json`（12 小时）、`meta_cache.json`（30 天）、`eps_cache/`（24 小时）、`eps_vote/`（12 小时）、`covers/`。

> 需要能访问 `unpkg.com`（拉 bangumi-data）与 `api.bgm.tv`；受限网络请配置 `BGM_PROXY`。

---

## 三、目录结构

```
anime-push-clawbot/
├── install.sh              一键安装（幂等）
├── export.sh               导出状态，迁移用
├── config.example.yml      配置模板（已脱敏）
├── code/
│   ├── aio-dynamic-push/   监控主程序（含自建的 clawbot/card/qr 通道）
│   └── anime_push/         放送表子系统
├── scripts/                看门狗 / 会话探测 / 保活提醒
├── systemd/                5 个单元文件
└── README.md
```

---

## 四、快速开始

### 1. 安装

```bash
chmod +x install.sh export.sh
./install.sh
```

脚本会完成：系统依赖 → Node 24 → OpenClaw → 微信插件 → 主程序 → Python 依赖 → 放送表子系统 → systemd 单元。

### 2. 填配置

```bash
vim /opt/aio-dynamic-push/config.yml
```

必填三项：

```yaml
# ① B站 cookie（浏览器登录 bilibili.com 后，F12 → Application → Cookies 复制）
cookie: "SESSDATA=<你的>; bili_jct=<你的>; buvid3=<你的>; buvid4=<你的>; DedeUserID=<你的>"

# ② DeepSeek Key（用于判断动态是否广告）
deepseek_key: sk-xxxxxxxx

# ③ 微信 userId（扫码后才知道，见下一步）
targets:
  - o9cqXXXXXXXX@im.wechat
```

### 3. 扫码绑定微信

```bash
openclaw channels login --channel openclaw-weixin
```

用手机微信扫描终端里的二维码。成功后查看 userId：

```bash
cat /root/.openclaw/openclaw-weixin/accounts/*-im-bot.json
# {"token":"...","userId":"o9cqXXXXXXXX@im.wechat",...}
```

把 `userId` 回填到配置的 `targets`，然后：

```bash
systemctl restart aio-dynamic-push
```

需要**第二个微信**时，重复第 3 步，并把两个 userId 都写进 `targets`。
建议同时执行（隔离会话）：

```bash
openclaw config set session.dmScope per-account-channel-peer
```

### 版本选择（重要）

**本仓库锁定 OpenClaw `2026.9.5`，不要盲目升级到 latest。**

| 项目 | 值 |
|---|---|
| 已验证可用版本 | `2026.9.5`（commit `ec9c1a1`） |
| 当时 npm latest | `2026.10.6`（内存占用更高） |
| 网关实测内存 | 约 **554 MB**（1.7 GB 内存的机器，可用仅 724 MB） |

2 核 2 GB 的机器上，网关本身就吃掉三分之一内存，再叠加监控程序与系统开销余量很小。
升级到新版本后常因内存不足导致 OOM、频繁 GC、响应变慢，甚至网关反复重启。

安装脚本默认已经钉住版本：

```bash
OPENCLAW_VER="${OPENCLAW_VER:-2026.9.5}"
```

如果确实要升级，请先在测试机验证内存，再用显式变量安装：

```bash
OPENCLAW_VER=2026.9.33 ./install.sh     # extended-stable 分支
```

升级后观察 24 小时：

```bash
free -m
ps -o rss= -p $(systemctl show openclaw-gateway -p MainPID --value) | awk '{printf "%.0f MB\n", $1/1024}'
dmesg -T | grep -i "killed process"      # 有输出说明被 OOM 杀过
```

### 4. 导入放送表定时任务（可选）

放送表由 OpenClaw 的 cron 驱动。安装后手动建一次：

```bash
openclaw cron add \
  --name "番剧放送表推送" \
  --cron "0 9 * * *" --tz Asia/Shanghai \
  --agent main \
  --message "每日番剧推送。工作目录 /root/anime_push。

1) 运行 python3 bgm_schedule.py --json 取当天放送列表。
2) 运行 python3 make_card.py -o /tmp/anime_today.png 生成卡片。
3) 用 message 工具发送到每个 target（见 config.yml 的 targets）。"
```

> `bgm_schedule.py` 依赖 `bd.json`（bangumi-data 全量清单，约 8 MB）。
> 若机器无法直连 `unpkg.com`，需要代理，见 `code/anime_push/net.py` 的 `BGM_PROXY` 环境变量。

---

## 五、配置项说明

| 字段 | 作用 | 默认 |
|---|---|---|
| `uid_list` | 要监控的 UP 主 UID 列表 | — |
| `intervals_second` | 轮询间隔（秒） | 600 |
| `skip_forward` | 是否跳过转发动态 | true |
| `cookie` | B站 cookie，缺失会 412 | — |
| `render_card` | 是否渲染卡片图 | true |
| `send_link` | 是否额外发一条链接文本 | true |
| `card_style` | 卡片样式：`bleed` / `inset` | bleed |
| `push_image_only` | 纯图片动态是否推送 | true |
| `fail_open` | AI 判断失败时是否放行 | true |
| `targets` | 微信 userId 列表（多账号） | — |
| `quota_max` | 每条用户消息后可发条数 | 10 |
| `quota_window_hours` | 额度窗口（小时） | 24 |

**每推送一条番剧消耗 2 条额度**（卡片 1 + 链接文本 1）。剩余不足 2 条时整条排队，不发半条。

---

## 六、日常运维

```bash
# 服务状态
systemctl status aio-dynamic-push
openclaw channels status

# 实时日志
journalctl -u aio-dynamic-push -f

# 待发队列
cat /opt/aio-dynamic-push/data/outbox.json | python3 -m json.tool

# 微信会话健康（每 30 分钟一行）
tail -5 /var/log/wx_session.log

# 看门狗动作记录
tail -5 /var/log/wx_watchdog.log
```

### 卡片样式调试

```bash
cd /opt/aio-dynamic-push && ./.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from push_channel.card import render_card
render_card('番剧名', '正文', 'UP名', 'https://www.bilibili.com',
            '/tmp/preview.png', style='bleed')
print('已生成 /tmp/preview.png')
"
```

---

## 七、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志 `sendMessage ret=-2 prepare failed` | 额度用完 / 会话失效 | 在微信里给 bot 发一句话 |
| 日志 `errcode -14 session timeout` | bot 令牌失效 | 重新扫码登录 |
| 表里 `412` | B站 cookie 过期 | 重新复制 cookie |
| `激活buvid3 失败 code 1302` | 无 cookie 时的风控 | 有 cookie 时可忽略 |
| 消息进了队列但没发 | 额度不足 | 看 `outbox.json` 与配额提示 |
| 扫码后收不到回复 | 微信里是新的对话窗口 | 找新窗口，别用旧的 |

### 配额口径

额度按「你最后一条消息之后，bot 已发出的所有消息」计算，包含：卡片、链接文本、agent 聊天回复、放送表卡片。数据来自网关日志，24 小时不互动则额度归零。

---

## 八、迁移

```bash
# 旧机器
./export.sh                 # 生成 anime-push-state-*.tar.gz

# 新机器
./install.sh
tar -xzf anime-push-state-*.tar.gz -C /
# 按 export.sh 末尾的提示把文件放回对应位置
systemctl restart openclaw-gateway aio-dynamic-push
```

⚠️ 导出包含微信登录凭证与 API Key，等同于账号密码，传输后及时删除。

---

## 九、已知限制

| 限制 | 说明 |
|---|---|
| 只能发图片和文本 | iLink 支持文本/图片/语音/文件/视频，但没有卡片消息，所以一条推送是「图片 + 文本」两条 |
| 额度按轮计算 | 每条 bot 消息占 1 条额度（卡片、文本各算 1 条）；每轮 10 条，发完必须等你再发一条消息才能继续 |
| 24 小时需互动 | 否则 context_token 失效，需重新扫码登录 |
| B站 cookie 会过期 | 过期后接口返回 412，需重新填写 |
| 放送表依赖外网数据源 | 需能访问 `unpkg.com` 拉取 bangumi-data；受限网络要配置 `BGM_PROXY` |
| 内存占用偏高 | 网关常驻约 600 MB，1 GB 内存的机器会比较紧 |

---

## 十、环境变量（可选，用于非默认路径）

代码里的路径都可用环境变量覆盖，写在 systemd 单元的 `Environment=` 里即可：

| 变量 | 默认值 | 作用 |
|---|---|---|
| `OPENCLAW_NODE` | 自动探测 | node 可执行文件 |
| `OPENCLAW_ENTRY` | 自动探测 | `openclaw.mjs` 路径 |
| `AIO_DATA_DIR` | `/opt/aio-dynamic-push/data` | 队列与去重状态 |
| `WX_STATE_DIR` | `/root/.openclaw/openclaw-weixin` | 微信凭证目录 |
| `WX_MSG_DB` | `<WX_STATE_DIR>/ref-messages.sqlite` | 消息库（配额统计） |
| `BGM_DATA` | `/root/anime_push/bd.json` | bangumi 全量清单 |
| `BGM_PROXY` | `socks5h://127.0.0.1:10808` | 放送表拉取数据用的代理 |

> 后两项由放送表子系统使用。若机器能直连 `unpkg.com`，把 `BGM_PROXY` 设为空字符串。

---

## 十一、致谢与许可

- 监控框架：[aio-dynamic-push](https://github.com/kaixinol/aio-dynamic-push)（MIT）
- 网关：[OpenClaw](https://openclaw.ai)
- 微信通道：`@tencent-weixin/openclaw-weixin`（Tencent，MIT）
- 番剧数据：[bangumi-data](https://github.com/bangumi-data/bangumi-data)（CC BY 4.0）

本项目整体以 MIT 协议开源，详见 [LICENSE](./LICENSE)。

---

## 十二、免责声明

- 仅用于**个人自动化**：把你自己订阅的 UP 动态转发到你自己绑定的微信。
- 微信通道使用腾讯官方 iLink 协议，请遵守微信平台规则，不要用于群发、营销或骚扰；
  发送频率与内容由使用者自行控制。
- B站 cookie、DeepSeek Key 等凭据请只保存在本机，切勿提交到公开仓库。
- 因使用不当导致的账号限制、封禁等后果由使用者自行承担。
