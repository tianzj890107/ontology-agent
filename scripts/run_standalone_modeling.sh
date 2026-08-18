#!/usr/bin/env bash
set -euo pipefail

repo_root="${ONTOLOGY_AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
port="${MODELING_SERVER_PORT:-47314}"
host="${MODELING_SERVER_HOST:-0.0.0.0}"
max_active_runs="${MODELING_SERVER_MAX_ACTIVE_RUNS:-10}"
max_active_per_user="${MODELING_SERVER_MAX_ACTIVE_PER_USER:-3}"
max_queued_per_user="${MODELING_SERVER_MAX_QUEUED_PER_USER:-3}"
max_queued_runs="${MODELING_SERVER_MAX_QUEUED:-50}"
run_root="${MODELING_SERVER_ROOT:-$repo_root/open-claude/sandbox/standalone-modeling-runs}"
key_file="${MODELING_SERVER_KEY_FILE:-$repo_root/.standalone-modeling-api-key}"

cd "$repo_root"

if [ ! -x .venv/bin/python ]; then
  echo "缺少 .venv/bin/python，无法启动独立建模服务。" >&2
  exit 1
fi

if [ ! -s "$key_file" ]; then
  umask 077
  .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))' > "$key_file"
  chmod 600 "$key_file"
fi

export ONTOLOGY_STANDALONE_API_KEY="$(tr -d '\r\n' < "$key_file")"
mkdir -p "$run_root"

exec .venv/bin/python open-claude/standalone_modeling_server.py \
  --host "$host" --port "$port" --root "$run_root" \
  --max-active-runs "$max_active_runs" \
  --max-active-per-user "$max_active_per_user" \
  --max-queued-per-user "$max_queued_per_user" \
  --max-queued-runs "$max_queued_runs"
