#!/usr/bin/env bash
# MediAgent 一键启动（macOS / Linux）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3.11+" >&2
  exit 1
fi

VERSION="$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
if [ "$(printf '%s\n' "3.11" "$VERSION" | sort -V | head -n1)" != "3.11" ]; then
  echo "需要 Python 3.11 及以上（当前 $VERSION）。LangGraph 的异步 interrupt() 依赖 3.11+。" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "创建虚拟环境 .venv ..."
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate

echo "安装后端依赖 ..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "启动后端 FastAPI (8000) ..."
uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

if command -v npm >/dev/null 2>&1; then
  cd frontend
  [ -d node_modules ] || { echo "安装前端依赖 ..."; npm install --no-audit --no-fund; }
  echo "启动前端 Vite (5173) ..."
  npm run dev
else
  echo "未检测到 npm，仅启动后端：http://127.0.0.1:8000/docs"
  wait $BACKEND_PID
fi
