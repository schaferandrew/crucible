#!/bin/bash
# Rebuild repos/conduit-invites: the base Conduit monorepo plus the contributor-invites feature
# (overlay/), which ships the redirect loop. Rerun after changing the base repo or the overlay,
# then bump the task's version (content changed).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$ROOT/repos/conduit-invites"
rm -rf "$OUT"
cp -R "$ROOT/repos/conduit-monorepo" "$OUT"
rm -rf "$OUT/node_modules"
cp -R "$HERE/overlay/." "$OUT/"
