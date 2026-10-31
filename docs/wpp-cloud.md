# 云端托管模式

本插件把个人微信（Pad 协议）接入 Hermes，账号由
[云端社交聚合平台](https://cloud.juhe.chat)托管；插件只对接平台网关。

| 方向 | 本插件（云端托管） | 直连模式（历史） |
| --- | --- | --- |
| 出站 | `https://<host>/api/v1/gateway` + `Authorization: Bearer wxa_...` | `https://<host>/api/...?authcode=...` |
| 凭据 | 平台网关令牌 `wxa_...`（每托管账号一把） | 直连 authcode + tokenKey |
| 入站主通道 | 平台控制台「普通回调」→ 本插件 webhook | 直连 `/Webhook/Set` → 本插件 webhook |
| 入站兜底 | `/Msg/Sync` 每 60s + 收到通知立即拉 | 长连接 + `/Msg/Sync` |
| 长连接 | **不建立** | `wss://.../ws/sync` |
| 回调注册 | **不注册**（由平台控制台管理） | 每 5 分钟 `/Webhook/*` |

Hermes 平台名沿用 `wechatpadpro`（工具集、配置键、cron 投递变量都依赖这个名字），
所以与直连模式的旧账号插件**同一时间只能启用一个**；切换时先停旧、再启新。

## 1. 在 WPP 控制台准备

1. 账号已导入或托管在 WPP（Authcode 属于共享生产客户端）。
2. 在「凭证 / 账号」详情里**签发网关令牌**（`wxa_...`）。令牌只完整展示一次；
   重新签发会让旧令牌立即失效。
3. 在「回调管理」里把该账号的**普通回调**指向本插件：

   ```
   https://<插件公网地址><webhookPath，含 webhookPathToken>
   ```

   - 已转云托管（origin=wpp）的账号，直接保存普通回调即可。
   - 仍是导入只读（origin=standalone）的账号，管理员可先在账号详情点
     「转为云托管」，再保存回调；也可临时用 `?takeover=1` 接管。转托管只改
     控制面，不轮换 authcode / 网关令牌，也不会让微信会话掉线。
   **business 回调不受影响**（WPP 不中继 business）。

4. 回调的 customer secret 可与账号 `webhookSecret` 保持一致 —— WPP 会发
   `X-Webhook-Signature` v2（`HMAC-SHA256(secret, f"{TsMs}.{DeliveryID}." + body)`），
   本插件按同一算法校验；只配 `webhookPathToken` 也能工作（fail-closed）。

## 2. 配置插件

最小 `.env`：

```dotenv
WPP_CLOUD_GATEWAY_URL=https://cloud.juhe.chat/api/v1/gateway
WPP_GATEWAY_TOKEN=wxa_xxxxxxxx
# 可选：WPP 回调指向的本插件地址
WECHATPRO_WEBHOOK_PUBLIC_URL=https://plugin.example.com
```

对应账号文件（`plugin/accounts/default.json`，参考 `cloud.example.json`）：

```json
{
  "enabled": true,
  "cloudMode": true,
  "agent": "wpp-wechat",
  "apiBaseUrl": "https://cloud.juhe.chat/api/v1/gateway",
  "gatewayTokenEnv": "WPP_GATEWAY_TOKEN",
  "webhookPath": "/wechatpadpro/webhook",
  "webhookPathToken": "<随机串>",
  "webhookPublicUrl": "https://plugin.example.com",
  "webhookSecret": "<与 WPP 回调 secret 一致，可留空>"
}
```

- 只写 `gatewayToken` 而不写 `cloudMode` 也会自动进入 cloud 模式。
- `authcode` / `tokenKey` 在 cloud 模式下**不生效**，残留值不会被当成凭据。
- `autoSetWebhook` 在 cloud 模式下强制为 `false`。

## 3. 插件视角的账号 URL

`Account.cloud_callback_url` 会给出「WPP 控制台应该填的完整 URL」（派生路径已含
`webhookPathToken`）。两种取法：

* **控制台**：`GET /accounts/<id>/diagnostics` 的 `webhook_url` 字段（v3.1.0 起；
  token **已打码**，可直接贴进工单/日志）。
* **命令行**：下面的脚本打印**明文**（只在本人终端用，别贴聊天工具）：

```bash
python3 - <<'PY'
from plugin.core import accounts
print(accounts.resolve("default").cloud_callback_url)
PY
```

## 4. 安全边界

平台网关只开放业务面。插件在本地先挡一次，错误信息可直接行动：

- 控制面、回调注册、运行时管理等非业务接口一律拒绝（清单随平台版本调整，不展开）；
- 登录类只放行状态查询与心跳；
- 同步开关、网络出口等影响共享会话的操作由平台控制台负责。

## 5. 重试与兜底语义（v3.1.0 起）

| 面 | 行为 |
| --- | --- |
| 读端点重试 | `502/503/504`，指数退避 |
| 写端点重试 | 只重试 `408/429/503` 一次；`Retry-After` 优先，夹到 `[0.2s, 10s]` |
| 写端点不重试 | `500/502/504`（无法判断是否已执行）、超时、断连 |
| 回调处理 | 验签后立即 `200`，正文异步派发（WPP 不会因为插件慢而重投） |
| `/Msg/Sync` 派发失败 | 本轮游标**不前进**，下一轮重拉失败条目；连续 3 轮仍失败则放弃并 ERROR 记丢 |
| 在途拉取期间的触发 | 记为 pending，本轮结束立刻补拉一趟（不会丢通知） |
| 首次拉取（库里无游标） | 只落基线、一条都不回放 |

## 6. 排障

| 现象 | 先看 |
| --- | --- |
| 平台未启用 | `hermes plugins list`；`.env` 里是否有 `WPP_GATEWAY_TOKEN` |
| 出站 401 | 令牌是否被重新签发 / 账号是否 active / 网关地址是否以 `/api/v1/gateway` 结尾 |
| 出站 429/503 后恢复 | 日志里的 `-> HTTP 429/503，Ns 后重试`；网关给的 `Retry-After` 会被尊重 |
| 入站全丢 | WPP 控制台回调 URL 是否带派生后的 path token；插件 webhook 端口是否公网可达 |
| 回调 403 | `webhookSecret` 是否与 WPP 回调 secret 一致（v2 HMAC）|
| 日志 `webhook 启动失败 … 端口被占用` | 多账号本就共用一个 server；真被别的进程占住时换 `webhookPort` |
| 日志 `CmdList 是映射但没有 List 数组` | vendor 响应形状变了：先核对 `/Msg/Sync` 原始响应，别急着改游标 |
| 日志 `条兜底消息派发失败（本轮游标不前进）` | 看同批的 `处理消息 … 失败` 原因；修好下游后 60s 内会自动重拉 |
| 只收到通知不回复 | 看日志 `收到 WPP 消息通知（无正文），触发 /Msg/Sync 拉取`；再查 `/Msg/Sync` 是否报错 |
