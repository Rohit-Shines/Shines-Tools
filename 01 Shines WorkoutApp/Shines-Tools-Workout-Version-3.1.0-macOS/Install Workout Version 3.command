#!/bin/zsh -f
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$SOURCE_DIR/payload"
TARGET="$HOME/Documents/Shines Tools/Workout Version 3"
APP="$HOME/Applications/Workout Version 3.app"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$HOME/Desktop/Workout_Version_3_Installation_${STAMP}.log"
PORT=8793

exec > >(tee -a "$LOG") 2>&1

printf '\n============================================================\n'
printf ' Shines Tools — Workout Version 3.1 macOS Installer\n'
printf '============================================================\n\n'

[[ "$(uname -s)" == "Darwin" ]] || { echo "ERROR: This package is for macOS only."; exit 1; }
ARCH="$(uname -m)"
[[ "$ARCH" == "arm64" || "$ARCH" == "x86_64" ]] || { echo "ERROR: Unsupported architecture: $ARCH"; exit 1; }

DEFAULT_NAME="$(id -F 2>/dev/null || echo User)"
PROFILE=$(/usr/bin/osascript - "$DEFAULT_NAME" <<'PROFILE_APPLESCRIPT' 2>/dev/null || true
on run argv
  set defaultName to item 1 of argv
  set answer to display dialog "Enter the profile name for Workout Version 3:" with title "Shines Tools Setup" default answer defaultName buttons {"Cancel", "Continue"} default button "Continue" cancel button "Cancel"
  return text returned of answer
end run
PROFILE_APPLESCRIPT
)
PROFILE="${PROFILE:-$DEFAULT_NAME}"
PROFILE="$(echo "$PROFILE" | tr '\n\r' '  ' | sed 's/^ *//;s/ *$//')"
[[ -z "$PROFILE" ]] && PROFILE="User"

mkdir -p "$HOME/Documents/Shines Tools" "$HOME/Applications"
if [[ -d "$TARGET" && -n "$(ls -A "$TARGET" 2>/dev/null)" ]]; then
  BACKUP="$HOME/Documents/Shines Tools/Workout Version 3_backup_${STAMP}"
  echo "Existing installation found. Backing up to: $BACKUP"
  mv "$TARGET" "$BACKUP"
fi
mkdir -p "$TARGET"
/usr/bin/rsync -a --exclude '.DS_Store' --exclude '.pytest_cache' "$PAYLOAD/" "$TARGET/"
cd "$TARGET"
mkdir -p data logs exports reports recordings versions models .bootstrap .python .cache

[[ -f "$TARGET/models/pose_landmarker_full.task" ]] || { echo "ERROR: Pose model is missing."; exit 1; }

UV="$TARGET/.bootstrap/uv"
if [[ ! -x "$UV" ]]; then
  /usr/bin/curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$TARGET/.bootstrap" sh
fi
[[ -x "$UV" ]] || { echo "ERROR: uv installation failed."; exit 1; }

export UV_PYTHON_INSTALL_DIR="$TARGET/.python"
export UV_CACHE_DIR="$TARGET/.cache/uv"
export UV_NO_PROGRESS=1

"$UV" python install 3.12
rm -rf "$TARGET/.venv"
"$UV" venv --python 3.12 "$TARGET/.venv"
PY="$TARGET/.venv/bin/python"
"$UV" pip install --python "$PY" -r "$TARGET/requirements.txt"
if [[ "$ARCH" == "arm64" ]]; then
  "$UV" pip install --python "$PY" 'mediapipe==0.10.35'
else
  "$UV" pip install --python "$PY" 'mediapipe==0.10.21'
fi

PYTHONPATH="$TARGET" "$PY" - <<'PYVERIFY'
import platform, sys, numpy, cv2, mediapipe, matplotlib
from workout_ai.constants import EXERCISES
print('Python:', sys.version.split()[0])
print('Architecture:', platform.machine())
print('NumPy:', numpy.__version__)
print('OpenCV:', cv2.__version__)
print('MediaPipe:', mediapipe.__version__)
print('Matplotlib:', matplotlib.__version__)
print('Exercises:', len(EXERCISES))
PYVERIFY

