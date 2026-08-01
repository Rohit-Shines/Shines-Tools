#!/bin/zsh
set -uo pipefail

APP_NAME="HL7 SHINES Explorer"
VERSION="1.2.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FILES_DIR="$SCRIPT_DIR/App Files - Do Not Delete"
DEST_DIR="$HOME/Applications"
DEST_APP="$DEST_DIR/$APP_NAME.app"
PYTHON_URL="https://www.python.org/ftp/python/3.12.9/python-3.12.9-macos11.pkg"
PYTHON_DEFAULT="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"

show_dialog() {
  local message="$1"
  /usr/bin/osascript - "$APP_NAME Installer" "$message" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  display dialog (item 2 of argv) with title (item 1 of argv) buttons {"OK"} default button "OK"
end run
APPLESCRIPT
}

fail() {
  local message="$1"
  echo ""
  echo "INSTALLATION FAILED: $message"
  show_dialog "Installation failed: $message"
  echo ""
  echo "Press Return to close this window."
  read -r _
  exit 1
}

is_apple_silicon() {
  if [[ "$(/usr/bin/uname -m)" == "arm64" ]]; then
    return 0
  fi

  # Terminal may itself be running through Rosetta and report x86_64.
  # This hardware check still correctly detects an M1/M2/M3/M4 Mac.
  local arm_support
  arm_support="$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || /bin/echo 0)"
  [[ "$arm_support" == "1" ]]
}

find_python() {
  local candidates=(
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "/usr/bin/python3"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      /bin/echo "$candidate"
      return 0
    fi
  done
  return 1
}

install_python() {
  local pkg="$TMPDIR/python-3.12.9-macos11.pkg"

  echo "A compatible Python runtime was not found."
  echo "Downloading the official Python runtime..."
  /usr/bin/curl --fail --location --retry 3 --progress-bar "$PYTHON_URL" -o "$pkg" || \
    fail "Could not download the Python runtime. Check the internet connection and try again."

  echo "Checking the Python installer signature..."
  local signature
  signature="$(/usr/sbin/pkgutil --check-signature "$pkg" 2>&1 || true)"
  echo "$signature"
  echo "$signature" | /usr/bin/grep -q "Python Software Foundation" || \
    fail "The downloaded Python installer signature could not be verified."

  echo "Installing the Python runtime. macOS may request an administrator password..."
  /usr/bin/osascript - "$pkg" <<'APPLESCRIPT'
on run argv
  set pkgPath to item 1 of argv
  do shell script "/usr/sbin/installer -pkg " & quoted form of pkgPath & " -target /" with administrator privileges
end run
APPLESCRIPT
  [[ $? -eq 0 ]] || fail "Python installation was cancelled or failed."
  [[ -x "$PYTHON_DEFAULT" ]] || fail "Python installation did not complete correctly."
  /bin/rm -f "$pkg"
}

echo "========================================================"
echo "       HL7 SHINES EXPLORER $VERSION - INSTALLER"
echo "========================================================"
echo ""

[[ -d "$FILES_DIR" ]] || fail "The App Files folder is missing. Keep all package files together."
/bin/mkdir -p "$DEST_DIR" || fail "Could not create $DEST_DIR."

# Stop any previously launched copy and remove the old installation.
/usr/bin/pkill -f "$DEST_APP/Contents/MacOS" >/dev/null 2>&1 || true
/bin/rm -rf "$DEST_APP"

if is_apple_silicon && [[ -d "$FILES_DIR/Apple Silicon/$APP_NAME.app" ]]; then
  echo "Apple Silicon Mac detected."
  echo "Installing the included native application (Python is not required)..."
  SOURCE_APP="$FILES_DIR/Apple Silicon/$APP_NAME.app"
  /usr/bin/ditto --rsrc --extattr "$SOURCE_APP" "$DEST_APP" || fail "Could not copy the native application."

  [[ -x "$DEST_APP/Contents/MacOS/HL7Shines" ]] || fail "The native application executable is missing."
else
  echo "Intel Mac detected."
  echo "Installing the universal Python-based application..."

  PYTHON_BIN="$(find_python || true)"
  if [[ -z "$PYTHON_BIN" ]]; then
    install_python
    PYTHON_BIN="$PYTHON_DEFAULT"
  fi

  SOURCE_APP="$FILES_DIR/Universal Template/$APP_NAME.app"
  [[ -d "$SOURCE_APP" ]] || fail "The universal application template is missing."
  /usr/bin/ditto --rsrc --extattr "$SOURCE_APP" "$DEST_APP" || fail "Could not copy the universal application."

  PYTHON_PATH_FILE="$DEST_APP/Contents/Resources/python-path.txt"
  /usr/bin/printf '%s\n' "$PYTHON_BIN" > "$PYTHON_PATH_FILE" || fail "Could not save the Python runtime path."
  /bin/chmod 644 "$PYTHON_PATH_FILE" 2>/dev/null || true

  [[ -s "$PYTHON_PATH_FILE" ]] || fail "The Python runtime path file was not created."
  [[ "$(/bin/cat "$PYTHON_PATH_FILE")" == "$PYTHON_BIN" ]] || fail "The Python runtime path could not be verified."

  PYTHONPATH="$DEST_APP/Contents/Resources/app/src" "$PYTHON_BIN" -c 'import hl7_shines.app' >/dev/null 2>&1 || \
    fail "The installed application source could not be loaded."
fi

/bin/chmod +x "$DEST_APP/Contents/MacOS/"* 2>/dev/null || true
/usr/bin/xattr -dr com.apple.quarantine "$DEST_APP" 2>/dev/null || true
/usr/bin/codesign --force --deep --sign - "$DEST_APP" >/dev/null 2>&1 || true

# Refresh the app registration, then open the exact newly installed copy.
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "$LSREGISTER" ]]; then
  "$LSREGISTER" -f "$DEST_APP" >/dev/null 2>&1 || true
fi

echo "Opening $APP_NAME..."
/usr/bin/open -n "$DEST_APP" || fail "The application was installed but could not be opened."

echo ""
echo "Installation complete."
echo "Installed at: $DEST_APP"
show_dialog "$APP_NAME $VERSION was installed successfully in your Applications folder."
