#!/usr/bin/env bash
# Double-click this file in Finder on macOS to start Invoice Studio.
# It opens Terminal, runs start.sh from the same folder, and keeps the window
# open so you can read the result.
cd "$(dirname "$0")"
./start.sh
status=$?
echo ""
if [ "$status" -ne 0 ]; then
    echo "Start failed (exit code $status). See docs/MAC_SETUP.md, section Troubleshooting."
fi
echo "You can close this window."
read -r -p "Press Return to close." _ || true
exit "$status"
