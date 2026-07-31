# Install Workout Version 3.1 on macOS

## Requirements

- macOS 12 or later
- Apple Silicon or Intel 64-bit Mac
- Built-in or USB camera
- Internet connection for the first installation

## One-click installation

1. Download `Shines-Tools-Workout-Version-3.1.0-macOS.zip`.
2. Double-click the ZIP to extract it.
3. Open the extracted folder.
4. Right-click `Install Workout Version 3.command` and choose **Open**.
5. Enter the profile name.
6. Wait while the installer creates a private Python environment and runs the automated tests.
7. When macOS asks, allow Terminal to use the camera and allow the launcher to control Terminal.
8. Open `~/Applications/Workout Version 3.app`.

The program files are installed under:

```text
~/Documents/Shines Tools/Workout Version 3
```

## Gatekeeper fallback

Open Terminal, type `cd `, drag the extracted installer folder into Terminal, and press Return. Then run:

```bash
xattr -dr com.apple.quarantine .
chmod +x "Install Workout Version 3.command"
/bin/zsh -f "./Install Workout Version 3.command"
```

## Camera permission

Workout Version 3 uses a Terminal bridge because Terminal reliably owns the camera permission for the Python/OpenCV process. Keep the minimised Terminal window open while a workout is active.

Review camera permission under:

```text
System Settings → Privacy & Security → Camera
```

## Uninstall

Run:

```text
~/Documents/Shines Tools/Workout Version 3/Uninstall Workout Version 3.command
```

The uninstaller asks whether to preserve workout history and exports.
