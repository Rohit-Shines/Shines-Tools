$ErrorActionPreference = "Stop"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload = Join-Path $SourceDir "payload"
$Documents = [Environment]::GetFolderPath("MyDocuments")
$Desktop = [Environment]::GetFolderPath("Desktop")
$Target = Join-Path $Documents "Shines Tools\Workout Version 3"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $Desktop "Workout_Version_3_Installation_$Stamp.log"
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$DesktopShortcut = Join-Path $Desktop "Workout Version 3.lnk"
$StartMenuShortcut = Join-Path $StartMenu "Workout Version 3.lnk"

Start-Transcript -Path $Log -Append | Out-Null
$Backup = $null
try {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " Shines Tools - Workout Version 3.1 Windows Installer" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    if (-not [Environment]::Is64BitOperatingSystem) { throw "64-bit Windows 10 or Windows 11 is required." }
    $Architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    if ($Architecture -ne "X64") { throw "This release supports Windows x64. Detected: $Architecture" }

    Add-Type -AssemblyName Microsoft.VisualBasic
    $Profile = [Microsoft.VisualBasic.Interaction]::InputBox("Enter the profile name:", "Workout Version 3 Setup", $env:USERNAME).Trim()
    if ([string]::IsNullOrWhiteSpace($Profile)) { $Profile = "User" }

    New-Item -ItemType Directory -Path (Split-Path $Target -Parent) -Force | Out-Null
    if (Test-Path $Target) {
        $Backup = Join-Path (Split-Path $Target -Parent) "Workout Version 3_backup_$Stamp"
        Move-Item -LiteralPath $Target -Destination $Backup -Force
    }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    Copy-Item -Path (Join-Path $Payload "*") -Destination $Target -Recurse -Force
    foreach ($folder in @("data","logs","exports","reports","recordings","versions","models",".bootstrap",".python",".cache")) {
        New-Item -ItemType Directory -Path (Join-Path $Target $folder) -Force | Out-Null
    }
    if ($Backup) {
        foreach ($folder in @("data","exports","reports","versions")) {
            $source = Join-Path $Backup $folder
            if (Test-Path $source) { Copy-Item -Path (Join-Path $source "*") -Destination (Join-Path $Target $folder) -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }

    if (-not (Test-Path (Join-Path $Target "models\pose_landmarker_full.task"))) { throw "Pose model is missing. Extract the ZIP again." }

    $Bootstrap = Join-Path $Target ".bootstrap"
    $Uv = Join-Path $Bootstrap "uv.exe"
    if (-not (Test-Path $Uv)) {
        $env:UV_UNMANAGED_INSTALL = $Bootstrap
        Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression
    }
    if (-not (Test-Path $Uv)) { throw "Private Python manager installation failed." }

    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Target ".python"
    $env:UV_CACHE_DIR = Join-Path $Target ".cache\uv"
    $env:UV_NO_PROGRESS = "1"
    & $Uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed." }
    $Venv = Join-Path $Target ".venv"
    if (Test-Path $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force }
    & $Uv venv --python 3.12 $Venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
    $Python = Join-Path $Venv "Scripts\python.exe"
    $Pythonw = Join-Path $Venv "Scripts\pythonw.exe"

    & $Uv pip install --python $Python -r (Join-Path $Target "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $Uv pip install --python $Python "mediapipe==0.10.21"
    if ($LASTEXITCODE -ne 0) { throw "MediaPipe installation failed." }

    $env:PYTHONPATH = $Target
    & $Python -c "import platform,sys,numpy,cv2,mediapipe,matplotlib;from workout_ai.constants import EXERCISES;print('Python:',sys.version.split()[0]);print('Architecture:',platform.machine());print('NumPy:',numpy.__version__);print('OpenCV:',cv2.__version__);print('MediaPipe:',mediapipe.__version__);print('Matplotlib:',matplotlib.__version__);print('Exercises:',len(EXERCISES))"
    if ($LASTEXITCODE -ne 0) { throw "Application import verification failed." }

    & $Python (Join-Path $Target "setup_profile.py") --home $Target --profile $Profile
    if ($LASTEXITCODE -ne 0) { throw "Profile setup failed." }

    & $Python -m pytest (Join-Path $Target "tests") --import-mode=importlib -q
    if ($LASTEXITCODE -ne 0) { throw "Automated tests failed." }

    $CameraReady = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & $Python (Join-Path $Target "camera_permission_test.py") --home $Target
        if ($LASTEXITCODE -eq 0) { $CameraReady = $true; break }
        Start-Process "ms-settings:privacy-webcam"
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "Enable Camera access, Let apps access your camera, and Let desktop apps access your camera. Close Teams, Zoom, OBS and the Camera app, then click OK to retry.",
            "Workout Version 3 Camera Setup",
            "OK",
            "Warning"
        ) | Out-Null
    }
    if (-not $CameraReady) { Write-Warning "Camera access was not confirmed. Installation will continue." }

    $StartBat = Join-Path $Target "Start Workout Version 3.bat"
    @"
@echo off
cd /d "$Target"
start "Workout Version 3" "$Pythonw" "$Target\launch_workout_version_3.pyw"
"@ | Set-Content -LiteralPath $StartBat -Encoding ASCII

    $CameraBat = Join-Path $Target "Open Camera Settings.bat"
    "@echo off`r`nstart ms-settings:privacy-webcam`r`n" | Set-Content -LiteralPath $CameraBat -Encoding ASCII

    $DiagnoseBat = Join-Path $Target "Diagnose Workout Version 3.bat"
    @"
@echo off
cd /d "$Target"
set WORKOUT_HOME=$Target
"$Python" "$Target\diagnose_windows.py"
pause
"@ | Set-Content -LiteralPath $DiagnoseBat -Encoding ASCII

    $ExportBat = Join-Path $Target "Export Workout Data.bat"
    @"
@echo off
cd /d "$Target"
"$Python" "$Target\export_data.py" --home "$Target" --profile "$Profile"
start "" "$Target\exports"
pause
"@ | Set-Content -LiteralPath $ExportBat -Encoding ASCII

    $UninstallPs1 = Join-Path $Target "Uninstall-WorkoutVersion3.ps1"
    @'
Add-Type -AssemblyName PresentationFramework
$Documents = [Environment]::GetFolderPath("MyDocuments")
$Desktop = [Environment]::GetFolderPath("Desktop")
$Target = Join-Path $Documents "Shines Tools\Workout Version 3"
$StartMenuLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Workout Version 3.lnk"
$DesktopLink = Join-Path $Desktop "Workout Version 3.lnk"
$result = [System.Windows.MessageBox]::Show("Keep workout history and exports? Yes keeps a backup; No removes everything.","Uninstall Workout Version 3","YesNoCancel","Question")
if ($result -eq "Cancel") { exit }
Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "*$Target*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item $DesktopLink,$StartMenuLink -Force -ErrorAction SilentlyContinue
schtasks.exe /Delete /TN "Shines Tools - Workout Version 3 Reminder" /F 2>$null | Out-Null
if ($result -eq "Yes") {
  $backup = Join-Path $Documents ("Workout_Version_3_Data_Backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
  New-Item -ItemType Directory -Path $backup -Force | Out-Null
  foreach ($folder in @("data","exports","reports","versions")) { if (Test-Path (Join-Path $Target $folder)) { Copy-Item (Join-Path $Target $folder) $backup -Recurse -Force } }
  Remove-Item $Target -Recurse -Force
  [System.Windows.MessageBox]::Show("Workout Version 3 was removed. Data backup: $backup","Uninstall complete") | Out-Null
} else {
  Remove-Item $Target -Recurse -Force
  [System.Windows.MessageBox]::Show("Workout Version 3 and local data were removed.","Uninstall complete") | Out-Null
}
'@ | Set-Content -LiteralPath $UninstallPs1 -Encoding UTF8

    $UninstallBat = Join-Path $Target "Uninstall Workout Version 3.bat"
    "@echo off`r`nPowerShell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UninstallPs1`"`r`n" | Set-Content -LiteralPath $UninstallBat -Encoding ASCII

    $WshShell = New-Object -ComObject WScript.Shell
    foreach ($linkPath in @($DesktopShortcut, $StartMenuShortcut)) {
        $Shortcut = $WshShell.CreateShortcut($linkPath)
        $Shortcut.TargetPath = $Pythonw
        $Shortcut.Arguments = "`"$(Join-Path $Target 'launch_workout_version_3.pyw')`""
        $Shortcut.WorkingDirectory = $Target
        $Shortcut.Description = "Shines Tools - Workout Version 3"
        $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
        $Shortcut.Save()
    }

    $Stable = Join-Path $Target "versions\3.1.0-windows-clean-$Stamp"
    New-Item -ItemType Directory -Path $Stable -Force | Out-Null
    foreach ($name in @("workout_ai","tests","workout_gui.py","workout_tracker.py","reminder_agent.py","VERSION.txt","requirements.txt","launch_workout_version_3.pyw")) {
        $source = Join-Path $Target $name
        if (Test-Path $source) { Copy-Item $source (Join-Path $Stable $name) -Recurse -Force }
    }

    Start-Process -FilePath $Pythonw -ArgumentList "`"$(Join-Path $Target 'launch_workout_version_3.pyw')`"" -WorkingDirectory $Target
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "Workout Version 3.1 installation is complete.`n`nUse the Desktop or Start menu shortcut.`n`nProgram: $Target`nHistory: $Target\data\workouts.sqlite3`nExports: $Target\exports",
        "Shines Tools Installed",
        "OK",
        "Information"
    ) | Out-Null

    Write-Host "INSTALLATION COMPLETE" -ForegroundColor Green
    Write-Host "Program files: $Target"
    Write-Host "History: $Target\data\workouts.sqlite3"
    Write-Host "Exports: $Target\exports"
    Write-Host "Log: $Log"
}
catch {
    Write-Host "INSTALLATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($Backup -and (Test-Path $Backup)) {
        if (Test-Path $Target) { Move-Item -LiteralPath $Target -Destination (Join-Path $Documents "Workout_Version_3_failed_$Stamp") -Force -ErrorAction SilentlyContinue }
        Move-Item -LiteralPath $Backup -Destination $Target -Force
        Write-Host "Previous installation restored." -ForegroundColor Green
    }
    Write-Host "Log: $Log" -ForegroundColor Yellow
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
