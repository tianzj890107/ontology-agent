#!/usr/bin/env bash
set -euo pipefail

# One process-wide Python environment is shared by 47313, 47314 and every
# sandboxed Agent command. Run workspaces must never create their own venv or
# install packages; they only receive a read-only view of this environment.
repo_root="${ONTOLOGY_AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
shared_venv="${ONTOLOGY_AGENT_SHARED_VENV:-$repo_root/.venv}"
python_bin="$shared_venv/bin/python"
lock_dir="$(dirname "$shared_venv")/.ontology-agent-venv.lock"
stamp="$shared_venv/.ontology-agent-deps.sha256"

mkdir -p "$(dirname "$shared_venv")"
while ! mkdir "$lock_dir" 2>/dev/null; do
  sleep 0.2
done
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT

if [ ! -x "$python_bin" ]; then
  bootstrap_python="${ONTOLOGY_AGENT_BOOTSTRAP_PYTHON:-$(command -v python3 || command -v python || true)}"
  if [ -z "$bootstrap_python" ]; then
    echo "找不到可用于创建共享 Agent venv 的 Python。" >&2
    exit 1
  fi
  "$bootstrap_python" -m venv "$shared_venv"
fi

if [ ! -x "$python_bin" ]; then
  echo "共享 Agent venv 创建失败：$python_bin" >&2
  exit 1
fi

fingerprint="$("$python_bin" -c 'import hashlib,pathlib,sys; root=pathlib.Path(sys.argv[1]); h=hashlib.sha256(); paths=[root/"open-claude"/"pyproject.toml",root/"open-claude"/"open_claude"/"requirements.txt"]+sorted((root/"open-claude"/"open_claude").rglob("*.py")); [h.update(str(p).encode()+p.read_bytes()) for p in paths if p.exists()]; print(h.hexdigest())' "$repo_root")"
needs_install=1
if [ -s "$stamp" ] && [ "$(cat "$stamp")" = "$fingerprint" ]; then
  needs_install=0
fi

if [ "$needs_install" -eq 1 ]; then
  # Install as a normal wheel, not editable: bubblewrap exposes the shared
  # venv but deliberately does not expose the repository source.
  "$python_bin" -m pip install --quiet --disable-pip-version-check \
    --no-deps --force-reinstall "$repo_root/open-claude"
  "$python_bin" -m pip install --quiet --disable-pip-version-check \
    -r "$repo_root/open-claude/open_claude/requirements.txt"
  printf '%s\n' "$fingerprint" > "$stamp"
  chmod 600 "$stamp"
fi

printf '%s\n' "$shared_venv"
