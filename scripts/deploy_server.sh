#!/usr/bin/env bash
set -euo pipefail

deploy_root="${ONTOLOGY_AGENT_ROOT:-/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent}"
deploy_branch="${ONTOLOGY_AGENT_BRANCH:-20260727}"
deploy_port="${ONTOLOGY_AGENT_PORT:-47313}"

cd "$deploy_root"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "部署目录不是 Git 工作区，请先按 DEPLOYMENT.md 完成一次性初始化。" >&2
  exit 1
fi

if [ "$(git branch --show-current)" != "$deploy_branch" ]; then
  echo "当前分支不是 $deploy_branch，拒绝部署。" >&2
  exit 1
fi

git fetch origin "$deploy_branch"
git pull --ff-only origin "$deploy_branch"

if [ ! -x .venv/bin/python ]; then
  echo "缺少服务器虚拟环境 .venv/bin/python，拒绝覆盖服务器环境。" >&2
  exit 1
fi

.venv/bin/python -m pip install -e open-claude >/dev/null
.venv/bin/python -m unittest tests.test_ontology_knowledge tests.test_frontend_contract
.venv/bin/python -m py_compile open-claude/oc_codex_server.py

mapfile -t old_pids < <(pgrep -f "[o]c_codex_server.py.*--port ${deploy_port}" || true)
if [ "${#old_pids[@]}" -gt 0 ]; then
  kill "${old_pids[@]}"
  for _ in $(seq 1 30); do
    if ! kill -0 "${old_pids[@]}" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
fi

nohup .venv/bin/python open-claude/oc_codex_server.py \
  --host 0.0.0.0 --port "$deploy_port" \
  >"ontology-agent-${deploy_port}.log" 2>&1 </dev/null &
new_pid=$!

for _ in $(seq 1 40); do
  if curl --fail --silent --show-error "http://127.0.0.1:${deploy_port}/" >/dev/null; then
    echo "部署成功 branch=${deploy_branch} commit=$(git rev-parse --short HEAD) pid=${new_pid} port=${deploy_port}"
    exit 0
  fi
  if ! kill -0 "$new_pid" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

echo "服务启动或健康检查失败，最近日志如下：" >&2
tail -80 "ontology-agent-${deploy_port}.log" >&2 || true
exit 1
