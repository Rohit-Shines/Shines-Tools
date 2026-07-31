param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$AppName = "HL7 SHINES Explorer"
$Version = "1.2.0"
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\HL7 SHINES Explorer"
$RuntimeParent = Join-Path $env:LOCALAPPDATA "Programs\HL7 SHINES Explorer Runtime"
$RuntimeDir = Join-Path $RuntimeParent "Python312"
$PythonExe = Join-Path $RuntimeDir "python.exe"
$PythonwExe = Join-Path $RuntimeDir "pythonw.exe"
$PythonUrl = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\HL7 SHINES Explorer"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "HL7 SHINES Explorer.lnk"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HL7 SHINES Explorer"

Add-Type -AssemblyName System.Windows.Forms

function Show-Message([string]$Text, [string]$Title = "HL7 SHINES Explorer") {
    [System.Windows.Forms.MessageBox]::Show($Text, $Title, "OK", "Information") | Out-Null
}

function Get-DefaultRegistryValue([string]$Path) {
    try {
        return (Get-Item -Path $Path -ErrorAction Stop).GetValue("")
    } catch {
        return $null
    }
}

function Remove-Registration {
    Remove-Item $DesktopShortcut -Force -ErrorAction SilentlyContinue
    Remove-Item $StartMenuDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue

    foreach ($Extension in ".hl7", ".er7") {
        $ExtKey = "HKCU:\Software\Classes\$Extension"
        if ((Get-DefaultRegistryValue $ExtKey) -eq "HL7ShinesExplorer.Message") {
            Remove-Item $ExtKey -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item "HKCU:\Software\Classes\HL7ShinesExplorer.Message" -Recurse -Force -ErrorAction SilentlyContinue
}

if ($Uninstall) {
    Remove-Registration
    $DeleteCmd = 'timeout /t 2 /nobreak >nul & rmdir /s /q "{0}" & rmdir /s /q "{1}"' -f $InstallDir, $RuntimeParent
    Start-Process -FilePath $env:ComSpec -ArgumentList "/d", "/c", $DeleteCmd -WindowStyle Hidden
    Show-Message "$AppName was removed from this Windows account." "Uninstall Complete"
    exit 0
}

try {
    $PayloadDir = Join-Path $PackageRoot "App Files - Do Not Delete"
    if (-not (Test-Path (Join-Path $PayloadDir "launch.pyw"))) {
        throw "The App Files folder is missing. Keep the complete package together."
    }
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

    $RuntimeReady = (Test-Path $PythonExe) -and (Test-Path $PythonwExe)
    if ($RuntimeReady) {
        & $PythonExe -c "import sys, tkinter; assert sys.version_info >= (3, 11)"
        $RuntimeReady = ($LASTEXITCODE -eq 0)
    }

    if (-not $RuntimeReady) {
        $InstallerPath = Join-Path $env:TEMP "python-3.12.9-amd64.exe"
        $ProgressPreference = "SilentlyContinue"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        try {
            Invoke-WebRequest -Uri $PythonUrl -OutFile $InstallerPath -UseBasicParsing
        } catch {
            Import-Module BitsTransfer -ErrorAction Stop
            Start-BitsTransfer -Source $PythonUrl -Destination $InstallerPath
        }

        $Signature = Get-AuthenticodeSignature $InstallerPath
        if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            throw "The downloaded Python installer signature could not be verified."
        }

        $Arguments = @(
            "/quiet",
            "InstallAllUsers=0",
            "TargetDir=$RuntimeDir",
            "Include_launcher=0",
            "InstallLauncherAllUsers=0",
            "Include_pip=0",
            "Include_tcltk=1",
            "Include_test=0",
            "Include_doc=0",
            "Include_debug=0",
            "Include_symbols=0",
            "Include_dev=0",
            "Shortcuts=0",
            "AssociateFiles=0",
            "PrependPath=0"
        )
        $Process = Start-Process -FilePath $InstallerPath -ArgumentList $Arguments -Wait -PassThru
        Remove-Item $InstallerPath -Force -ErrorAction SilentlyContinue
        if ($Process.ExitCode -ne 0) {
            throw "The Python runtime installer returned error code $($Process.ExitCode)."
        }
    }

    if (-not (Test-Path $PythonwExe)) {
        throw "The application runtime was not installed correctly."
    }
    & $PythonExe -c "import sys, tkinter; assert sys.version_info >= (3, 11)"
    if ($LASTEXITCODE -ne 0) {
        throw "The installed Python runtime cannot load Tkinter."
    }

    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item (Join-Path $PayloadDir "src") (Join-Path $InstallDir "src") -Recurse -Force
    Copy-Item (Join-Path $PayloadDir "launch.pyw") $InstallDir -Force
    Copy-Item (Join-Path $PayloadDir "AppIcon.ico") $InstallDir -Force
    Copy-Item $MyInvocation.MyCommand.Path (Join-Path $InstallDir "Installer Support.ps1") -Force

    $PreviousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $InstallDir "src"
    & $PythonExe -c "import hl7_shines.app"
    $ImportExitCode = $LASTEXITCODE
    $env:PYTHONPATH = $PreviousPythonPath
    if ($ImportExitCode -ne 0) {
        throw "The installed HL7 SHINES Explorer source could not be loaded."
    }

    $InstalledUninstallBat = Join-Path $InstallDir "Uninstall HL7 SHINES Explorer.bat"
    @(
        "@echo off",
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installer Support.ps1" -Uninstall'
    ) | Set-Content -Path $InstalledUninstallBat -Encoding ASCII

    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($DesktopShortcut)
    $Shortcut.TargetPath = $PythonwExe
    $Shortcut.Arguments = '"' + (Join-Path $InstallDir "launch.pyw") + '"'
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.IconLocation = (Join-Path $InstallDir "AppIcon.ico") + ",0"
    $Shortcut.Description = "HL7 v2 message explorer, validator, editor, analytics and MLLP test tool"
    $Shortcut.Save()

    New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
    Copy-Item $DesktopShortcut (Join-Path $StartMenuDir "HL7 SHINES Explorer.lnk") -Force
    $UninstallShortcut = $Shell.CreateShortcut((Join-Path $StartMenuDir "Uninstall HL7 SHINES Explorer.lnk"))
    $UninstallShortcut.TargetPath = $InstalledUninstallBat
    $UninstallShortcut.WorkingDirectory = $InstallDir
    $UninstallShortcut.Save()

    New-Item -Path "HKCU:\Software\Classes\HL7ShinesExplorer.Message" -Force | Out-Null
    Set-Item -Path "HKCU:\Software\Classes\HL7ShinesExplorer.Message" -Value "HL7 Message"
    New-Item -Path "HKCU:\Software\Classes\HL7ShinesExplorer.Message\DefaultIcon" -Force | Out-Null
    Set-Item -Path "HKCU:\Software\Classes\HL7ShinesExplorer.Message\DefaultIcon" -Value ((Join-Path $InstallDir "AppIcon.ico") + ",0")
    New-Item -Path "HKCU:\Software\Classes\HL7ShinesExplorer.Message\shell\open\command" -Force | Out-Null
    $OpenCommand = '"{0}" "{1}" "%1"' -f $PythonwExe, (Join-Path $InstallDir "launch.pyw")
    Set-Item -Path "HKCU:\Software\Classes\HL7ShinesExplorer.Message\shell\open\command" -Value $OpenCommand
    foreach ($Extension in ".hl7", ".er7") {
        New-Item -Path "HKCU:\Software\Classes\$Extension" -Force | Out-Null
        Set-Item -Path "HKCU:\Software\Classes\$Extension" -Value "HL7ShinesExplorer.Message"
    }

    New-Item -Path $UninstallKey -Force | Out-Null
    Set-ItemProperty -Path $UninstallKey -Name "DisplayName" -Value $AppName
    Set-ItemProperty -Path $UninstallKey -Name "DisplayVersion" -Value $Version
    Set-ItemProperty -Path $UninstallKey -Name "Publisher" -Value "Rohit Shines"
    Set-ItemProperty -Path $UninstallKey -Name "InstallLocation" -Value $InstallDir
    Set-ItemProperty -Path $UninstallKey -Name "DisplayIcon" -Value (Join-Path $InstallDir "AppIcon.ico")
    Set-ItemProperty -Path $UninstallKey -Name "UninstallString" -Value ('"' + $InstalledUninstallBat + '"')
    Set-ItemProperty -Path $UninstallKey -Name "NoModify" -Type DWord -Value 1
    Set-ItemProperty -Path $UninstallKey -Name "NoRepair" -Type DWord -Value 1

    Start-Process -FilePath $PythonwExe -ArgumentList ('"' + (Join-Path $InstallDir "launch.pyw") + '"') -WorkingDirectory $InstallDir
    Show-Message "$AppName $Version was installed successfully. A shortcut was added to the Desktop and Start menu." "Installation Complete"
} catch {
    Show-Message ("Installation failed:`r`n`r`n" + $_.Exception.Message + "`r`n`r`nCheck the internet connection and keep all package files together.") "Installation Failed"
    exit 1
}
