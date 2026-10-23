# anime-push-clawbot

基于 [aio-dynamic-push](https://github.com/kaixinol/aio-dynamic-push) 的二开项目。

> 🧪 **vibe coding 项目**：对话驱动、AI 辅助写成，个人自用优先，未做系统性工程评审与完整测试。

> **OpenClaw 版本固定 2026.9.5，别升级。**
> 2C2G 实测：升到最新版（2026.10.x）后网关内存压不住，会 OOM、反复重启；停在 2026.9.5 时网关稳定在约 550 MB。
> `install.sh` 已默认钉住该版本。

---

## 一、实现了什么功能

### 1. 番剧放送表

每天 09:00 抓取当日新番放送列表（数据源 bangumi-data），渲染成一张放送表卡片推送到微信。
日文原名缺中文译名时，会用 B站搜索交叉验证（同一候选至少命中 2 条视频标题才采纳），证据不足保留原名。

<img src="docs/schedule-demo.jpg" alt="放送表示例" width="380">

<sub>表格三列：放送时间 / 番剧名 / 集数（三源投票）；午夜后条目归入 NEXT DAY；子供向、特摄、长寿番默认不列。</sub>

### 2. B站搬运 UP 动态订阅

轮询指定 UP 的动态，识别番剧更新后推送图文卡片：

```
轮询 → 集数规则直通 → AI 判断是否广告 → 完结番过滤 → 跨 UP 去重 → 渲染卡片 → 推送
```

推送内容为一张 1000×1240 的卡片（封面、标题、正文、BV 号、二维码）+ 一条带链接的文本。

<img src="docs/card-demo.jpg" alt="卡片示例" width="340">

<sub>UP 名、BV 号、二维码均为占位（二维码只指向站点首页）；封面为该番剧公开宣传图，版权归原权利人，仅作效果展示。</sub>

### 3. 内容过滤

**动态推送**：

| 环节 | 规则 |
|---|---|
| 强特征放行 | 集数、季数、PV/预告、定档、开播、放送、制作决定、视觉图、声优、剧场版、OVA、字幕组、连载、完结、番外、总集篇、重制 |
| 弱特征约束 | 只有「新番/番剧/动画」等泛称时，投稿视频需带集数季数、文字动态需带资讯词，否则丢弃 |
| 广告剔除 | 充电、B币、优惠券、折扣、抽奖、电商平台、下单、恰饭、商单、赞助、私信、加群、一键三连、求关注 |
| 日常剔除 | 日常、吐槽、心情、吃饭、生日、旅游、加班、摸鱼、闲聊 |
| 账号公告剔除 | 举报、封号、申诉、限流、收益、补偿、维权 |
| AI 复核 | DeepSeek 判断是否为「番剧更新 / 番剧资讯」，其余类别丢弃 |
| 补档过滤 | 已完结番剧的“第N集/全N集”不推送（按 bangumi 起止日期判定） |
| 转发跳过 | `skip_forward: true` 时不推转发类动态 |
| 跨 UP 去重 | 同一部番 3 天内被不同 UP 推过只发一次，带季数隔离与 AI 译名兜底 |

**放送表**：

| 环节 | 规则 |
|---|---|
| 子供向 / 特摄排除 | 内置中日双语关键词表（蜡笔小新、哆啦A梦、面包超人、光之美少女、假面骑士、奥特曼、宝可梦、数码宝贝等约 40 项）+ Bangumi 标签「子供向/幼儿/少儿/亲子/早教」 |
| 长寿番排除 | 开播早于 3 年且仍在放送的常驻长篇，默认不列入当日表 |
| 深夜档归属 | 北京时间 1 点前播出归入前一天，避免漏项 |
| 译名补全 | 日文原名缺中文译名时用 B站搜索交叉验证，至少 2 条视频标题命中才采纳，否则保留原名 |

### 4. 多微信号

一个网关可绑定多个微信，各自独立的 agent、会话历史与发送额度，互不影响。

### 5. 通道可靠性

- 持久化发送队列：发送失败不丢消息，自动重试，重启后重新渲染卡片补发
- 额度感知：一条推送需 2 条额度，不足整条排队，不发半条
- 额度预警与积压提醒：剩 1 条时告知有内容积压，促使回话重置
- 会话保活：24 小时有效期前，在白天时段提醒回话
- 自愈：分发卡死自动重启网关，会话异常只排队不乱发

### 6. 番剧信息源

番剧数据不依赖 B站 的番剧库，来自以下公开源：

| 数据源 | 提供什么 |
|---|---|
| **bangumi-data**（主源） | 番剧清单、开播/完结日期、每周放送时刻（`broadcast` 重复规则）、中文译名（`titleTranslate`）、分站链接 |
| **Bangumi API** | 中文名 `name_cn`、分类标签 `tags`、封面 `images`、分集表 `/v0/episodes` 的 `airdate` |
| **AniList** | `nextAiringEpisode`，下一集集数与播出时间 |
| **Mikan（蜜柑）** | 字幕组资源与更新，用于集数兜底、封面缓存 |
| **B站番剧时间线** | 备用当日番剧表 |

取值规则：

| 用途 | 顺序 / 规则 |
|---|---|
| 今日放送 | bangumi-data 的 `broadcast` 推算，换算北京时间 |
| 中文译名 | bangumi-data → Bangumi `name_cn` → B站搜索交叉验证（≥2 条标题命中才采纳） |
| 集数 | **三源投票**（Bangumi 分集表 / bangumi-data 推算 / AniList），至少两源一致才采信，否则显示 `?` |
| 完结判定 | bangumi-data 的 `end` 早于当前时间即视为完结 |
| 封面 | Bangumi `images.large` → Mikan 缓存 |

本地缓存：`bd.json` 12 小时、`meta_cache.json` 30 天、`eps_cache/` 24 小时、`eps_vote/` 12 小时。需要能访问 `unpkg.com` 与 `api.bgm.tv`，受限网络用 `BGM_PROXY`。

所有出站消息经本机 OpenClaw 网关（`127.0.0.1`）转发，不对外暴露端口；B站接口需 cookie，放送表需能访问 `unpkg.com`（受限网络用 `BGM_PROXY`）。
代码里另有抖音 / 小红书 / 微博 / 斗鱼 / 虎牙的查询适配，以及 Bark / Telegram / 飞书 / 企业微信 / 钉钉 / Server酱 / QQ 的推送通道，**默认全部禁用**。

---

## 二、运维方式

### 服务清单

| 单元 | 类型 | 周期 | 职责 |
|---|---|---|---|
| `aio-dynamic-push.service` | 常驻 | — | 轮询 B站、渲染卡片、投递队列 |
| `openclaw-gateway.service` | 常驻 | — | 微信收发、agent 对话、cron 任务 |
| `wx-watchdog.timer` | 定时 | 3 分钟 | 分发卡死检测与自愈重启 |
| `wx-session-probe.timer` | 定时 | 30 分钟 | 会话健康探测（只读） |
| `wx-ping-reminder.timer` | 定时 | 20 分钟 | 会话保活提醒 |

### 日常检查

```bash
systemctl status aio-dynamic-push openclaw-gateway   # 服务状态
journalctl -u aio-dynamic-push -f                    # 推送日志
openclaw channels status                             # 微信在线状态
tail -5 /var/log/wx_session.log                      # 会话健康：OK / FAIL
tail -5 /var/log/wx_watchdog.log                     # 自愈动作记录
python3 -m json.tool /opt/aio-dynamic-push/data/outbox.json   # 待发队列
```

### 额度模型

```
每条用户消息 → bot 可发 10 条
单条番剧推送 = 卡片 1 条 + 链接文本 1 条 = 2 条
剩余 ≥ 2 → 正常发送
剩余 = 1 → 不推送，改发积压清单（提示回话）
剩余 = 0 → 静默等待
24 小时无互动 → 额度归零，需重新扫码
```

### 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `sendMessage ret=-2 prepare failed` | 额度耗尽 | 微信里回一句话 |
| `errcode -14 session timeout` | 会话凭据失效 | `openclaw channels login --channel openclaw-weixin` |
| B站接口返回 `412` | cookie 过期 | 重填 `config.yml` 的 `cookie` |
| 扫码成功但收不到回复 | 微信里换成了新对话窗口 | 找新窗口，旧窗口已废弃 |
| 队列只增不减 | 额度长期为 0 | 检查 `outbox.json` 与配额提示 |

### 迁移

```bash
./export.sh                                   # 旧机器：导出配置 + 状态
./install.sh                                  # 新机器：装环境
tar -xzf anime-push-state-*.tar.gz -C /       # 恢复状态
systemctl restart openclaw-gateway aio-dynamic-push
```

扫码凭证无法跨机复用，迁移后需重新扫码一次。

---

## 三、实施方式

### 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Ubuntu 22.04 / Debian 12 |
| 配置 | 1 核 1 G 起（网关常驻约 600 MB 内存） |
| Node.js | ≥ 22（脚本自动安装 v24） |
| Python | 3.10+（用 venv 隔离） |
| 依赖 | 中文字体（Noto CJK）、curl |

### 安装流程

`install.sh` 九个幂等步骤：

```
1. 系统依赖（python3 / venv / Noto CJK / curl）
2. Node.js ≥ 22（缺失时用 nvm 装 v24）
3. npm 安装 OpenClaw
4. 安装并启用微信通道插件
5. 部署监控程序到 /opt/aio-dynamic-push
6. 创建 venv 并安装 Python 依赖
7. 部署放送表子系统到 /root/anime_push
8. 部署运维脚本到 /root
9. 安装并启动 systemd 单元
```

### 配置

主配置：`/opt/aio-dynamic-push/config.yml`，模板见 `config.example.yml`。

必填三类：

```yaml
cookie: "SESSDATA=...; bili_jct=...; buvid3=...; buvid4=...; DedeUserID=..."   # B站
deepseek_key: sk-...                                                          # 广告判断
targets:                                                                      # 微信 userId
  - o9cqXXXX@im.wechat
```

关键可调项：

| 字段 | 说明 | 默认 |
|---|---|---|
| `uid_list` | 要订阅的 UP 主 UID | — |
| `intervals_second` | 轮询间隔 | 600 |
| `card_style` | 卡片样式 `bleed` / `inset` | bleed |
| `send_link` | 是否附带链接文本 | true |
| `quota_max` | 单轮额度 | 10 |

### 绑定微信

```bash
openclaw channels login --channel openclaw-weixin              # 终端出二维码，手机扫
cat /root/.openclaw/openclaw-weixin/accounts/*-im-bot.json     # 取 userId
# 回填到 config.yml 的 targets，然后：
systemctl restart aio-dynamic-push
```

多微信：重复扫码，两个 userId 都写进 `targets`，并执行
`openclaw config set session.dmScope per-account-channel-peer` 隔离会话。

### 放送表定时任务

由 OpenClaw 的 cron 驱动，安装后手动建一次：

```bash
openclaw cron add --name "番剧放送表推送" \
  --cron "0 9 * * *" --tz Asia/Shanghai --agent main \
  --message "每日番剧推送。工作目录 /root/anime_push。执行 bgm_schedule.py 取列表，
             用 make_card.py 生成卡片，再发送到 config.yml 中配置的所有 targets。"
```

### 卡片调试

```bash
cd /opt/aio-dynamic-push && ./.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from push_channel.card import render_card
render_card('番剧名','正文','UP名','https://www.bilibili.com','/tmp/preview.png',style='bleed')
"
```

---

## 四、目录结构

```
anime-push-clawbot/
├── install.sh              一键安装
├── export.sh               导出状态（迁移用）
├── config.example.yml      配置模板
├── code/
│   ├── aio-dynamic-push/   监控主程序
│   └── anime_push/         放送表子系统
├── scripts/                看门狗 / 会话探测 / 保活提醒
├── systemd/                1 常驻服务 + 3 组定时器
├── README.md               完整文档
└── LICENSE                 MIT + 第三方声明
```

## License

MIT。上游项目与第三方数据源遵循各自许可，见 [LICENSE](./LICENSE)。
