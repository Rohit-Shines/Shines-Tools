# Install Workout Version 3.1 on Windows

## Requirements

- Windows 10 or Windows 11
- 64-bit x64 processor
- Built-in or USB webcam
- Internet connection for the first installation

## One-click installation

1. Download `Shines-Tools-Workout-Version-3.1.0-Windows.zip`.
2. Right-click the ZIP and select **Extract All**.
3. Open the extracted folder.
4. Double-click `Install Workout Version 3.bat`.
5. Enter the profile name when prompted.
6. Wait while the installer creates a private Python environment, installs dependencies, and runs tests.
7. If Camera privacy settings open, enable:
   - Camera access
   - Let apps access your camera
   - Let desktop apps access your camera
8. Start Workout Version 3 from the Desktop or Start menu.

The program files are installed under:

```text
Documents\Shines Tools\Workout Version 3
```

## PowerShell security warning

The BAT launcher uses PowerShell with `-ExecutionPolicy Bypass` only for the local installer script in the extracted package. No system-wide PowerShell setting is changed.

## Camera troubleshooting

Close Teams, Zoom, OBS, Webex, the Windows Camera app, and browser video calls before testing. Use:

```text
Documents\Shines Tools\Workout Version 3\Open Camera Settings.bat
```

## Uninstall

Run:

```text
Documents\Shines Tools\Workout Version 3\Uninstall Workout Version 3.bat
```

The uninstaller can preserve a backup of history, exports, reports and saved versions.
