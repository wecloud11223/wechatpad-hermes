# 排障

> 登录阶段被要求人脸 / 安全验证、或登录 IP 需要固定到自有主机时，
> 见 [人脸验证](face-verify.md) 与 [住宅出口](residential-egress.md)。

先跑只读检查，它会告诉你缺什么、下一步做什么，且不会打印密钥：

```bash
python3 "$HERMES_HOME/plugins/wpp-cloud-platform/setup_wizard.py" --check --json
hermes plugins doctor "$HERMES_HOME/plugins/wpp-cloud-platform"
```

---

## 插件没有加载

**症状**：`hermes plugins list` 里没有 `wpp-cloud-platform`，或平台不在线。

1. `hermes plugins list` 确认状态是 enabled；
2. `hermes --version` 必须 `>= 0.21.5`（插件依赖 `env_enablement_fn`）；
3. 看网关日志：

   ```bash
   journalctl --user -u hermes-gateway -n 100 --no-pager
   # 或
   tail -n 100 "$HERMES_HOME/logs/gateway.log"
   ```

4. 检查 `plugin.yaml` 是否在 `$HERMES_HOME/plugins/wpp-cloud-platform/plugin.yaml`；
5. 如果日志说缺 `aiohttp` / `websockets` / `pymysql`，把它们装进 **Hermes 自己的解释器**：

   ```bash
   <hermes-python> -m pip install 'aiohttp>=3.9,<4' 'websockets>=12,<16' 'pymysql>=1.1,<2'
   ```

---

## 平台已注册但不收消息

按顺序排查：

1. **账号是否连接**：`--check --json` 的 `ready`，以及日志里的连接行；
2. **凭据是否被别处占用**：一个 WPP 网关令牌只给一个客户端实例用。同一令牌在另一台
   机器/另一个 profile 上跑着，会把当前实例的通知流打乱；
3. **WPP 回调是否可达**：WPP 控制台该账号的「消息回调」地址应等于插件日志里的
   `cloud_callback_url`（`https://<公网域名>/wechatpadpro/<pathToken>/<账号>/webhook`），
   反代要转发到 `WECHATPRO_WEBHOOK_HOST:webhookPort`、事件选 `sync_message`；
4. **签名是否一致**：`.env` 的 `WECHATPRO_WEBHOOK_SECRET` 必须与 WPP 控制台该账号的
   回调 secret 逐字一致（v2 HMAC：`HMAC-SHA256(secret, f"{TimestampMs}.{DeliveryID}." + raw_body)`），否则 403；
5. **准入**：默认全放行；如果配了 `dmPolicy: allowlist`，用户不在 `allowFrom` /
   `WECHATPRO_ALLOWED_USERS` 里会被静默丢弃；`blacklistUsers` 一票否决；
   `pairing` 模式只放行已配对用户；
6. **群策略**：`groupPolicy` 为 `disabled` / `closed`，或 `allowlist` 但群不在
   `groupAllowFrom` 里，都会不回复；拼错的值按 fail-closed 处理；
7. **网关层**：`open` / `blacklist` / `pairing` 需要 `WECHATPRO_ALLOW_ALL_USERS=1`
   才过 Hermes 中心授权；缺它时日志会出现 `Unauthorized user`，插件侧什么都看不到。

WPP 模式下**没有 vendor WebSocket 兜底**：回调不通时只剩 `/Msg/Sync` 每 60s 轮询，
消息会延迟但不会丢。日志里出现 `/Msg/Sync` 200 说明出站凭据与账号在线状态正常，
此时应优先查回调 URL / secret / nginx 转发。

---

## 日志里一直有 webhook 403

- 确认请求确实来自 WPP 回调：应带 `X-Webhook-Signature` / `X-Webhook-Timestamp-Ms` /
  `X-Webhook-Delivery`，且 `X-Webhook-Signature-Version` 为空或 `v2`；
- `WECHATPRO_WEBHOOK_SECRET` 与 WPP 控制台该账号的回调 secret 是否逐字一致
  （不要带引号或多余空格）；
- 服务器时间是否准确（允许偏移默认 ±300 秒，`WPP_WEBHOOK_MAX_SKEW_SEC` 可调）；
- 路径 token 是否包含在 URL 中，且代理没有改写路径。

临时诊断可设 `WPP_WEBHOOK_DEBUG=1`，它会把签名头写进日志（含凭据风险），**验完立刻关闭**。

---

## 工具数量不对 / 工具没注册

- `plugin.yaml` 的 `provides_tools` 必须与实际注册逐名一致；
- 注册失败不会影响其他工具：日志里会有 `注册失败` 和模块名；
- 在仓库里跑契约测试：

  ```bash
  python -m pytest plugin/tests/test_registration.py -q
  ```

---

## 语音没有转成文字

需要两样东西：

1. silk 解码器：`WPP_SILK_DECODER_PATH`（默认 `~/silk_decoder/silk/decoder`）；
2. STT key：`WECHATPRO_STT_API_KEY` 或 `SILICONFLOW_API_KEY`。

缺任意一样，第一条无法转写的语音会打一条 WARNING，之后降为 DEBUG。模型看到的是
`[语音]` 一行。厂商自带转写（`voice.transcript`）存在时不会走本地转写。

出站语音需要 `WPP_SILK_ENCODER_PATH`；缺失时降级为文件发送。

---

## 媒体消息没有公网 URL（OSS）

OSS 默认关闭。确认：

1. `.env` 里有 `WECHATPRO_OSS_ENABLED=1`；
2. `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_BUCKET` 齐全；
3. 本机装了 `ossutil`，且 `~/.ossutilconfig` 有可用的鉴权配置。

缺任何一项都只会让"这条消息不带 URL"，不影响收发；日志里有一行
`[OSS] 上传失败（本条消息不带 URL）`。

---

## 数据库相关

- 默认 SQLite：`<插件目录>/wpp.sqlite3`。确认 `WECHATPRO_DB_BACKEND` 没有被设成
  意外值（拼错会直接报错，不会静默回落）；
- 从旧版升级：原来的 MariaDB 部署必须补 `WECHATPRO_DB_BACKEND=mysql`，否则会连到
  一个空 SQLite（表现为历史全没了）；
- MySQL：`WECHATPRO_DB_HOST` 默认只允许本机；远程必须显式
  `WECHATPRO_DB_ALLOW_REMOTE=1`；连不上时消息收发正常，历史/心流/审计降级；
- 启动日志会打印 schema 漂移检测结果；插件**不会自动改列**；
- 测试库名必须以 `_test` 结尾，否则测试护栏直接拒绝（SQLite 只用临时文件）。

---

## 升级后行为异常

1. 确认 `hermes plugins doctor` 通过；
2. 确认 Python 依赖版本满足 `plugin.yaml` 的上下界；
3. 回滚：把升级前的插件目录备份换回来并重启；
4. 报告问题时附上：Hermes 版本、`--check --json` 输出（它不含密钥）、相关日志片段。

---

## 收集诊断信息

```bash
hermes --version
python3 "$HERMES_HOME/plugins/wpp-cloud-platform/setup_wizard.py" --check --json
hermes plugins doctor "$HERMES_HOME/plugins/wpp-cloud-platform"
journalctl --user -u hermes-gateway -n 200 --no-pager > /tmp/hermes-gateway.log
```

发送日志前先自行检查是否包含 wxid、群名、URL 等隐私信息。
