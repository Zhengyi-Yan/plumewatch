# Run with Windows PowerShell 5.1. Real CMD, mocked WSL/PowerShell executables;
# no distribution, Python environment, server, or browser is changed.
param([string]$LauncherPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'Start Dashboard.bat'))
$ErrorActionPreference = 'Stop'
$source = $LauncherPath
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temp = Join-Path $tempBase ('plumewatch-launcher-test-' + [guid]::NewGuid())
$savedEnvironment = @{}
foreach ($key in @('PATH', 'PW_TEST_DIR', 'PW_TEST_PHASE', 'PW_TEST_CODE', 'ERRORLEVEL')) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$mock = @'
using System;
using System.Diagnostics;
using System.IO;
class LauncherMock {
    static int Main(string[] args) {
        string name = Path.GetFileNameWithoutExtension(Process.GetCurrentProcess().MainModule.FileName);
        string dir = Environment.GetEnvironmentVariable("PW_TEST_DIR");
        string failure = Environment.GetEnvironmentVariable("PW_TEST_PHASE");
        int code = int.Parse(Environment.GetEnvironmentVariable("PW_TEST_CODE"));
        if (name == "where") return failure == "where" ? code : 0;
        if (name == "powershell") {
            bool browser = string.Join(" ", args).Contains("Start-Process");
            string phase = browser ? "browser" : "port";
            File.WriteAllText(Path.Combine(dir, phase + ".txt"), "called");
            return failure == phase ? code : 0;
        }
        string command = string.Join(" ", args);
        string wslPhase = command.Contains("/bin/true") ? "probe" :
                         command.Contains("bash") ? "prerequisites" : "server";
        File.AppendAllText(Path.Combine(dir, "wsl.txt"), wslPhase + "\n");
        if (args.Length < 4 || args[0] != "-d" || args[1] != "Ubuntu" ||
            Environment.CommandLine.Contains("-d \"Ubuntu\"")) {
            Console.Error.WriteLine("Distribution must reach WSL without CMD quotes.");
            return -1;
        }
        if (wslPhase == "probe") {
            if (args[2] != "--exec" || args[3] != "/bin/true") return 98;
        } else {
            if (args[2] != "--cd" || args[3] != "~/projects/repo with spaces & (review)") {
                Console.Error.WriteLine("Linux repository path was split or changed.");
                return 99;
            }
        }
        return failure == wslPhase ? code : 0;
    }
}
'@
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $bin = Join-Path $temp 'bin'
    New-Item -ItemType Directory -Path $bin | Out-Null
    $exe = Join-Path $bin 'wsl.exe'
    Add-Type -TypeDefinition $mock -OutputAssembly $exe -OutputType ConsoleApplication
    Copy-Item -LiteralPath $exe -Destination (Join-Path $bin 'powershell.exe')
    Copy-Item -LiteralPath $exe -Destination (Join-Path $bin 'where.exe')
    $fixture = Join-Path $temp 'launcher folder with spaces & (review)'
    New-Item -ItemType Directory -Path $fixture | Out-Null
    $launcher = Join-Path $fixture 'Start Dashboard.bat'
    $text = [IO.File]::ReadAllText($source).Replace('PW_REPO=~/projects/plumewatch',
                                               'PW_REPO=~/projects/repo with spaces & (review)')
    [IO.File]::WriteAllText($launcher, ($text -replace '\r?\n', "`r`n"), [Text.Encoding]::ASCII)
    $env:PATH = $bin + ';' + $savedEnvironment['PATH']
    # An inherited ERRORLEVEL variable shadows CMD's dynamic exit code.
    Remove-Item Env:ERRORLEVEL -ErrorAction SilentlyContinue
    $cases = @(
        @{ Name = 'success'; Phase = ''; Code = 0; Calls = 'probe,prerequisites,server'; Starts = $true }
        @{ Name = 'missing_wsl'; Phase = 'where'; Code = 1; Calls = ''; Starts = $false }
    )
    foreach ($phase in @('probe', 'prerequisites', 'port', 'server')) {
        foreach ($code in @(1, -1, -2147467259)) {
            $calls = switch ($phase) {
                probe { 'probe' }
                server { 'probe,prerequisites,server' }
                default { 'probe,prerequisites' }
            }
            $cases += @{ Name = "${phase}_${code}"; Phase = $phase; Code = $code;
                         Calls = $calls; Starts = ($phase -eq 'server') }
        }
    }
    foreach ($case in $cases) {
        $caseDir = Join-Path $temp $case.Name
        New-Item -ItemType Directory -Path $caseDir | Out-Null
        $env:PW_TEST_DIR = $caseDir
        $env:PW_TEST_PHASE = $case.Phase
        $env:PW_TEST_CODE = [string]$case.Code
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = $env:ComSpec
        $info.Arguments = '/d /c ""' + $launcher + '""'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::Start($info)
        $process.StandardInput.Close() # Allow PAUSE on failure to finish unattended.
        if (-not $process.WaitForExit(10000)) {
            $process.Kill()
            throw "$($case.Name): launcher hung"
        }
        $output = $process.StandardOutput.ReadToEnd() + $process.StandardError.ReadToEnd()
        $actual = $process.ExitCode
        $process.Dispose()
        if ($actual -ne $case.Code) {
            throw "$($case.Name): exit $actual instead of $($case.Code). $output"
        }
        $callsPath = Join-Path $caseDir 'wsl.txt'
        $calls = if (Test-Path -LiteralPath $callsPath) { (Get-Content -LiteralPath $callsPath) -join ',' } else { '' }
        if ($calls -ne $case.Calls) { throw "$($case.Name): unexpected WSL calls: $calls. $output" }
        if (($output -match 'Starting PlumeWatch') -ne $case.Starts) {
            throw "$($case.Name): incorrect startup announcement. $output"
        }
        if (-not $case.Starts -and (Test-Path -LiteralPath (Join-Path $caseDir 'browser.txt'))) {
            throw "$($case.Name): browser started after a failed check"
        }
        if ($case.Phase -in @('where', 'probe', 'prerequisites') -and
            (Test-Path -LiteralPath (Join-Path $caseDir 'port.txt'))) {
            throw "$($case.Name): port check ran after failed prerequisites"
        }
        if ($case.Starts) {
            # START /B is asynchronous. Wait briefly for the mock browser to exit.
            $browserPath = Join-Path $caseDir 'browser.txt'
            for ($i = 0; $i -lt 50 -and -not (Test-Path -LiteralPath $browserPath); $i++) {
                Start-Sleep -Milliseconds 20
            }
            if (-not (Test-Path -LiteralPath $browserPath)) { throw 'Browser helper was not launched.' }
        }
        Write-Host "PASS $($case.Name)"
    }
    Write-Host "$($cases.Count) launcher scenarios passed in real CMD."
}
finally {
    foreach ($key in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
    }
    $resolvedTemp = [IO.Path]::GetFullPath($temp)
    if (-not $resolvedTemp.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path $resolvedTemp -Leaf) -notlike 'plumewatch-launcher-test-*') {
        throw 'Refusing cleanup outside the launcher test directory.'
    }
    if (Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
}
