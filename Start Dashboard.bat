@echo off
setlocal
rem Change these only if your Ubuntu distribution or Linux checkout differs.
set "PW_DISTRO=Ubuntu"
set "PW_REPO=~/projects/plumewatch"
set "PW_PORT=8000"

where wsl.exe >nul 2>&1
if errorlevel 1 (
  echo WSL is not available. Complete the Windows installation in README.md first.
  pause
  exit /b 1
)

wsl.exe -d "%PW_DISTRO%" --cd "%PW_REPO%" -- bash -c "test -f app.py && test -x .venv/bin/python && test -x experiments/unet/.venv/bin/python && test -f data/processed/multiclass_rf_v2_20260930/model.pkl && test -f experiments/unet/outputs/expanded_all_data_20260930/model.pt && test -f data/processed/svm_rbf_20261001/model.pkl"
if errorlevel 1 (
  echo Checkout, Python environments or models are missing. See README.md.
  echo Check PW_DISTRO and PW_REPO at the top of this file.
  pause
  exit /b 1
)

powershell.exe -NoProfile -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', [int]$env:PW_PORT); exit 1 } catch { exit 0 } finally { $client.Dispose() }"
if errorlevel 1 (
  echo Port %PW_PORT% is already in use. Stop the existing dashboard or change PW_PORT.
  pause
  exit /b 1
)

echo Starting PlumeWatch at http://localhost:%PW_PORT%
echo Keep this window open. Press Ctrl+C here to stop the dashboard.
start "" /b powershell.exe -NoProfile -Command "$url = 'http://localhost:' + $env:PW_PORT; for ($i = 0; $i -lt 30; $i++) { try { $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2; if ($response.StatusCode -eq 200) { Start-Process $url; exit 0 } } catch {} Start-Sleep -Seconds 1 }; Write-Host 'Browser did not open automatically. Check the server output and open the displayed URL manually.'"
wsl.exe -d "%PW_DISTRO%" --cd "%PW_REPO%" -- .venv/bin/python -m shiny run --host 127.0.0.1 --port %PW_PORT% app.py
if errorlevel 1 (
  echo Dashboard stopped with an error. Keep the error above for diagnosis.
  pause
)
endlocal
