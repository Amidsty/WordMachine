#!/usr/bin/env bash
# Persistent, loopback-only LOCAL development instance; never loads a business .env.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PATH="$HOME/.local/share/wordmachine-tools/node/bin:$HOME/.local/bin:$PATH"
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' '缺少项目 Python 环境，请先运行 ./setup.sh --init-local' >&2
  exit 1
fi
exec .venv/bin/python -m scripts.local_dev "$@"
