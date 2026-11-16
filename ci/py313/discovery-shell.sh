#!/usr/bin/env bash
# Enter the course-discovery Python 3.13 runtime container with the correct
# settings identity, DB password, and (optional) platform-LMS interop env.
#
# Usage:  ./ci/py313/discovery-shell.sh
# Mirror of platform's ops/lms-shell.sh / cms-shell.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer `uv run` (same as platform py313), fall back to system python3.
if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project --python 3.13 python -B "$SCRIPT_DIR/ops_discovery.py" shell
else
  exec python3 -B "$SCRIPT_DIR/ops_discovery.py" shell
fi
