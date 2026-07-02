# 启动 NI 振动采集【守护进程】（常驻）。它本身不立即采集，而是监听 DB collector_control.ni_run，
# 等 Web 端「开始采集」指令。在独立 PowerShell 窗口运行，可看到滚动日志；Ctrl+C 退出。
$ErrorActionPreference = 'Stop'
$dir = Join-Path $PSScriptRoot 'collector'
$exe = Join-Path $dir 'bin\Release\net472\Collector.exe'

# DB 密码：优先用已设的环境变量，否则用现场默认（改库密码就改这里或先 setx COLLECTOR_PGPASSWORD）
if (-not $env:COLLECTOR_PGPASSWORD) { $env:COLLECTOR_PGPASSWORD = '584412135lwx' }

if (-not (Test-Path $exe)) {
  Write-Host '未找到可执行体，正在编译 (dotnet build -c Release) …' -ForegroundColor Yellow
  $dotnet = 'C:\Program Files\dotnet\dotnet.exe'
  & $dotnet build (Join-Path $dir 'Collector.csproj') -c Release
}
Write-Host '采集守护进程启动。请在 http://localhost:4000 点 NI「开始」。Ctrl+C 退出。' -ForegroundColor Green
& $exe
