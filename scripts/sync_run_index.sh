#!/usr/bin/env bash
# 提交并推送 47314 run 索引库当前快照（服务器端使用）。
# 索引库（.runs.sqlite3 / .runs.json）已纳入版本管理；服务持续写库期间，
# 定期执行本脚本把最新快照落入 git，误删后可恢复，也便于部署 pull 前工作区整洁。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

index_paths=(
  open-claude/sandbox/standalone-modeling-runs/.runs.sqlite3
  open-claude/sandbox/standalone-modeling-runs/.runs.json
)

if ! git diff --quiet -- "${index_paths[@]}"; then
  git add -- "${index_paths[@]}"
  git commit -m "chore(runs): snapshot run index (server $(hostname))"
  git push origin "$(git rev-parse --abbrev-ref HEAD)"
  echo "run index snapshot committed and pushed."
else
  echo "run index unchanged; nothing to do."
fi
