#!/usr/bin/env bash
# Start the course-discovery Python 3.13 local environment (containers + runserver).
# Mirrors platform's `ops/ops.py up`.
#
# Usage:  ./ci/py313/start-discovery.sh
# Optional interop (platform LMS): export DISCOVERY_LMS_JWT_SECRET=... before running.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project --python 3.13 python -B "$SCRIPT_DIR/ops_discovery.py" up
else
  exec python3 -B "$SCRIPT_DIR/ops_discovery.py" up
fi
