#!/usr/bin/env bash
# Two-pass build that produces a wheel WITH a copy of itself bundled inside
# `plutus_verify/_bundled/`. Run before any PyPI release or before producing
# a wheel that downstream Plutus repos will use via `plutus check`.
#
# After this script, `dist/plutus_verify-X.Y.Z-py3-none-any.whl` contains
# `plutus_verify/_bundled/plutus_verify-X.Y.Z-py3-none-any.whl`. The
# runtime helper `ensure_plutus_wheel` finds the bundled wheel via
# `importlib.resources` and stages it into the Docker build context.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
BUNDLED_DIR="$ROOT/plutus_verify/_bundled"
DIST_DIR="$ROOT/dist"

# Pass 1: clean state, build the inner wheel.
echo "Pass 1: building wheel with empty _bundled/ ..."
rm -rf "$DIST_DIR"
find "$BUNDLED_DIR" -name '*.whl' -delete 2>/dev/null || true
python -m build --wheel

# Capture pass-1 wheel.
INNER_WHEEL=$(ls "$DIST_DIR"/plutus_verify-*-py3-none-any.whl)
echo "Pass 1 produced: $(basename "$INNER_WHEEL")"

# Stage it inside the source tree for pass 2.
cp "$INNER_WHEEL" "$BUNDLED_DIR/"

# Pass 2: rebuild with the wheel staged inside _bundled/.
echo "Pass 2: rebuilding wheel with _bundled/ populated ..."
rm -rf "$DIST_DIR"
python -m build --wheel

OUTER_WHEEL=$(ls "$DIST_DIR"/plutus_verify-*-py3-none-any.whl)
echo "Pass 2 produced: $(basename "$OUTER_WHEEL")"
echo ""
echo "Final wheel: $OUTER_WHEEL"
echo "Contains bundled: $(unzip -l "$OUTER_WHEEL" | grep _bundled || echo 'NONE -- bug!')"

# Clean up the staging area so dev iteration doesn't keep stale state.
find "$BUNDLED_DIR" -name '*.whl' -delete 2>/dev/null || true
echo ""
echo "Cleaned _bundled/ for dev iteration. The wheel at $OUTER_WHEEL is the artifact to ship."
