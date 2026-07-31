#!/bin/zsh
set -u

APP_NAME="HL7 SHINES Explorer"
VERSION="1.2.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FILES_DIR="$SCRIPT_DIR/App Files - Do Not Delete"
DEST_DIR="$HOME/Applications"
DEST_APP="$DEST_DIR/$APP_NAME.app"
PYTHON_URL="https://www.python.org/ftp/python/3.12.9/python-3.12.9-macos11.pkg"
PYTHON_DEFAULT="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"

show_dialog() {
  /usr/bin/osascript -e "display dialog "$1" with title "$APP_NAME Installer" buttons {"OK"} default button "OK"" >/dev/null 2>&1 || true
}

fail() {
  echo ""
  echo "INSTALLATION FAILED: $1"
  show_dialog "Installation failed: $1"
  echo "Press Return to close this window."
  read -r _
  exit 1
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
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

install_python() {
  local pkg="$TMPDIR/python-3.12.9-macos11.pkg"
  echo "A compatible Python runtime was not found."
  echo "Downloading the official Python runtime..."
  /usr/bin/curl --fail --location --retry 3 --progress-bar "$PYTHON_URL" -o "$pkg" || fail "Could not download the Python runtime. Check the internet connection and try again."

  echo "Checking the Python installer signature..."
  local signature
  signature="$(/usr/sbin/pkgutil --check-signature "$pkg" 2>&1 || true)"
  echo "$signature"
  echo "$signature" | /usr/bin/grep -q "Python Software Foundation" || fail "The downloaded Python installer signature could not be verified."

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

ARCH="$(/usr/bin/uname -m)"
if [[ "$ARCH" == "arm64" && -d "$FILES_DIR/Apple Silicon/$APP_NAME.app" ]]; then
  echo "Apple Silicon Mac detected. Installing the native application..."
  SOURCE_APP="$FILES_DIR/Apple Silicon/$APP_NAME.app"
  /bin/rm -rf "$DEST_APP"
  /usr/bin/ditto "$SOURCE_APP" "$DEST_APP" || fail "Could not copy the application."
else
  echo "Intel Mac or universal fallback detected."
  PYTHON_BIN="$(find_python || true)"
  if [[ -z "$PYTHON_BIN" ]]; then
    install_python
    PYTHON_BIN="$PYTHON_DEFAULT"
  fi

  SOURCE_APP="$FILES_DIR/Universal Template/$APP_NAME.app"
  [[ -d "$SOURCE_APP" ]] || fail "The universal application template is missing."
  /bin/rm -rf "$DEST_APP"
  /usr/bin/ditto "$SOURCE_APP" "$DEST_APP" || fail "Could not copy the universal application."
  /bin/echo -n "$PYTHON_BIN" > "$DEST_APP/Contents/Resources/python-path.txt"
  PYTHONPATH="$DEST_APP/Contents/Resources/app/src" "$PYTHON_BIN" -c 'import hl7_shines.app' >/dev/null 2>&1 || fail "The installed application source could not be loaded."
fi

/bin/chmod +x "$DEST_APP/Contents/MacOS/"* 2>/dev/null || true
/usr/bin/xattr -dr com.apple.quarantine "$DEST_APP" 2>/dev/null || true
/usr/bin/codesign --force --deep --sign - "$DEST_APP" >/dev/null 2>&1 || true

echo "Opening $APP_NAME..."
/usr/bin/open "$DEST_APP" || fail "The application was installed but could not be opened."

echo ""
echo "Installation complete."
echo "Installed at: $DEST_APP"
show_dialog "$APP_NAME $VERSION was installed successfully in your Applications folder."
