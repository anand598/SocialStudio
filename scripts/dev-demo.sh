#!/usr/bin/env bash
set -euo pipefail
export GENERATION_MODE=demo
exec "$(cd "$(dirname "$0")" && pwd)/dev-local.sh"