PYTHONPATH="$TARGET" "$PY" "$TARGET/setup_profile.py" --home "$TARGET" --profile "$PROFILE"
PYTHONPATH="$TARGET" "$PY" -m pytest "$TARGET/tests" --import-mode=importlib -q

SNAPSHOT="$TARGET/versions/3.1.0-clean-install_${STAMP}"
mkdir -p "$SNAPSHOT"
cp -R "$TARGET/workout_ai" "$TARGET/tests" "$SNAPSHOT/"
cp "$TARGET/workout_gui.py" "$TARGET/workout_tracker.py" "$TARGET/reminder_agent.py" "$TARGET/VERSION.txt" "$TARGET/requirements.txt" "$SNAPSHOT/"

BRIDGE="$TARGET/launch_workout_version_3_via_terminal.command"
cat > "$BRIDGE" <<'BRIDGE_SCRIPT'
#!/bin/zsh -f
set -u
ROOT="$HOME/Documents/Shines Tools/Workout Version 3"
PYTHON="$ROOT/.venv/bin/python"
GUI="$ROOT/workout_gui.py"
LOG="$ROOT/logs/terminal_bridge_runtime.log"
PORT=8793
mkdir -p "$ROOT/logs"
exec >> "$LOG" 2>&1
pkill -f "$ROOT/workout_gui.py" 2>/dev/null || true
pkill -f "$ROOT/workout_tracker.py" 2>/dev/null || true
sleep 1
cd "$ROOT" || exit 1
export PYTHONPATH="$ROOT"
export PATH="$ROOT/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUNBUFFERED=1
exec "$PYTHON" "$GUI" --home "$ROOT" --port "$PORT"
BRIDGE_SCRIPT
chmod +x "$BRIDGE"
xattr -d com.apple.quarantine "$BRIDGE" 2>/dev/null || true

rm -rf "$APP"
APPLESCRIPT_FILE="$TARGET/.build_launcher_${STAMP}.applescript"
cat > "$APPLESCRIPT_FILE" <<'APPLESCRIPT_CODE'
on run
  set bridgePath to POSIX path of (path to home folder) & "Documents/Shines Tools/Workout Version 3/launch_workout_version_3_via_terminal.command"
  set launchCommand to "/bin/zsh -f " & quoted form of bridgePath
  tell application "Terminal"
    activate
    do script launchCommand
    delay 2
    try
      set miniaturized of front window to true
    end try
  end tell
end run
APPLESCRIPT_CODE
/usr/bin/osacompile -o "$APP" "$APPLESCRIPT_FILE"
rm -f "$APPLESCRIPT_FILE"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
/usr/bin/codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true

cat > "$TARGET/Start Workout Version 3.command" <<'START_COMMAND'
#!/bin/zsh -f
APP="$HOME/Applications/Workout Version 3.app"
if [[ ! -d "$APP" ]]; then
  /usr/bin/osascript -e 'display alert "Workout Version 3 is not installed" message "Run the Shines Tools installer again."'
  exit 1
fi
open "$APP"
START_COMMAND

