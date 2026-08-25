#!/usr/bin/env bash
set -euo pipefail

# One process-wide Python environment is shared by 47313, 47314 and every
# sandboxed Agent command. Run workspaces must never create their own venv or
# install packages; they only receive a read-only view of this environment.
repo_root="${ONTOLOGY_AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
shared_venv="${ONTOLOGY_AGENT_SHARED_VENV:-$repo_root/.venv}"
python_bin="$shared_venv/bin/python"
# Optional dependency extra (e.g. ``redis`` for
# TASKS_COORDINATOR_BACKEND=redis / MODELING_SERVER_COORDINATOR_BACKEND=redis).
# Installed through the same local wheel so offline deployment only needs the
# extra's wheel in the pip cache; no ad-hoc network install at startup.
venv_extra="${ONTOLOGY_AGENT_VENV_EXTRA:-}"
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

fingerprint="$("$python_bin" -c 'import hashlib,pathlib,sys; root=pathlib.Path(sys.argv[1]); h=hashlib.sha256(); paths=[root/"open-claude"/"pyproject.toml",root/"open-claude"/"open_claude"/"requirements.txt"]+sorted((root/"open-claude"/"open_claude").rglob("*.py")); [h.update(str(p).encode()+p.read_bytes()) for p in paths if p.exists()]; print(h.hexdigest())' "$repo_root")"${venv_extra:+|$venv_extra}
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
  if [ -n "$venv_extra" ]; then
    # ``open-claude[<extra>]`` resolves the extra's requirements (e.g. redis)
    # through the same wheel metadata used by the base install, so the
    # dependency comes from the same wheel/cache source as everything else.
    "$python_bin" -m pip install --quiet --disable-pip-version-check \
      "$repo_root/open-claude[$venv_extra]"
  fi
  printf '%s\n' "$fingerprint" > "$stamp"
  chmod 600 "$stamp"
fi

printf '%s\n' "$shared_venv"
