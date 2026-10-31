# AGENTS.md — 仓库约定（给所有 AI agent / 协作者）

本仓库是 **wpp-cloud-platform**（Hermes 平台的 WPP Cloud 插件）的唯一事实来源。

- 本地路径（示例）：`~/dev/wpp-hermes-cloud`
- GitHub：<https://github.com/wecloud11223/wechatpad-hermes>（默认分支 `main`）
- 插件名/平台名：`wpp-cloud-platform` / `wechatpadpro`（**平台名不得改**：工具、配置键、
  cron 投递变量都依赖它）

## 🔁 git 自动同步（本仓库已配置，任何人/agent 修改都会自动进 GitHub）

三条链路叠在一起，任意一条生效即可同步：

| 链路 | 触发时机 | 命令/位置 |
| --- | --- | --- |
| **手动（推荐）** | 改完就提交 | `bash scripts/git-autosync.sh` |
| **post-commit hook** | `git commit` 成功后自动 `push` | `scripts/git-hooks/post-commit`（后台推送，不阻塞） |
| **systemd timer 兜底** | 每 5 分钟 | `scripts/systemd/wpp-git-autosync.timer` → 逐仓库跑 `scripts/git-autosync.sh` |

- `git-autosync.sh` **幂等**：没有改动什么都不做；有改动才 `git add -A` → 敏感扫描 →
  提交（`chore(autosync): <时间>`）→ 推送。
- 推送失败不会丢改动：提交留在本地，下一轮重试；日志见 `.git/autosync-push.log`。
- 新机器/新克隆装一次即可：

  ```bash
  bash scripts/install-git-hooks.sh          # pre-commit 扫描 + post-commit 推送
  sudo bash scripts/install-autosync-timer.sh # 5 分钟兜底 timer（可选但建议）
  ```

- SSH 走专名 Host（不干扰本机其他 GitHub 账号）：

  ```
  Host github-wecloud11223
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_github
    IdentitiesOnly yes
  ```

  远端地址形如 `git@github-wecloud11223:wecloud11223/wechatpad-hermes.git`。

## 🧪 CI 说明

| job | 跑什么 | 说明 |
| --- | --- | --- |
| `static` | ruff + `compileall` + `scripts/check_public_tree.py` | 公开 runner 上恒绿，任何 PR 都跑 |
| `tests` | `pytest plugin/tests` | **需要 Hermes 运行时**（`gateway` 包）。默认跳过（`HERMES_RUNTIME` 未设）；启用方式：在装了 Hermes 的 self-hosted runner 上把仓库变量 `HERMES_RUNTIME` 设为 `true` |

完整业务用例在别人机器上跑不起来是**环境缺件**，不是代码坏了——本地跑法见
`CONTRIBUTING.md` 的「测试约定」。新增用例请保持"只依赖标准库 + dev 依赖"，
别把 CI 静态 job 也拖进 Hermes 依赖里。

## 🚫 铁律

1. **不要在部署副本里改代码**：生产副本 `~/.hermes/plugins/wpp-cloud-platform/` 是
   `deploy.sh` 的确定性产物；改动只落本仓库，再用 `bash deploy.sh --local --restart` 同步。
2. **不提交凭证**：`plugin/accounts/*.json`（含 authcode）、`.env`、`data/`、
   `public_tree_denylist.txt`、`CONFTEST_LOCAL` 一律在 `.gitignore` 里；只放行
   `*.example.json` 与 `.env.example`（内容必须是占位值）。
3. **公开仓**：本仓库内容会公开。真实 wxid / 群号 / 网关令牌（`wxa_...`）/ 厂商域名 /
   内网地址 / 本机绝对路径都不许出现。`scripts/check_public_tree.py` 会拦截，pre-commit
   hook 也会跑它。
4. **改行为必须带测试**：`plugin/tests/` 覆盖每个语义分支；行为变更请同步
   `CHANGELOG.md` 与 `docs/`。
5. 注册期只用标准库（`plugin/toolkit/`、`plugin/registration.py` 模块级不得 import
   `aiohttp`/`websockets`/`pymysql`，需要时函数体内延迟导入）。

## ✅ 提交前自检

```bash
ruff check plugin tools      # 或 ~/.local/bin/ruff
PYTHONPATH=~/.hermes/hermes-agent:/tmp/hermes-test-deps python3 -m pytest plugin/tests -q
python3 scripts/check_public_tree.py
```

或一次跑完：`bash scripts/check.sh`。

依赖说明：Hermes 核心包需在 `PYTHONPATH`（`~/.hermes/hermes-agent`）；测试
额外需要 `ruamel.yaml` + `pytest-asyncio` + `fastapi` + `httpx`（本机装在
`/tmp/hermes-test-deps`）。

## 📝 提交信息

Conventional Commits + 中文摘要（一个提交只做一件事）：

```
feat(platform): 兜底派发失败时游标不前进
fix(core): 写端点 408/429/503 重试一次并尊重 Retry-After
docs: 补充 diagnostics webhook_url 用法
```

## 分支与发布

- 只在 `main` 上开发；`git-autosync.sh` 只推当前分支，不要长期留在 feature 分支上工作。
- 版本号两处同步：`plugin/plugin.yaml` 与 `pyproject.toml`；`plugin/dashboard/manifest.json`
  是控制台 UI 自己的版本，按需单独 bump。
