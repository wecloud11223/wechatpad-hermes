# 安装、升级与卸载

> 本仓库是 **WPP Cloud 专用**的 Hermes 插件（`wpp-cloud-platform`），只对接
> WPP 托管网关：出站 `https://<host>/api/v1/gateway` + `Authorization: Bearer wxa_...`，
> 入站由 WPP 控制台「消息回调」触发 + `/Msg/Sync` 每 60s 兜底。**不直连 vendor、
> 不建 vendor WebSocket、不向 vendor 注册 `/Webhook/*`**。
>
> 原 vendor 直连插件 `wechatpadpro-platform` 保持不动；两者使用同一个 Hermes
> 平台名 `wechatpadpro`，**不能同时启用**（同名平台会互相遮蔽）。
>
> AstrBot 用户请用 [astrbot-plugin-wpp-cloud](https://github.com/jiexiaoyin/astrbot-plugin-wpp-cloud)。

## 前置条件

| 项 | 要求 |
|---|---|
| Hermes Agent | `>= 0.21.5`（插件使用 `env_enablement_fn` 挂载点） |
| Python | `>= 3.11` |
| WPP Cloud | 已在控制台托管该微信账号，并签发**网关令牌** `wxa_...`（每账号一把，≠ vendor authcode） |
| 回调地址 | WPP 控制台能访问到插件 webhook 的公网地址（由 nginx/反代转到 `webhookHost:webhookPort`） |
| 网络 | 插件所在机器能访问 WPP 网关 `https://<host>/api/v1/gateway` |
| 可选 | MySQL/MariaDB（默认内置 SQLite）、ossutil、ffmpeg、silk 编解码器、LLM / STT key（缺失时对应能力降级） |

确认 Hermes 版本：

```bash
hermes --version
```

## 必填环境变量

写入对应 profile 的 `.env`（`0600`），**不要把明文写进 `config.yaml` 或账号 JSON**：

```dotenv
WPP_CLOUD_GATEWAY_URL=https://<host>/api/v1/gateway
WPP_GATEWAY_TOKEN=wxa_xxxxxxxx
```

| 变量 | 说明 |
|---|---|
| `WPP_CLOUD_GATEWAY_URL` | WPP 网关根地址（必须以 `/api/v1/gateway` 结尾） |
| `WPP_GATEWAY_TOKEN` | 该托管账号的 WPP 网关令牌 |
| `WPP_CLOUD_MODE` | 可选，置 `1` 强制 WPP 模式；本插件默认即 WPP 模式 |
| `WECHATPRO_WEBHOOK_PUBLIC_URL` | 可选，插件 webhook 公网基地址（WPP 回调指向这里）；留空则退化为纯 `/Msg/Sync` 轮询 |

## 方式 A：deploy.sh（本分支生产路径）

```bash
bash deploy.sh --check              # 只预览差异
bash deploy.sh --local              # 同步到 ~/.hermes/plugins/wpp-cloud-platform
bash deploy.sh --local --restart    # 同步后重启 Hermes gateway
```

`deploy.sh` 只写 `~/.hermes/plugins/wpp-cloud-platform`，**不碰**旧
`wechatpadpro` 目录、`accounts/`、`data/`。

## 方式 B：安装脚本

```bash
git clone <repo-url> wpp-hermes
cd wpp-hermes
bash scripts/install.sh
```

常用参数：

```bash
bash scripts/install.sh --home /srv/hermes        # 指定 Hermes home
bash scripts/install.sh --profile wpp-wechat      # 装进某个 profile
bash scripts/install.sh --dry-run                 # 只打印将执行的操作
bash scripts/install.sh --no-wizard               # 只复制并启用
```

脚本行为：

1. 检查 `HERMES_HOME` 与目标插件目录；
2. 把 `plugin/` 复制到 `<home>/plugins/wpp-cloud-platform`（已有目录时先备份，保留 `accounts/`）；
3. 调用 `hermes plugins enable wpp-cloud-platform`；
4. 调用 `setup_wizard.py` 完成配置（向导首项即 WPP 网关地址与网关令牌）；
5. 打印 `hermes plugins doctor` 与重启命令。

## 方式 C：手动安装

```bash
mkdir -p "$HERMES_HOME/plugins"
cp -r plugin "$HERMES_HOME/plugins/wpp-cloud-platform"
chmod 700 "$HERMES_HOME/plugins/wpp-cloud-platform/accounts"
python3 "$HERMES_HOME/plugins/wpp-cloud-platform/setup_wizard.py"
hermes plugins enable wpp-cloud-platform
hermes plugins doctor "$HERMES_HOME/plugins/wpp-cloud-platform"
```

如果 Hermes 使用隔离解释器，还需要把依赖装进它：

```bash
<hermes-python> -m pip install 'aiohttp>=3.9,<4' 'websockets>=12,<16' 'pymysql>=1.1,<2'
```

> `websockets` 仅保留给可选的 vendor 兼容分支；WPP 模式不会建立 WS 连接。

## 账号文件

复制 `plugin/accounts/default.example.json` 为 `accounts/default.json`（`0600`），按 WPP 规范至少确认：

```json
{
  "enabled": true,
  "cloudMode": true,
  "apiBaseUrl": "https://<host>/api/v1/gateway",
  "gatewayTokenEnv": "WPP_GATEWAY_TOKEN",
  "webhookPublicUrl": "https://<插件公网域名>",
  "webhookSecretEnv": "WECHATPRO_WEBHOOK_SECRET",
  "selfWxid": "wxid_xxx",
  "agent": "wpp-wechat"
}
```

- 凭据只写 `*Env` 名称，明文放 `.env`。
- 不要写 `authcode` / `tokenKey` / `wsUrl` / `autoSetWebhook`：WPP 模式下这些字段不存在，插件也不会读取。
- `agent` 必须是对应 profile 名，**不要写 `main`**。

## WPP 控制台回调

1. 插件启动后日志会打印 `cloud_callback_url`（形如
   `https://<插件公网域名>/wechatpadpro/<webhookPathToken>/<账号ID>/webhook`）。
2. 在 WPP 控制台该账号的「消息回调」里填入该地址，事件选 `sync_message`，
   设置回调 secret（与 `.env` 的 `WECHATPRO_WEBHOOK_SECRET` 一致），重试 3 次、超时 5s。
3. 回调只作为“有新消息”的通知；插件收到后立即拉 `/Msg/Sync`，并且每 60s 兜底一次。
   **首次同步只落游标、不回放历史消息。**

## 多 profile

Hermes 的 profile 是独立的 `HERMES_HOME`（通常位于 `~/.hermes/profiles/<name>`）。
每个账号应绑定自己的 profile：

```bash
hermes profile create wpp-wechat
bash scripts/install.sh --home ~/.hermes/profiles/wpp-wechat
```

每个账号使用**独立**的 WPP 网关令牌、`selfWxid`、`webhookPort`，账号 JSON 的 `agent`
写该 profile 名。

## 升级

```bash
git pull
bash deploy.sh --local --restart
hermes plugins doctor "$HERMES_HOME/plugins/wpp-cloud-platform"
```

`deploy.sh` 不会覆盖 `accounts/` 与 `data/`。升级前如需手工备份，把旧插件目录
复制到 `/data/wpp-hermes-backup-<timestamp>/`。

从旧 vendor 版本迁移：

1. 先把账号 JSON 改成 WPP 结构（`cloudMode` / `apiBaseUrl` / `gatewayTokenEnv`）；
2. 停 gateway；
3. 把旧 `wechatpadpro` 插件目录**移出** `plugins/`（不是仅 disable，否则同名平台会遮蔽）；
4. 部署 `wpp-cloud-platform` 并在 `plugins.enabled` 里启用它；
5. 在 WPP 控制台配置回调，启动 gateway，确认日志出现
   `WPP Cloud 模式：不建立 vendor WS` 与 `平台已连接`。

## 卸载

```bash
bash scripts/uninstall.sh                 # 停用并删除代码目录，保留 .env 与账号
bash scripts/uninstall.sh --purge         # 连账号目录一起删
bash scripts/uninstall.sh --home /srv/hermes
```

手动卸载：

```bash
hermes plugins disable wpp-cloud-platform
rm -rf "$HERMES_HOME/plugins/wpp-cloud-platform"
```

`.env` 里的 `WPP_*` / `WECHATPRO_*` 变量需要自己清理，脚本不会动它（可能和其他组件共用）。
卸载本插件不会影响 WPP 侧的账号与回调配置；如需停用回调，在 WPP 控制台删除该账号的回调。

## 离线安装

```bash
git clone <repo-url> wpp-hermes
cd wpp-hermes
bash scripts/install.sh --no-wizard
# 然后按 docs/configuration.md 手工写 .env 与 accounts/default.json
```

依赖需要提前放进 Hermes 的解释器；`--no-wizard` 不会联网。