cat > "$TARGET/Diagnose Workout Version 3.command" <<'DIAG_COMMAND'
#!/bin/zsh -f
set -u
ROOT="$HOME/Documents/Shines Tools/Workout Version 3"
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/logs/diagnostic_$(date +%Y%m%d_%H%M%S).txt"
mkdir -p "$ROOT/logs"
exec > >(tee "$LOG") 2>&1
echo "Workout Version 3 diagnostics"
echo "macOS: $(sw_vers -productVersion)"
echo "Architecture: $(uname -m)"
echo "Root: $ROOT"
echo "Version: $(cat "$ROOT/VERSION.txt" 2>/dev/null || echo missing)"
if [[ ! -x "$PY" ]]; then echo "ERROR: Python environment missing"; exit 1; fi
cd "$ROOT"
PYTHONPATH="$ROOT" "$PY" - <<'PYDIAG'
import platform, sys, numpy, cv2, mediapipe, matplotlib
from workout_ai.constants import DEFAULT_HOME, EXERCISES
print('Python:', sys.version)
print('Architecture:', platform.machine())
print('NumPy:', numpy.__version__)
print('OpenCV:', cv2.__version__)
print('MediaPipe:', mediapipe.__version__)
print('Matplotlib:', matplotlib.__version__)
print('Default home:', DEFAULT_HOME)
print('Exercises:', len(EXERCISES))
PYDIAG
echo "App: $(test -d "$HOME/Applications/Workout Version 3.app" && echo FOUND || echo MISSING)"
echo "Port 8793:"
lsof -nP -iTCP:8793 -sTCP:LISTEN || true
tail -n 100 "$ROOT/logs/gui_process.log" 2>/dev/null || true
tail -n 100 "$ROOT/logs/terminal_bridge_runtime.log" 2>/dev/null || true
echo "Diagnostic saved: $LOG"
read "?Press Return to close."
DIAG_COMMAND

cat > "$TARGET/Export Workout Data.command" <<'EXPORT_COMMAND'
#!/bin/zsh -f
ROOT="$HOME/Documents/Shines Tools/Workout Version 3"
PY="$ROOT/.venv/bin/python"
cd "$ROOT" || exit 1
PROFILE="${1:-User}"
PYTHONPATH="$ROOT" "$PY" "$ROOT/export_data.py" --home "$ROOT" --profile "$PROFILE"
open "$ROOT/exports"
read "?Press Return to close."
EXPORT_COMMAND

cat > "$TARGET/Uninstall Workout Version 3.command" <<'UNINSTALL_COMMAND'
#!/bin/zsh -f
set -e
ROOT="$HOME/Documents/Shines Tools/Workout Version 3"
APP="$HOME/Applications/Workout Version 3.app"
choice=$(/usr/bin/osascript <<'APPLESCRIPT'
button returned of (display dialog "Remove Workout Version 3?" with title "Shines Tools Uninstaller" buttons {"Cancel", "Keep Data", "Delete Everything"} default button "Keep Data" cancel button "Cancel" with icon caution)
APPLESCRIPT
) || exit 0
pkill -f "$ROOT/workout_gui.py" 2>/dev/null || true
pkill -f "$ROOT/workout_tracker.py" 2>/dev/null || true
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.shinestools.workoutversion3.reminder.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.shinestools.workoutversion3.reminder.plist"
rm -rf "$APP"
if [[ "$choice" == "Delete Everything" ]]; then
  rm -rf "$ROOT"
else
  rm -rf "$ROOT/.venv" "$ROOT/.bootstrap" "$ROOT/.python" "$ROOT/.cache"
  echo "Application removed. Data remains in $ROOT/data and $ROOT/exports"
fi
UNINSTALL_COMMAND

chmod +x "$TARGET"/*.command 2>/dev/null || true
xattr -d com.apple.quarantine "$TARGET"/*.command 2>/dev/null || true

/usr/bin/tccutil reset Camera com.apple.Terminal >/dev/null 2>&1 || true
set +e
PYTHONPATH="$TARGET" "$PY" "$TARGET/camera_permission_test.py" --home "$TARGET"
CAMERA_RESULT=$?
set -e
if [[ $CAMERA_RESULT -ne 0 ]]; then
  echo "Camera permission was not confirmed. Enable Terminal under Privacy & Security → Camera."
  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Camera' || true
fi

open "$APP"
echo
printf '============================================================\n'
printf ' INSTALLATION COMPLETE\n'
printf '============================================================\n'
echo "Application: $APP"
echo "Program files: $TARGET"
echo "History: $TARGET/data/workouts.sqlite3"
echo "Exports: $TARGET/exports"
echo "Log: $LOG"
/usr/bin/osascript -e 'display dialog "Workout Version 3.1 installation is complete. Approve Terminal camera and automation permission when requested." with title "Shines Tools Installed" buttons {"OK"} default button "OK"' >/dev/null 2>&1 || true
read "?Press Return to close this installer window."
