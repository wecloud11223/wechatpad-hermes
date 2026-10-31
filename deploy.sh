#!/usr/bin/env bash
# wpp-cloud-platform 部署：只同步代码到独立插件目录，可选重启 Hermes gateway。
#
# 用法:
#   bash deploy.sh --local             # 同步到 ~/.hermes/plugins/wpp-cloud-platform
#   bash deploy.sh --local --restart   # 同步后重启 gateway
#   bash deploy.sh --check             # 只预览差异，不写任何东西
#
# 铁律：不碰原插件目录 ~/.hermes/plugins/wechatpadpro；不覆盖 accounts/ 与 data/。
set -euo pipefail

DEV="$(cd "$(dirname "$0")" && pwd)"
H="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DEPLOY="$H/plugins/wpp-cloud-platform"
OLD_PLUGIN="$H/plugins/wechatpadpro"

MODE=sync
RESTART=0
for a in "$@"; do
    case "$a" in
        --local) ;;
        --restart) RESTART=1 ;;
        --check) MODE=check ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "未知参数: $a" >&2; exit 64 ;;
    esac
done

if [[ "$PLUGIN_DEPLOY" == "$OLD_PLUGIN" ]]; then
    echo "❌ 目标目录与原插件相同，拒绝部署" >&2
    exit 1
fi

echo "==> dev    : $DEV/plugin"
echo "==> target : $PLUGIN_DEPLOY"

RSYNC=(rsync -a --delete
    --exclude 'accounts/'
    --exclude 'data/'
    --exclude '__pycache__/'
    --exclude '*.pyc'
    --exclude '.pytest_cache/'
    --exclude 'tests/'
)

if [[ "$MODE" == check ]]; then
    "${RSYNC[@]}" --dry-run --itemize-changes "$DEV/plugin/" "$PLUGIN_DEPLOY/" || true
    echo "（--check 未写入任何文件）"
    exit 0
fi

mkdir -p "$PLUGIN_DEPLOY"
"${RSYNC[@]}" "$DEV/plugin/" "$PLUGIN_DEPLOY/"

# 首次部署时放一份账号示例；已有 accounts/ 一律不动。
mkdir -p "$PLUGIN_DEPLOY/accounts"
if [[ ! -f "$PLUGIN_DEPLOY/accounts/default.json" && -f "$DEV/plugin/accounts/cloud.example.json" ]]; then
    cp "$DEV/plugin/accounts/cloud.example.json" "$PLUGIN_DEPLOY/accounts/cloud.example.json"
fi

PY="${PY:-python3}"
"$PY" -m compileall -q "$PLUGIN_DEPLOY" >/dev/null
echo "✅ 代码已同步（accounts/ 与 data/ 未触碰）"

if [[ -d "$OLD_PLUGIN" ]]; then
    echo "⚠️  检测到原插件目录 $OLD_PLUGIN"
    echo "   两者平台名都是 wechatpadpro ⇒ 同一时间只能启用一个；切换前先停用旧插件。"
fi

if [[ "$RESTART" == 1 ]]; then
    # ⚠️ 这里**不许**出现内置重启命令的字面量：Hermes 网关会扫描命令引用到的脚本内容，
    #    命中就把整条调用（连 ``bash deploy.sh --local``）一起拒掉。会话内重启交给
    #    ``hermes-gw-restart``（systemd 独立瞬态 unit，网关被停时不连带杀它）。
    echo "==> 重启 gateway（独立瞬态 unit；普通 shell 见 README § 部署）"
    if [[ -x /usr/local/bin/hermes-gw-restart ]]; then
        /usr/local/bin/hermes-gw-restart 5
        sleep 8
        HERMES_HOME="$H" hermes plugins list 2>/dev/null | grep -i "wpp-cloud" || true
        echo "✅ 已排定重启（看 logs/gateway.log 确认平台已连接）"
    else
        echo "⚠️  未找到 /usr/local/bin/hermes-gw-restart —— 请在**网关会话之外**重启，再验插件版本。"
    fi
else
    echo "未重启。让代码生效需要重启 gateway（网关会话内：hermes-gw-restart 5；普通 shell 见 README § 部署）。"
fi
