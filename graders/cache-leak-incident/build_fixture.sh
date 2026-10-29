#!/bin/bash
# Rebuild repos/conduit-incident: the base Conduit monorepo, plus the 1.8.0 response-cache
# change (overlay/), plus two days of generated production logs. Rerun after changing the base
# repo, the overlay or make_logs.py, then bump C13's version (content changed).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$ROOT/repos/conduit-incident"
rm -rf "$OUT"
cp -R "$ROOT/repos/conduit-monorepo" "$OUT"
rm -rf "$OUT/node_modules"
cp -R "$HERE/overlay/." "$OUT/"
python3 "$HERE/make_logs.py" "$OUT/incident/logs" "$HERE/ground_truth.json"
