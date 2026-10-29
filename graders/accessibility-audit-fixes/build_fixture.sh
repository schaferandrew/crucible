#!/bin/bash
# Rebuild repos/conduit-a11y: the base Conduit monorepo plus components with the accessibility
# problems the audit (docs/accessibility-audit.md) describes. Rerun after changing the base repo
# or the overlay, then bump C15's version (content changed).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
OUT="$ROOT/repos/conduit-a11y"
rm -rf "$OUT"
cp -R "$ROOT/repos/conduit-monorepo" "$OUT"
rm -rf "$OUT/node_modules"
cp -R "$HERE/overlay/." "$OUT/"
