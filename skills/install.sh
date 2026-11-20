#!/usr/bin/env bash
# Install the skills in this folder for the current user.
#
#   ./install.sh          symlink into ~/.claude/skills (recommended: edits here
#                         are picked up immediately)
#   ./install.sh --copy   copy instead of symlink
#
# Idempotent: re-running replaces previous installs.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${SKILLS_TARGET:-$HOME/.claude/skills}"
MODE="link"

for arg in "$@"; do
  case "$arg" in
    --copy) MODE="copy" ;;
    -h|--help)
      sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$TARGET"

count=0
for dir in "$HERE"/*/; do
  name="$(basename "$dir")"
  [ -f "$dir/SKILL.md" ] || continue

  dest="$TARGET/$name"
  rm -rf "$dest"

  if [ "$MODE" = "copy" ]; then
    cp -R "$dir" "$dest"
  else
    ln -s "$dir" "$dest"
  fi

  echo "  installed $name -> $dest"
  count=$((count + 1))
done

echo
echo "$count skill(s) installed into $TARGET ($MODE)"

# Validate if the reference tool is available.
if command -v skills-ref >/dev/null 2>&1; then
  echo
  echo "Validating..."
  fail=0
  for dir in "$HERE"/*/; do
    [ -f "$dir/SKILL.md" ] || continue
    if ! skills-ref validate "$dir" >/dev/null 2>&1; then
      echo "  INVALID: $dir" >&2
      skills-ref validate "$dir" >&2 || true
      fail=1
    fi
  done
  [ "$fail" -eq 0 ] && echo "  all valid"
else
  echo
  echo "skills-ref not installed; skipping validation."
  echo "  pip install -e <path-to>/agentskills/skills-ref"
fi
