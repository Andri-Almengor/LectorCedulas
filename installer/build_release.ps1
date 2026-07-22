param(
    [Parameter(Mandatory=$true)][ValidateSet("installer","update","dashboard")][string]$Target,
    [string]$OutputDir = "$PSScriptRoot\..\dist"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

python -m pip install --requirement requirements.lock
python -m pip install --requirement requirements-dev.txt
python -m pytest -q
python -m compileall -q template tools dashboard_secure.py

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if ($Target -eq "dashboard") {
    pyinstaller --noconfirm --clean --onefile --noconsole --name DMS_LectorCedulas_Dashboard `
        --paths template --hidden-import assets.runtime.hardened.license_service dashboard_secure.py
    Copy-Item "dist\DMS_LectorCedulas_Dashboard.exe" $OutputDir -Force
    exit 0
}

Write-Host "Los builds de cliente y update se generan desde dashboard_secure.py para que las firmas usen claves privadas fuera del repositorio."
Write-Host "Destino seleccionado: $Target; carpeta de salida: $OutputDir"
