@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo === Desktop Toolkit P2P 中转一键部署 ===
echo 目录: %CD%
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Node.js。请先安装: https://nodejs.org/
  pause
  exit /b 1
)

echo [1/3] 检查 Cloudflare 登录...
call npx --yes wrangler whoami
if errorlevel 1 (
  echo.
  echo 未登录，即将打开浏览器登录 Cloudflare...
  call npx --yes wrangler login
)

echo.
echo [2/3] 部署 Worker + Durable Objects 房间...
call npx --yes wrangler deploy
if errorlevel 1 (
  echo.
  echo [失败] 部署出错。若提示 free plan migration，请确认 wrangler.toml 含:
  echo   new_sqlite_classes = ["Room"]
  pause
  exit /b 1
)

echo.
echo [3/3] 自检 /health ...
for /f "tokens=*" %%U in ('powershell -NoProfile -Command "(Get-Content wrangler.toml | Select-String -Pattern '^name\s*=').ToString() -replace '.*\"([^\"]+)\".*','$1'"') do set WNAME=%%U
if "%WNAME%"=="" set WNAME=desktop-toolkit-p2p

powershell -NoProfile -Command ^
  "$name='%WNAME%'; $who=npx --yes wrangler whoami 2>$null; $url=\"https://$name.christiancag-fr.workers.dev/health\"; try { $r=Invoke-RestMethod $url -TimeoutSec 15; $r | ConvertTo-Json -Compress; if ($r.durable_rooms) { Write-Host \"OK $url durable_rooms=true\" -ForegroundColor Green } else { Write-Host \"WARN durable_rooms=false\" -ForegroundColor Yellow } } catch { Write-Host \"Probe $url failed: $_\" -ForegroundColor Yellow; Write-Host \"请打开 Cloudflare 控制台确认 workers.dev 子域\" }"

echo.
echo 部署成功后，把 wrangler 输出的 https://*.workers.dev 填到应用「中转地址」。
echo 浏览器自检请用 https://（不是 wss://）加 /health
echo.
pause
