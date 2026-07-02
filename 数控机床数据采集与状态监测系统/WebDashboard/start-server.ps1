# 启动 Web 后端（看板 + OPC UA 轮询 + 采集配置/控制 API）。在独立 PowerShell 窗口运行，Ctrl+C 停止。
$ErrorActionPreference = 'Stop'
$api = Join-Path $PSScriptRoot 'api'
if (-not (Test-Path (Join-Path $api 'node_modules'))) {
  Write-Host '首次运行：安装依赖 npm install …' -ForegroundColor Yellow
  Push-Location $api; npm install; Pop-Location
}
Write-Host '启动后端 http://localhost:4000  （Ctrl+C 停止）' -ForegroundColor Green
Push-Location $api
node src/server.js
Pop-Location
