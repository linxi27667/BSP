[CmdletBinding()]
param(
    [string]$ProjectPath = (Get-Location).Path,
    [string]$Uvprojx,
    [string]$KeilExe,
    [switch]$Flash,
    [string]$BuildLog,
    [string]$FlashLog
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ProjectPath)) {
    throw "ProjectPath not found: $ProjectPath"
}

if (-not $Uvprojx) {
    $candidates = Get-ChildItem -Path $ProjectPath -Recurse -Include "*.uvprojx","*.uvproj" -ErrorAction SilentlyContinue
    if ($candidates.Count -eq 1) {
        $Uvprojx = $candidates[0].FullName
    } else {
        $candidates | Select-Object FullName
        throw "Uvprojx is required when zero or multiple Keil projects are found."
    }
}
if (-not (Test-Path -LiteralPath $Uvprojx)) {
    throw "Keil project not found: $Uvprojx"
}

if (-not $KeilExe) {
    foreach ($p in @("C:\Keil_v5\UV4\UV4.exe","C:\Keil\UV4\UV4.exe","D:\Keil_v5\UV4\UV4.exe","E:\Keil_v5\UV4\UV4.exe")) {
        if (Test-Path -LiteralPath $p) { $KeilExe = $p; break }
    }
}
if (-not $KeilExe -or -not (Test-Path -LiteralPath $KeilExe)) {
    throw "UV4.exe not found. Pass -KeilExe or install Keil5."
}

$outDir = Join-Path $ProjectPath "logs"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
if (-not $BuildLog) { $BuildLog = Join-Path $outDir "keil_build.log" }
if (-not $FlashLog) { $FlashLog = Join-Path $outDir "keil_flash.log" }

& $KeilExe -b $Uvprojx -j0 -o $BuildLog
$buildCode = $LASTEXITCODE
Get-Content -Path $BuildLog -Tail 80 -ErrorAction SilentlyContinue
if ($buildCode -ne 0) { throw "Keil build failed: $BuildLog" }

if ($Flash) {
    & $KeilExe -f $Uvprojx -o $FlashLog
    $flashCode = $LASTEXITCODE
    Get-Content -Path $FlashLog -Tail 80 -ErrorAction SilentlyContinue
    if ($flashCode -ne 0) { throw "Keil flash failed: $FlashLog" }
}

Write-Host "Keil cycle completed. BuildLog=$BuildLog FlashLog=$FlashLog"
