# wpp-hermes-cloud

Hermes Agent 的 **WPP Cloud 托管个人微信** 平台插件。它是
[`wpp-hermes`](https://github.com/jiexiaoyin/wpp-hermes) 的 WPP-only 分支：
只对接 WPP 托管网关，不再直连 vendor 服务。

| 方向 | 本插件（WPP Cloud） | 原 vendor 插件 |
| --- | --- | --- |
| 出站 | `https://<host>/api/v1/gateway` + `Authorization: Bearer wxa_...` | `https://<host>/api/...?authcode=...` |
| 凭据 | WPP 网关令牌（每账号一把） | vendor authcode + tokenKey |
| 入站主通道 | WPP 控制台「消息回调」→ 本插件 webhook | vendor `/Webhook/Set` |
| 入站兜底 | `/Msg/Sync` 每 60s + 收到通知立即拉 | vendor WS + `/Msg/Sync` |
| vendor WS | **不建立** | `wss://.../ws/sync` |
| vendor 回调注册 | **不注册**（槽位归 WPP） | 每 5 分钟 `/Webhook/*` |

- 插件包名：`wpp-cloud-platform`（`plugin/plugin.yaml`），**可以与原插件并存安装**。
- Hermes 平台名仍是 `wechatpadpro`（工具、配置键、cron 投递变量都依赖它）
  ⇒ **同一进程里同一时间只能启用一个**。切换时先停旧插件，再启本插件。
- 不修改 Hermes 本体代码；所有能力都在插件目录内。

完整配置与排障见 [`docs/wpp-cloud.md`](docs/wpp-cloud.md)。

## 1. WPP 控制台准备

1. 账号已导入/托管在 WPP（Authcode 属于共享生产客户端）。
2. 在账号详情里**签发网关令牌**：`wxa_...`。只完整展示一次；重新签发会让旧令牌失效。
3. 启动插件后读取本账号应填的回调 URL：

   ```bash
   python3 - <<'PY'
   from plugin.core import accounts
   print(accounts.resolve("default").cloud_callback_url)
   PY
   ```

   把它填到 WPP 控制台的**普通回调**。若账号仍显示「Standalone 导入 / 只读」，
   管理员先在账号详情点「转为云托管」再保存；转托管不轮换 authcode、网关令牌
   或微信会话。已转托管（origin=wpp）的账号直接保存即可，无需 `?takeover=1`
   （business 回调不受影响）。
4. 把回调的 customer secret 配到账号文件的 `webhookSecret`。WPP 发送 v2 签名：

   ```
   X-Webhook-Signature = hex(HMAC-SHA256(secret, f"{TimestampMs}.{DeliveryID}." + raw_body))
   X-Webhook-Timestamp-Ms / X-Webhook-Delivery / X-Webhook-Signature-Version: v2
   ```

   只配 `webhookPathToken` 也能工作（fail-closed），但不推荐。

## 2. 最小配置

`.env` / profile env：

```dotenv
WPP_CLOUD_GATEWAY_URL=https://wpp.example.com/api/v1/gateway
WPP_GATEWAY_TOKEN=wxa_xxxxxxxx
WECHATPRO_WEBHOOK_PUBLIC_URL=https://plugin.example.com
```

`plugin/accounts/default.json`（参考 `cloud.example.json`）：

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
  "webhookSecret": "<与 WPP 回调 secret 一致，可留空>"
}
```

- 只写 `gatewayToken` / `gatewayTokenEnv` 会自动进入 cloud 模式。
- `authcode` / `tokenKey` 在 cloud 模式下**不生效**；`autoSetWebhook` 强制为 `false`。
- 多账号按原插件方式各建一份 `accounts/<id>.json`，每账号一把网关令牌。

## 3. 入站语义

- WPP 普通回调可能是**完整消息**，也可能只是 `sync_message` 通知（没有正文）。
  通知会立即触发 `/Msg/Sync`，回调线程不等待 HTTP。
- **首次同步不回放**：本机第一次同步只保存 `KeyBuf` 游标，不派发厂商返回的历史。
- **先派发、后前进游标**：进程中途退出时下一轮会重复拉到同一批，由消息
  `msgId` 去重兜底（at-least-once）。
- **失败只告警**：`/Msg/Sync` 失败不会停掉平台，下一轮定时器继续重试。

## 4. 网关边界

WPP 网关只开放业务面；插件在本地先挡一次，给出可行动的错误：

- 屏蔽家族：`Admin` / `Webhook` / `Runtime` / `Customized`；
- 屏蔽操作：`/Tools/SetProxy`、`/Tools/GetBoundHardDevices`、
  `/Msg/StartAutoSync`、`/Msg/StopAutoSync`；
- `Login` 只放行：`GetLoginStatus`、`LongLinkStatus`、`HeartBeatLong`、`AutoHeartBeat`。

## 5. 部署与切换

```bash
# 只同步代码到独立插件目录（不重启）
bash sync.sh

# 同步并重启网关
bash deploy.sh --local --restart
```

目标目录固定为 `~/.hermes/plugins/wpp-cloud-platform`；**不会碰**
`~/.hermes/plugins/wechatpadpro`，也不会覆盖任何 `accounts/` 或生产凭据。

生产切换顺序：

1. 停用旧插件（原 `wechatpadpro` 实例），避免两边同时拉消息；
2. 启用 `wpp-cloud-platform`；
3. 在 WPP 控制台把回调切到 `cloud_callback_url`；
4. 观察日志：`增量兜底启动` → `首次同步：只建立游标` → `收到 WPP 消息通知`。

## 6. 测试

```bash
python -m pytest -q
```

> 必须在 Hermes 的 Python 环境中运行（`gateway` / `ruamel.yaml` / `aiohttp` 可见），
> 并先装好 `pytest` / `pytest-asyncio`。
> cloud 专项用例：`test_wpp_cloud_client.py`、`test_sync_fallback.py`、
> `test_webhook.py`、`test_enablement.py`、`test_accounts.py`。

## 仓库约定与自动同步

- 所有协作/agent 规则见 [AGENTS.md](AGENTS.md)。
- 本仓库配置了 git 自动同步：`git commit` 后由 hook 自动推送，另有 5 分钟兜底的
  systemd timer（`scripts/install-autosync-timer.sh`）。手动同步：
  `bash scripts/git-autosync.sh`；新克隆先跑 `bash scripts/install-git-hooks.sh`。
- 提交前敏感信息扫描：`python3 scripts/check_public_tree.py`（pre-commit 也会跑）。

