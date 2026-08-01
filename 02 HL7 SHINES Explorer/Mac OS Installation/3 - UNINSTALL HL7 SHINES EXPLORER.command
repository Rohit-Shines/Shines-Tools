#!/bin/zsh
set -u
APP="$HOME/Applications/HL7 SHINES Explorer.app"
PREFS="$HOME/Library/Application Support/HL7 Shines"

/bin/rm -rf "$APP"
/bin/rm -rf "$PREFS"
/usr/bin/osascript -e 'display dialog "HL7 SHINES Explorer was removed from this Mac." with title "Uninstall Complete" buttons {"OK"} default button "OK"' >/dev/null 2>&1 || true
echo "HL7 SHINES Explorer was removed."
