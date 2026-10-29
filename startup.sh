#!/usr/bin/env bash
set -euo pipefail

export FOLEYGRAPH_DATA_DIR="${FOLEYGRAPH_DATA_DIR:-/home/foleygraph}"
exec python -m uvicorn server.main:app \
  --host 0.0.0.0 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips='*'
