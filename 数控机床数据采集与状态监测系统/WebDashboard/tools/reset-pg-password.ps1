# 重置本机 PostgreSQL 16 的 postgres 密码（标准 trust 法，临时且自动还原）。
# 需以管理员身份运行：右键 PowerShell -> 以管理员身份运行，或在已提权的终端执行。
# 过程：备份 hba -> 本地连接临时改 trust -> 重启 -> ALTER USER 改密 -> 还原 hba -> 重启 -> 自检。
# 仅放开 127.0.0.1/::1 的本地连接，且 finally 中无条件还原；全程不开放外部访问。

$ErrorActionPreference = 'Stop'
$NewPassword = '584412135lwx'   # 改完后与 WebDashboard/api/.env 中 PGPASSWORD 一致
$pgDir   = 'C:\Program Files\PostgreSQL\16'
$dataDir = "$pgDir\data"
$hba     = "$dataDir\pg_hba.conf"
$psql    = "$pgDir\bin\psql.exe"
$svc     = 'postgresql-x64-16'

$backup = "$hba.bak_reset_$(Get-Date -Format yyyyMMdd_HHmmss)"
Copy-Item $hba $backup -Force
Write-Host "已备份 pg_hba.conf -> $backup"

try {
    # 1) 本地 host 行临时改 trust
    $orig = Get-Content $hba
    $tmp = $orig | ForEach-Object {
        if ($_ -match '^\s*host\s+all\s+all\s+(127\.0\.0\.1/32|::1/128)\s') {
            $_ -replace 'scram-sha-256|md5', 'trust'
        } else { $_ }
    }
    Set-Content -Path $hba -Value $tmp -Encoding ASCII
    Restart-Service $svc; Start-Sleep -Seconds 3
    Write-Host "已临时启用 trust 并重启服务"

    # 2) 改密码（trust 下无需旧密码）
    & $psql -U postgres -h 127.0.0.1 -d postgres -w -c "ALTER USER postgres PASSWORD '$NewPassword';"
    Write-Host "postgres 密码已重置"
}
finally {
    # 3) 无条件还原 hba 并重启
    Copy-Item $backup $hba -Force
    Restart-Service $svc; Start-Sleep -Seconds 3
    Write-Host "已还原 pg_hba.conf 并重启服务"
}

# 4) 自检 + 确保 vibration_db 存在
$env:PGPASSWORD = $NewPassword
& $psql -U postgres -h 127.0.0.1 -d postgres -w -c "SELECT version();"
$exists = (& $psql -U postgres -h 127.0.0.1 -d postgres -w -t -A -c "SELECT 1 FROM pg_database WHERE datname='vibration_db';")
if (-not $exists) {
    & $psql -U postgres -h 127.0.0.1 -d postgres -w -c "CREATE DATABASE vibration_db;"
    Write-Host "已创建数据库 vibration_db"
} else {
    Write-Host "vibration_db 已存在"
}
Write-Host "完成。密码 = $NewPassword（已与 .env 一致）"
