#!/usr/bin/env bash
set -euo pipefail

# exec keeps agent cancellation attached to the supervisor. Python's stdlib handles
# JSON, timestamp cursors and bounded pipe reads without jq or new dependencies.
exec python3 "$(dirname "${BASH_SOURCE[0]}")/collect_cl2_logs.py" "$@"
