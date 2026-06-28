#!/usr/bin/env bash
set -euo pipefail
SKILL_SRC="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.claude/skills/plutus-document"
mkdir -p "$HOME/.claude/skills"
if [[ -L "$TARGET" ]]; then
  echo "symlink already exists: $TARGET -> $(readlink "$TARGET")"
elif [[ -e "$TARGET" ]]; then
  echo "ERROR: $TARGET exists but is not a symlink. Refusing to overwrite." >&2
  exit 1
else
  ln -s "$SKILL_SRC" "$TARGET"
  echo "installed: $TARGET -> $SKILL_SRC"
fi
