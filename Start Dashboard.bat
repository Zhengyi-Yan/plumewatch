@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Change these only if your Ubuntu distribution or Linux checkout differs.
set "PW_DISTRO=Ubuntu"
set "PW_REPO=~/projects/plumewatch"
set "PW_PORT=8000"

where wsl.exe >nul 2>&1
set "PW_EXIT_CODE=%ERRORLEVEL%"
if not "%PW_EXIT_CODE%"=="0" (
  echo WSL is not available. Run Install PlumeWatch.bat first; see README.md.
  pause
  exit /b %PW_EXIT_CODE%
)

rem Do not quote the distro name: WSL can treat CMD's quotes as part of the name.
rem See https://github.com/microsoft/WSL/issues/9792. Keep Linux paths quoted.
wsl.exe -d %PW_DISTRO% --exec /bin/true
set "PW_EXIT_CODE=%ERRORLEVEL%"
if not "%PW_EXIT_CODE%"=="0" (
  echo Ubuntu/WSL could not start. WSL exit code: %PW_EXIT_CODE%.
  echo Check PW_DISTRO and run wsl --list --verbose. Keep the WSL error above for diagnosis.
  pause
  exit /b %PW_EXIT_CODE%
)

wsl.exe -d %PW_DISTRO% --cd "%PW_REPO%" -- bash -c "test -f app.py && test -x .venv/bin/python && test -x experiments/unet/.venv/bin/python && test -f data/processed/multiclass_rf_v2_20260930/model.pkl && test -f experiments/unet/outputs/expanded_all_data_20260930/model.pt && test -f data/processed/svm_rbf_20261001/model.pkl"
set "PW_EXIT_CODE=%ERRORLEVEL%"
if not "%PW_EXIT_CODE%"=="0" (
  echo Installation check failed. WSL exit code: %PW_EXIT_CODE%.
  echo Checkout, Python environments or models are missing. Run Install PlumeWatch.bat to install or repair.
  echo Check PW_DISTRO and PW_REPO at the top of this file.
  pause
  exit /b %PW_EXIT_CODE%
)

powershell.exe -NoProfile -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', [int]$env:PW_PORT); exit 1 } catch { exit 0 } finally { $client.Dispose() }"
set "PW_EXIT_CODE=%ERRORLEVEL%"
if not "%PW_EXIT_CODE%"=="0" (
  echo Port %PW_PORT% is already in use. Stop the existing dashboard or change PW_PORT.
  pause
  exit /b %PW_EXIT_CODE%
)

echo Starting PlumeWatch at http://localhost:%PW_PORT%
echo Keep this window open. Press Ctrl+C here to stop the dashboard.
start "" /b powershell.exe -NoProfile -Command "$url = 'http://localhost:' + $env:PW_PORT; for ($i = 0; $i -lt 30; $i++) { try { $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2; if ($response.StatusCode -eq 200) { Start-Process $url; exit 0 } } catch {} Start-Sleep -Seconds 1 }; Write-Host 'Browser did not open automatically. Check the server output and open the displayed URL manually.'"
set "PW_EXIT_CODE=%ERRORLEVEL%"
if not "%PW_EXIT_CODE%"=="0" (
  echo Could not start the browser helper. Exit code: %PW_EXIT_CODE%.
  pause
  exit /b %PW_EXIT_CODE%
)
wsl.exe -d %PW_DISTRO% --cd "%PW_REPO%" -- .venv/bin/python -m shiny run --host 127.0.0.1 --port %PW_PORT% app.py
set "PW_EXIT_CODE=%ERRORLEVEL%"
if not "%PW_EXIT_CODE%"=="0" (
  echo Dashboard stopped with an error. WSL exit code: %PW_EXIT_CODE%.
  echo Keep the error above for diagnosis.
  pause
)
endlocal & exit /b %PW_EXIT_CODE%
