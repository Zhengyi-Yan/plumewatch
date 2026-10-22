# Mock Windows/WSL calls in child processes; never enable features or install packages.
$ErrorActionPreference = 'Stop'
$previousLocalAppData = $env:LOCALAPPDATA
$installer = Join-Path (Split-Path $PSScriptRoot -Parent) 'install_windows.ps1'
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$runtime = (Get-Process -Id $PID).Path
$temp = Join-Path ([IO.Path]::GetTempPath()) ('plumewatch-ps-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
$mock = @'
$ErrorActionPreference = 'Stop'
$env:OS = 'Windows_NT'
function Get-CimInstance { [pscustomobject]@{ BuildNumber = '19045' } }
function Get-Command {
    if ($env:PW_TEST_CASE -ne 'missing_wsl') { [pscustomobject]@{ Name = 'wsl.exe' } }
}
function wsl.exe {
    Add-Content $env:PW_TEST_LOG ('wsl ' + ($args -join ' '))
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '--version') {
        if ($env:PW_TEST_CASE -in @('enable_wsl', 'enable_failed')) { $global:LASTEXITCODE = 1 }
    } elseif ($args[0] -eq '--list') {
        if ($env:PW_TEST_CASE -notin @('new_ubuntu', 'ubuntu_failed', 'ubuntu_reboot')) { "U`0b`0u`0n`0t`0u`0" }
    } elseif ($args[0] -eq '--install') {
        if ($env:PW_TEST_CASE -eq 'ubuntu_failed') { $global:LASTEXITCODE = 1 }
        if ($env:PW_TEST_CASE -eq 'ubuntu_reboot') { $global:LASTEXITCODE = 3010 }
    } elseif ($args -contains 'id') {
        if ($env:PW_TEST_CASE -eq 'root_user') { '0' } else { '1000' }
    } elseif ($args -contains 'uname') {
        if ($env:PW_TEST_CASE -like 'wsl1_*') { '4.4.0-Microsoft' } else { '6.6.0-microsoft-standard-WSL2' }
    } elseif ($args -contains 'wslpath') {
        if ($args[2] -ne '--exec') {
            $global:LASTEXITCODE = 1
            'wslpath: C:UsersdenniDesktopplumewatch-mainscriptsinstall_wsl.sh'
            return
        }
        $expectedPath = Join-Path (Split-Path $env:PW_TEST_INSTALLER -Parent) 'scripts/install_wsl.sh'
        if ($args.Count -ne 7 -or $args[-1] -ne $expectedPath) {
            throw 'Windows script path was split or changed before reaching wslpath.'
        }
        if ($env:PW_TEST_CASE -eq 'path_failed') { $global:LASTEXITCODE = 1; return }
        '/mnt/c/Test Folder & (review)/scripts/install_wsl.sh'
    } elseif ($args -contains 'bash') {
        if ($args.Count -ne 5 -or $args[2] -ne '--exec' -or
            $args[-1] -ne '/mnt/c/Test Folder & (review)/scripts/install_wsl.sh') {
            throw 'Ubuntu script path must be passed intact without a shell parsing it.'
        }
        if ($env:PW_TEST_CASE -eq 'install_failed') { $global:LASTEXITCODE = 1 }
    }
}
function Start-Process {
    param($FilePath, $ArgumentList, $Verb, [switch]$Wait, [switch]$PassThru)
    Add-Content $env:PW_TEST_LOG ('process ' + $FilePath + ' ' + $ArgumentList)
    if ($FilePath -eq 'powershell.exe') {
        $encoded = ($ArgumentList -split ' ')[-1]
        $command = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
        Add-Content $env:PW_TEST_LOG ('elevated ' + $command)
    }
    if ($env:PW_TEST_CASE -eq 'enable_failed') { [pscustomobject]@{ ExitCode = 5 } }
    else { [pscustomobject]@{ ExitCode = 0 } }
}
function Read-Host {
    Add-Content $env:PW_TEST_LOG 'prompt'
    if ($env:PW_TEST_CASE -eq 'wsl1_accept') { 'y' } else { '' }
}
function New-Object {
    param($ComObject)
    if ($ComObject -ne 'WScript.Shell') { throw 'Unexpected COM object' }
    $folders = [pscustomobject]@{}
    $folders | Add-Member ScriptMethod Item { param($name) $env:PW_TEST_DESKTOP }
    $shell = [pscustomobject]@{ SpecialFolders = $folders }
    $shell | Add-Member ScriptMethod CreateShortcut {
        param($path)
        $shortcut = [pscustomobject]@{ TargetPath = 'other-app'; WorkingDirectory = ''; Description = '' }
        $shortcut | Add-Member ScriptMethod Save { Add-Content $env:PW_TEST_LOG 'shortcut saved' }
        return $shortcut
    }
    return $shell
}
& $env:PW_TEST_INSTALLER
exit $LASTEXITCODE
'@
try {
    $sourceRoot = Split-Path $PSScriptRoot -Parent
    $fixture = Join-Path $temp 'installer folder with spaces & (review)'
    New-Item -ItemType Directory -Path (Join-Path $fixture 'scripts') | Out-Null
    foreach ($name in @('install_windows.ps1', 'Start Dashboard.bat', 'scripts/install_wsl.sh')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $fixture $name)
    }
    $installer = Join-Path $fixture 'install_windows.ps1'
    $wrapper = Join-Path $temp 'mock.ps1'
    [IO.File]::WriteAllText($wrapper, $mock)
    $cases = @{
        success = 0; enable_wsl = 3010; enable_failed = 1; missing_wsl = 1
        new_ubuntu = 0; ubuntu_failed = 1; ubuntu_reboot = 3010; root_user = 1
        wsl1_decline = 1; wsl1_accept = 0; install_failed = 1; shortcut_conflict = 1; path_failed = 1
    }
    foreach ($case in $cases.Keys) {
        $caseDir = Join-Path $temp $case
        New-Item -ItemType Directory -Path $caseDir | Out-Null
        $env:LOCALAPPDATA = $caseDir
        $env:PW_TEST_CASE = $case
        $env:PW_TEST_LOG = Join-Path $caseDir 'calls.txt'
        $env:PW_TEST_DESKTOP = $caseDir
        $env:PW_TEST_INSTALLER = $installer
        if ($case -eq 'shortcut_conflict') {
            Set-Content (Join-Path $caseDir 'PlumeWatch.lnk') 'other-app'
        }
        $output = & $runtime -NoProfile -ExecutionPolicy Bypass -File $wrapper 2>&1
        $actual = $LASTEXITCODE
        $expected = $cases[$case]
        if ([Environment]::OSVersion.Platform -ne 'Win32NT') { $expected = $expected % 256 }
        if ($actual -ne $expected) { throw "${case}: exit $actual instead of $expected. $output" }
        $calls = if (Test-Path $env:PW_TEST_LOG) { Get-Content $env:PW_TEST_LOG -Raw } else { '' }
        if (($cases[$case] -eq 0) -ne ($calls -match 'shortcut saved')) {
            throw "${case}: shortcut created before success, or missing after success. $output"
        }
        if ($cases[$case] -ne 0 -and "$output" -match 'Installation and model checks passed') {
            throw "${case}: false success message"
        }
        if ($case -eq 'enable_wsl' -and $calls -notmatch 'elevated & wsl.exe --install --no-distribution;') {
            throw 'WSL enablement must not install Ubuntu as the elevated account.'
        }
        if ($case -eq 'wsl1_decline' -and $calls -match '--set-version') { throw 'Declined conversion ran.' }
        if ($case -eq 'path_failed' -and "$output" -notmatch 'Ubuntu could not translate installer path') {
            throw 'A WSL path error must identify path conversion, not blame ZIP extraction.'
        }
        Write-Host "PASS $case"
    }
    Write-Host "PowerShell syntax and $($cases.Count) mocked installer scenarios passed."
}
finally {
    $env:LOCALAPPDATA = $previousLocalAppData
    Remove-Item -LiteralPath $temp -Recurse -Force
    Remove-Item Env:PW_TEST_CASE, Env:PW_TEST_LOG, Env:PW_TEST_DESKTOP, Env:PW_TEST_INSTALLER -ErrorAction SilentlyContinue
}
