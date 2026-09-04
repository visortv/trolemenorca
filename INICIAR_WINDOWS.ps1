$ErrorActionPreference="Stop"
$Port=5055
$StateDir=Join-Path $env:LOCALAPPDATA "MenorcaBus"
$PidFile=Join-Path $StateDir "server.pid"
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
Set-Location $PSScriptRoot

if(Test-Path $PidFile){
  $old=(Get-Content $PidFile -Raw).Trim()
  if($old -match '^\d+$'){
    $p=Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue
    if($p){ Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 500 }
  }
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

$conns=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach($c in $conns){
  $p=Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
  if($p -and $p.ProcessName -match '^python'){
    try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Start-Sleep -Milliseconds 400 }
    catch {
      Write-Host "No se puede cerrar el Python anterior en 5055. Ejecuta este BAT como administrador una vez."
      Read-Host "ENTER"; exit 1
    }
  }
}

if(-not (Test-Path ".\venv\Scripts\python.exe")){ py -m venv venv }
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check | Out-Host

Write-Host ""
Write-Host "1/2 SINCRONIZANDO DIRECTAMENTE CADA LINEA TMSA (paradas + horarios)..."
& ".\venv\Scripts\python.exe" ".\sync_tmsa.py"
$syncCode=$LASTEXITCODE
if($syncCode -ne 0){
  Write-Host "La sincronizacion ha fallado y no hay snapshot valido."
  Read-Host "ENTER"; exit 1
}

Write-Host ""
Write-Host "2/2 ARRANCANDO MENORCA BUS..."
$proc=Start-Process ".\venv\Scripts\python.exe" -ArgumentList "app.py" -WorkingDirectory $PSScriptRoot -PassThru
Set-Content $PidFile $proc.Id -Encoding ascii
Start-Sleep -Seconds 1
Start-Process "http://127.0.0.1:5055/"
Write-Host "Menorca Bus V10.1 iniciado PID $($proc.Id)"
