#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "            DPN AI v5 - STANDALONE LOCAL INSTALLER"
echo "============================================================"

command -v python3 >/dev/null || { echo "Python 3.11+ is required."; exit 1; }
command -v ollama >/dev/null || { echo "Install Ollama from https://ollama.com/download and rerun."; exit 1; }
python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else "DPN AI requires Python 3.11+")
PY

[[ -x .venv/bin/python ]] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r requirements-voice.txt || echo "Voice dependencies failed; the AI core remains available."
[[ -f .env ]] || cp .env.example .env
mkdir -p data workspace/generated workspace/uploads plugins skills

if ! ollama list >/dev/null 2>&1; then
  nohup ollama serve >data/ollama.log 2>&1 &
  sleep 4
fi
ollama pull qwen3.5:9b || echo "Worker model pull failed; retry with: ollama pull qwen3.5:9b"
ollama pull nomic-embed-text || echo "Embedding model pull failed; semantic memory will remain unavailable until installed."
python manage.py install-voices sentinel aurora || echo "Voice model download failed; retry with: .venv/bin/python manage.py install-voices"
python -m compileall app
python manage.py doctor

echo "Installed. Run ./run_dpn_ai.sh"