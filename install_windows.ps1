# Windows PowerShell 5.1; run through Install PlumeWatch.bat.
$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu'
$logStarted = $false

try {
    if ($env:OS -ne 'Windows_NT') { throw 'This installer runs on Windows only.' }
    $windows = Get-CimInstance Win32_OperatingSystem
    if ([int]$windows.BuildNumber -lt 19041) {
        throw 'Windows 11 or Windows 10 build 19041 or newer is required.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'Windows cannot find wsl.exe. Install Windows updates and retry.'
    }
    foreach ($file in @('scripts/install_wsl.sh', 'Start Dashboard.bat')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $file))) {
            throw "Missing $file. Extract the entire installer ZIP before running it."
        }
    }
    $installDir = Join-Path $env:LOCALAPPDATA 'PlumeWatch'
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    $logPath = Join-Path $installDir ('install-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    Start-Transcript -Path $logPath | Out-Null
    $logStarted = $true
    Write-Host 'PlumeWatch setup: Ubuntu/WSL2, Python environments, models and verification.'
    Write-Host "Internet access is required. Setup log: $logPath"

    # Probe errors are expected when WSL has not been enabled yet.
    $ErrorActionPreference = 'Continue'
    & wsl.exe --version 2>$null | Out-Null
    $wslReady = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
    if (-not $wslReady) {
        Write-Host 'Windows will ask for administrator permission to enable WSL.'
        # Enable system components only; Ubuntu must belong to the original Windows user.
        $enableCommand = '& wsl.exe --install --no-distribution; $result = $LASTEXITCODE; if ($result -notin @(0,3010)) { Read-Host "WSL setup failed. Keep the error above, then press Enter" | Out-Null }; exit $result'
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($enableCommand))
        $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru `
            -ArgumentList "-NoProfile -EncodedCommand $encoded"
        if ($process.ExitCode -notin @(0, 3010)) {
            throw "WSL setup failed (exit $($process.ExitCode)). See the administrator window output."
        }
        Write-Host 'Save your work and restart Windows, then double-click Install PlumeWatch.bat again.'
        exit 3010
    }

    $ErrorActionPreference = 'Continue'
    $names = @(& wsl.exe --list --quiet 2>$null) -replace "`0", ''
    $ErrorActionPreference = 'Stop'
    $newUbuntu = -not ($names | Where-Object { $_.Trim() -eq $distro })
    if ($newUbuntu) {
        Write-Host 'Installing Ubuntu. Create its username/password if asked.'
        Write-Host 'If you reach an Ubuntu shell prompt, type exit to return to this installer.'
        & wsl.exe --install -d $distro
        if ($LASTEXITCODE -eq 3010) {
            Write-Host 'Restart Windows, then double-click Install PlumeWatch.bat again.'
            exit 3010
        }
        if ($LASTEXITCODE -ne 0) { throw 'Ubuntu installation failed. Keep the output above.' }
    }

    $ErrorActionPreference = 'Continue'
    $userId = (& wsl.exe -d $distro -- id -u 2>$null | Out-String).Trim()
    $userExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($userExit -ne 0 -or $userId -eq '0') {
        Write-Host 'Ubuntu will open. Create your Linux username/password if asked.'
        Write-Host 'When its setup finishes, close that Ubuntu window and return here.'
        Start-Process -FilePath 'wsl.exe' -ArgumentList '-d Ubuntu' | Out-Null
        Read-Host 'Press Enter after finishing Ubuntu account setup' | Out-Null
        $userId = (& wsl.exe -d $distro -- id -u | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $userId -notmatch '^[1-9][0-9]*$') {
            throw 'Ubuntu needs a normal (non-root) default user. Finish its account setup and rerun this installer.'
        }
    }

    $kernel = (& wsl.exe -d $distro -- uname -r | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu could not start. Restart Windows and retry.' }
    if ($kernel -notmatch '(?i)WSL2') {
        $answer = Read-Host 'Ubuntu uses WSL1. Save/back up its work before converting to WSL2. Convert now? [y/N]'
        if ($answer -ne 'y') { throw 'WSL2 is required. No conversion was performed.' }
        & wsl.exe --set-version $distro 2
        if ($LASTEXITCODE -ne 0) { throw 'Ubuntu could not be converted to WSL2.' }
    }

    $scriptPath = Join-Path $PSScriptRoot 'scripts/install_wsl.sh'
    # Direct execution preserves path backslashes and spaces instead of parsing them in a shell.
    $linuxPath = (& wsl.exe -d $distro --exec wslpath -a -u $scriptPath | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $linuxPath.StartsWith('/')) {
        throw "Ubuntu could not translate installer path '$scriptPath' (wslpath exit $LASTEXITCODE). Keep the WSL error above for diagnosis."
    }
    & wsl.exe -d $distro --exec bash $linuxPath
    if ($LASTEXITCODE -ne 0) { throw 'PlumeWatch installation or verification failed. Fix the error above and rerun setup.' }

    $launcher = Join-Path $installDir 'Start Dashboard.bat'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start Dashboard.bat') -Destination $launcher -Force
    $shell = New-Object -ComObject WScript.Shell
    $desktop = $shell.SpecialFolders.Item('Desktop')
    $shortcutPath = Join-Path $desktop 'PlumeWatch.lnk'
    if (Test-Path -LiteralPath $shortcutPath) {
        $existing = $shell.CreateShortcut($shortcutPath)
        if ($existing.TargetPath -ne $launcher) {
            throw 'A different PlumeWatch shortcut already exists on your Desktop. Rename it and rerun setup.'
        }
    }
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $launcher
    $shortcut.WorkingDirectory = $installDir
    $shortcut.Description = 'Start the PlumeWatch dashboard in Ubuntu/WSL2'
    $shortcut.Save()
    Write-Host 'Installation and model checks passed. Double-click PlumeWatch on your Desktop to start.'
    Write-Host 'Keep the dashboard window open while using it; press Ctrl+C there to stop.'
    exit 0
}
catch {
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'You can rerun Install PlumeWatch.bat after fixing the problem; completed steps are reused.'
    exit 1
}
finally {
    if ($logStarted) {
        Stop-Transcript | Out-Null
        Write-Host "Setup log: $logPath"
    }
}
