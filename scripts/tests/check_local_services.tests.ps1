$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\check_local_services.ps1'

& powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath -MySqlPort 1 -RedisPort 1 -TimeoutMilliseconds 100 2>$null
if ($LASTEXITCODE -eq 0) {
    throw 'Unavailable service ports must fail the local-service check.'
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "Available native services must pass; exit code $LASTEXITCODE."
}
