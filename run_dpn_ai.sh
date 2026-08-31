#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ -x .venv/bin/python ]] || ./install_linux.sh
source .venv/bin/activate
if ! ollama list >/dev/null 2>&1; then
  nohup ollama serve >data/ollama.log 2>&1 &
  sleep 3
fi
python launch.py