#!/usr/bin/env bash
set -euo pipefail

app_dirs=(/Applications "$HOME/Applications")
existing_dirs=()
for dir in "${app_dirs[@]}"; do
  [[ -d "$dir" ]] && existing_dirs+=("$dir")
done

echo "SAP-named .app bundles:"
if ((${#existing_dirs[@]})); then
  find "${existing_dirs[@]}" -type d -name '*.app' -prune -print 2>/dev/null \
    | awk -F/ 'tolower($NF) ~ /sap/ { print }'
fi

echo
echo "Visible running GUI process names (System Events):"
if ! osascript -e 'tell application "System Events" to get name of every process whose background only is false'; then
  echo "Could not query System Events. Grant Terminal permission to control System Events and retry." >&2
  exit 1
fi
