#!/usr/bin/env bash
# Install pinned project dependencies. Database creation requires --init-local explicitly.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PATH="$HOME/.local/share/wordmachine-tools/node/bin:$HOME/.local/bin:$PATH"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--init-local' ) ]]; then
  printf '%s\n' '用法：./setup.sh [--init-local]；后者仅初始化全新的私有本地开发库。' >&2
  exit 2
fi
if [[ $(id -u) -eq 0 ]]; then
  printf '%s\n' '请使用普通用户运行，不要 sudo。' >&2
  exit 1
fi
if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  printf '%s\n' '需要 Node ^22.18.0 或 >=24.12.0（含 npm）；环境要求与本地启动说明见 README.md。' >&2
  exit 1
fi
node -e 'const [a,b] = process.versions.node.split(".").map(Number); if (!((a===22 && b>=18) || a>24 || (a===24 && b>=12))) { console.error("Node 版本不支持，需要 ^22.18.0 或 >=24.12.0"); process.exit(1) }'
if [[ ! -e .venv ]]; then
  if command -v uv >/dev/null; then
    uv venv --python 3.11 .venv
  else
    python=$(command -v python3.11 || command -v python3 || true)
    if [[ -z "$python" ]] || ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
      printf '%s\n' '需要 Python 3.10+（推荐 3.11），或在用户目录安装 uv 后重试。' >&2
      exit 1
    fi
    "$python" -m venv .venv
  fi
fi
.venv/bin/python -c 'import sys; sys.exit("项目 .venv 需要 Python 3.10+，不会自动覆盖旧环境") if sys.version_info < (3, 10) else None'
# Full workspace includes tests; a runtime-only export can omit requirements-dev.txt.
requirements=requirements.txt
[[ ! -f requirements-dev.txt ]] || requirements=requirements-dev.txt
if command -v uv >/dev/null; then
  uv pip install --python .venv/bin/python -r "$requirements"
  uv pip check --python .venv/bin/python
else
  .venv/bin/python -m pip install -r "$requirements"
  .venv/bin/python -m pip check
fi
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
if [[ "${1:-}" == '--init-local' ]]; then
  .venv/bin/python -m scripts.local_dev --init
fi
printf '%s\n' '依赖及前端构建已准备好。已有本地实例用 ./start.sh；新实例需显式 ./setup.sh --init-local。'
