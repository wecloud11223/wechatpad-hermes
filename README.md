# wechatpad-hermes

**个人微信（Pad 协议）· 云端托管 · Hermes Agent 平台插件**

让 Hermes 直接拥有一个真实的个人微信号：账号托管在
[**云端社交聚合平台**](https://cloud.juhe.chat)，扫码接入、7×24 在线，插件只对接
平台网关（一把 `wxa_…` 令牌），不依赖设备、模拟器或自建协议服务。

- 平台：Hermes `>= 0.21.5`
- 版本：`3.1.0`
- 许可：MIT
- 能力面：**292 个 `wpp_*` 工具** + 平台收发 + 群运营 + 心流 + 控制台

---

## 为什么走云端托管

| | 自建协议端 | **本插件 + 云端托管平台** |
| --- | --- | --- |
| 接入 | 部署协议服务、维护设备/模拟器、跟随协议升级 | 控制台**扫码托管**，插件只填网关地址 + 令牌 |
| 稳定性 | 掉线/风控/会话失效全自己兜 | 平台侧会话保持、心跳与重连，账号常在线 |
| 多账号 | 多进程多端口多套配置 | 多份账号 JSON，一个账号一把网关令牌 |
| 观测 | 只有自己的日志 | 控制台 7 个页签 + `/metrics` + 诊断接口 |
| 边界 | 全量接口暴露 | 网关只开业务面，管理/回调注册类接口本地直接拦截 |

一句话：**协议与会话交给平台，Agent 只专注「说什么、什么时候说」。**

---

## 核心能力

### 消息与媒体

- 收发文本、图片、语音、视频、文件、链接卡片、名片、位置、小程序、引用回复、撤回。
- 语音双向：入站 SILK 解码 + 转写（给模型看）；出站按情绪 TTS 合成语音，
  编码失败自动降级成语音文件。
- 媒体内联编码走线程池 + 200MB 上限，不阻塞事件循环；大文件走上传通道。

### 292 个工具，19 个能力域

| 域 | 数量 | 域 | 数量 |
| --- | --- | --- | --- |
| 消息收发与互动 | 26 | 语音与媒体文件 | 20 |
| 群聊管理 | 24 | 账号、登录与资料 | 37 |
| 好友与通讯录 | 20 | 朋友圈 | 29 |
| 微信搜索 | 23 | 视频号 | 19 |
| 公众号 | 15 | 支付与红包 | 16 |
| 小程序 | 12 | 收藏 / 企微联系人 | 4 / 3 |
| 小微智能体 | 20 | MCP 兼容工具 | 10 |

模型按自然语言自动选工具，也可以直接点名（如 `wpp_send_text`、`wpp_fc_list`）。
完整清单见 [docs/tools.md](docs/tools.md)。

### 双通道入站

| 通道 | 作用 |
| --- | --- |
| 平台普通回调（webhook） | 主通道；v2 HMAC（±300s）、缺 secret 时 fail-closed |
| `/Msg/Sync` 兜底 | 默认 60s 一轮；收到回调通知立刻补拉 |

- **首次同步不回放**：只落 `KeyBuf` 游标，重启不会补回历史。
- **先派发、后前进游标**：进程退出最多重复，由 `msgId` 去重兜底（at-least-once）。
- **派发失败游标不前进**：本轮失败下一轮重拉；连续 3 轮仍失败才放弃并记 ERROR，
  既不静默丢消息，也不会让一条坏消息永久堵死兜底通道。
- **在途补拉**：拉取过程中又收到通知，本轮结束后立即再拉一次，不丢触发。

### 群运营

- 群白名单 / 黑名单 / 静默、私聊放行、必须 @ 才回复。
- 成员变动识别：进群/退群系统通知驱动成员表更新。
- 进群欢迎：模板变量 + @ 新人，可按群画像润色。
- 复读保护：同内容窗口内抑制，且**确认发送成功后才计数**。

---

## 特色功能

这些能力是「让机器人像群成员」的关键，默认关闭、按需开启，失败只降级不阻塞收发。

### 群聊心流（heartflow）

群消息 90% 不需要机器人开口。心流用一次小模型调用做**五维打分**
（相关性 / 意愿 / 社交适宜 / 时机 / 连续性），加权过阈值才接话。

- **三重预算取更严**：账号配置、群画像建议、外环占比三者取最严格的一档
  —— 画像只能让它更克制，不能让它更激进。
- **群画像**：自动总结每个群的身份、话题、活跃时段，供判定参考。
- **冷却与频率限制**：同步预筛先拦掉不该花的模型调用。
- **台账留痕**：过没过阈值、为什么被拦，全部落库，方便复盘调参。

### 好感度与情绪

按群内互动记账，影响回复语气与 TTS 情绪；私聊没有群情绪记录，固定 `calm`。

### 意图识别与群上下文

群里 @ 机器人时只挑相关消息注入上下文（可选向量检索），避免被无关聊天带偏。

### 黑话挖掘与说话风格

- **黑话**：从群聊里发现并解释本群特有词，回复时参考。
- **风格**：学习群友的句长、语气词、称呼、表情，让回复更像群里的人。

### 朋友圈

29 个工具覆盖发布（图文/视频）、列表、详情、点赞、评论、删除、可见范围；
`fristpagemd5` 翻页等平台细节都已封装。

### 历史检索

收发消息落 SQLite（默认）或 MySQL，可按人 / 群 / 关键词检索——
「上周三老王说的那个链接」这类问题不需要翻手机。

### 可观测控制台

Hermes dashboard 内嵌 **「云端社交聚合控制台」**（7 个页签）：

`状态运维` · `准入策略` · `进群欢迎` · `能力开关` · `群与成员` · `消息分析` · `心流运营`

- 3 秒热加载配置，跨进程写锁 + `expected_mtime_ns` 乐观并发（改冲突返回 409）。
- 不调用平台接口、不触发同步：只读写账号配置与本地库，页面不会把生产号拖慢。
- 诊断接口附带**打码后**的派生回调地址，排障时一眼对上平台控制台。

### 主动关心（私聊）

私聊场景按策略主动发起关心，白名单控制对象，可配时段与频次。

### MCP 兼容

开启后给 MCP 调用方一份精简工具集，方便外部 Agent 复用同一个微信号。

---

## 架构

```
 手机微信（真实账号）
      │  扫码登录，会话由平台维持
      ▼
┌──────────────────────────────────┐
│ 云端社交聚合平台  cloud.juhe.chat   │
│  扫码托管 · 会话保持 · 心跳重连      │
└───────────────┬──────────────────┘
                │ 出站：POST /api/v1/gateway + Bearer wxa_…
                │ 入站：普通回调（v2 HMAC）/ 通知触发 /Msg/Sync
                ▼
┌──────────────────────────────────┐       ┌─────────────────┐
│ wechatpad-hermes                  │◄─────►│   Hermes Agent   │
│ 账号/策略 · 回调 · 兜底 · 工具 · 心流 │       │ 模型 / 技能 / 定时 │
└──────────────────────────────────┘       └─────────────────┘
```

---

## 快速开始

### 1. 平台托管 + 签发令牌

账号导入 [云端社交聚合平台](https://cloud.juhe.chat) 后，在账号详情签发网关令牌
（`wxa_…`，只完整展示一次；重新签发会让旧令牌失效）。

### 2. 安装插件

```bash
# 把 plugin/ 放到 Hermes 插件目录（目录名即插件 id，保持 wpp-cloud-platform 不变）
cp -r plugin ~/.hermes/plugins/wpp-cloud-platform
```

`.env` / profile env：

```dotenv
WPP_CLOUD_GATEWAY_URL=https://wpp.example.com/api/v1/gateway
WPP_GATEWAY_TOKEN=wxa_xxxxxxxx
WECHATPRO_WEBHOOK_PUBLIC_URL=https://plugin.example.com
```

### 3. 账号配置

`plugin/accounts/default.json`（参考 `cloud.example.json`，真实账号文件不入库）：

```json
{
  "enabled": true,
  "cloudMode": true,
  "agent": "wpp-wechat",
  "apiBaseUrl": "https://wpp.example.com/api/v1/gateway",
  "gatewayTokenEnv": "WPP_GATEWAY_TOKEN",
  "webhookPath": "/wechatpadpro/webhook",
  "webhookPathToken": "<随机串>",
  "webhookPublicUrl": "https://plugin.example.com",
  "webhookSecret": "<与平台回调 secret 一致，可留空>"
}
```

只写 `gatewayToken` / `gatewayTokenEnv` 即自动进入 cloud 模式；`authcode` / `tokenKey`
不生效，回调注册强制关闭（回调由平台控制台管理）。

### 4. 回填回调

```bash
python3 - <<'PY'
from plugin.core import accounts
print(accounts.resolve("default").cloud_callback_url)
PY
```

把该地址填到平台控制台的**普通回调**，secret 配到账号文件的 `webhookSecret`。

### 5. 验证

```bash
HERMES_HOME=~/.hermes hermes gateway restart
```

日志依次出现：`增量兜底启动` → `首次同步：只建立游标` → `收到消息通知`。
控制台「状态运维」页签能看到连接状态。

---

## 可靠性细节

| 场景 | 行为 |
| --- | --- |
| 网关 408 / 429 / 503 | 写操作也重试一次，优先 `Retry-After`（夹到 0.2–10s） |
| 网关 500 / 502 / 504 | 写操作不重试（防重复发送），读操作正常重试 |
| 兜底派发失败 | 游标不前进、下一轮重拉；连续 3 轮放弃并记 ERROR |
| 通知在拉取途中到达 | 本轮结束后立即补拉（pending） |
| 同一消息重复投递 | `msgId` 去重（at-least-once） |
| 媒体过大 / 读取失败 | 可读错误 + 降级，不阻塞事件循环 |

## 安全边界

平台网关只开放业务面：控制面、回调注册、运行时管理等非业务接口由客户端本地预挡，
越界调用直接返回可读错误，不会打到平台。具体策略随平台版本调整，不在文档中展开。

## 部署与切换

```bash
bash sync.sh                   # 只同步代码，不重启
bash deploy.sh --local --restart  # 同步并重启网关
```

目标目录固定 `~/.hermes/plugins/wpp-cloud-platform`，不会碰 `accounts/` 与任何生产凭据。

## 命名与兼容

- 对外名称：**wechatpad-hermes**（本仓库）。
- 内部标识：插件 id `wpp-cloud-platform`、Hermes 平台名 `wechatpadpro`、
  环境变量 `WPP_CLOUD_*` / `WECHATPRO_*` —— 为兼容既有部署、工具名、配置键与
  定时投递变量保持不变。

## 测试

```bash
# 需要 Hermes 运行时（gateway 包）+ pytest / pytest-asyncio / ruamel.yaml
python -m pytest plugin/tests -q
```

CI 在公开 runner 上只跑静态检查与敏感信息扫描；完整用例需要 Hermes 运行时，
详见 [AGENTS.md](AGENTS.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/wpp-cloud.md](docs/wpp-cloud.md) | 云端模式接入、配置与排障 |
| [docs/features.md](docs/features.md) | 心流 / 欢迎 / 好感度 / 语音 / 检索等增强能力 |
| [docs/tools.md](docs/tools.md) | 292 个工具清单 |
| [docs/configuration.md](docs/configuration.md) | 环境变量与账号字段总表、控制台 |
| [docs/architecture.md](docs/architecture.md) | 数据流、进程模型与错误路径 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 常见故障定位 |
| [AGENTS.md](AGENTS.md) | 协作规范、git 自动同步、CI 说明 |

## 链接

- 云端社交聚合平台：<https://cloud.juhe.chat>
- 问题反馈：<https://github.com/wecloud11223/wechatpad-hermes/issues>
