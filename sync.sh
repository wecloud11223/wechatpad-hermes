#!/usr/bin/env bash
# wpp-cloud-platform 代码同步（不碰服务生命周期）。
#
#   bash sync.sh              # dev/plugin -> ~/.hermes/plugins/wpp-cloud-platform
#   bash sync.sh --check      # 只比较差异，不写
#
# accounts/ 与 data/ 是生产运行数据，永远不参与同步/删除。
set -euo pipefail

DEV="$(cd "$(dirname "$0")" && pwd)"
H="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DEPLOY="$H/plugins/wpp-cloud-platform"
MODE=sync
[[ "${1:-}" == "--check" ]] && MODE=check

if [[ "$PLUGIN_DEPLOY" == "$H/plugins/wechatpadpro" ]]; then
    echo "❌ 目标目录与原插件相同，拒绝同步" >&2
    exit 1
fi

RSYNC=(rsync -a --delete
    --exclude 'accounts/'
    # 2026-11-14 修：原先 `--exclude 'data/'` 把**代码包** plugin/data/ 整个挡在同步外
    # （schema.sql / repo_hf.py 改完永远同步不过去，v3.1.4 部署时踩实）。
    # 真正该保的是**运行数据**（sqlite/快照类文件），按文件型排除。
    --exclude '*.db' --exclude '*.db-*' --exclude '*.sqlite*' --exclude '*.sqlite3*'
    --exclude 'data/*.json'
    --exclude '__pycache__/'
    --exclude '*.pyc'
    --exclude '.pytest_cache/'
    --exclude 'tests/'
)

if [[ "$MODE" == check ]]; then
    "${RSYNC[@]}" --dry-run --itemize-changes "$DEV/plugin/" "$PLUGIN_DEPLOY/" || true
    exit 0
fi

mkdir -p "$PLUGIN_DEPLOY"
"${RSYNC[@]}" "$DEV/plugin/" "$PLUGIN_DEPLOY/"
python3 -m compileall -q "$PLUGIN_DEPLOY" >/dev/null
echo "✅ 已同步到 $PLUGIN_DEPLOY（accounts/ 与 data/ 保留）"
echo "   重启后生效（在外层 shell 重启网关，见 README）"
