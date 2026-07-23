param(
    [Parameter(Mandatory=$true)][ValidateSet("installer","update","dashboard")][string]$Target,
    [string]$OutputDir = "$PSScriptRoot\..\dist"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

python -m pip install --requirement requirements-dev.txt
python -m pytest -q
python -m compileall -q dashboard.py template tools tests

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if ($Target -eq "dashboard") {
    pyinstaller --noconfirm --clean --onefile --noconsole --name DMS_LectorCedulas_Dashboard `
        --paths template --hidden-import assets.runtime.hardened.license_service dashboard.py
    Copy-Item "dist\DMS_LectorCedulas_Dashboard.exe" $OutputDir -Force
    exit 0
}

Write-Host "Los builds de cliente y update se generan desde dashboard.py."
Write-Host "El dashboard emite licencias Ed25519 al crear o renovar cada cliente."
Write-Host "Destino seleccionado: $Target; carpeta de salida: $OutputDir"
