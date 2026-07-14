[CmdletBinding()]
param(
    [string]$ProjectPath = (Get-Location).Path
)

$ErrorActionPreference = "SilentlyContinue"

function Find-FirstExisting {
    param([string[]]$Paths)
    foreach ($p in $Paths) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            return (Resolve-Path -LiteralPath $p).Path
        }
    }
    return $null
}

$espIdf = Find-FirstExisting @(
    "E:\MCU\esp32\.espressif\v5.5.3\esp-idf",
    "C:\Espressif\frameworks\esp-idf-v5.5.3",
    "$env:USERPROFILE\esp\v5.5.3\esp-idf",
    "$env:USERPROFILE\esp\esp-idf"
)

$keil = Find-FirstExisting @(
    "C:\Keil_v5\UV4\UV4.exe",
    "C:\Keil\UV4\UV4.exe",
    "D:\Keil_v5\UV4\UV4.exe",
    "E:\Keil_v5\UV4\UV4.exe"
)
if (-not $keil) {
    $keil = Get-ChildItem -Path "C:\","D:\","E:\" -Filter "UV4.exe" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}

$jlinkTools = @()
$jlinkRoots = @(
    "C:\Program Files\SEGGER\JLink",
    "C:\Program Files (x86)\SEGGER\JLink",
    "E:\MCU\BSP"
)
foreach ($root in $jlinkRoots) {
    foreach ($exe in @("JLinkRTTLogger.exe","JLinkRTTClient.exe","JLinkGDBServerCL.exe","JLink.exe","JLinkExe.exe")) {
        $p = Join-Path $root $exe
        if (Test-Path -LiteralPath $p) { $jlinkTools += (Resolve-Path -LiteralPath $p).Path }
    }
}

$serialPorts = @()
try {
    $serialPorts = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
} catch {}

$pnpPorts = @()
try {
    $pnpPorts = Get-PnpDevice -Class Ports | Select-Object Status,FriendlyName,InstanceId
} catch {}

$project = Resolve-Path -LiteralPath $ProjectPath -ErrorAction SilentlyContinue
$projectRoot = if ($project) { $project.Path } else { $ProjectPath }

$idfProjects = @()
$keilProjects = @()
if (Test-Path -LiteralPath $projectRoot) {
    $ignoredDirs = "\\(\.git|build|build_ninja|managed_components|esp-dl-ref)($|\\)"
    if ((Test-Path -LiteralPath (Join-Path $projectRoot "CMakeLists.txt") -PathType Leaf) -and
        ((Test-Path -LiteralPath (Join-Path $projectRoot "sdkconfig") -PathType Leaf) -or
         (Test-Path -LiteralPath (Join-Path $projectRoot "sdkconfig.defaults") -PathType Leaf))) {
        $idfProjects += (Join-Path $projectRoot "CMakeLists.txt")
    }
    $idfProjects += @(Get-ChildItem -Path $projectRoot -Recurse -Filter "CMakeLists.txt" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch $ignoredDirs -and
            ((Test-Path -LiteralPath (Join-Path $_.DirectoryName "sdkconfig") -PathType Leaf) -or
             (Test-Path -LiteralPath (Join-Path $_.DirectoryName "sdkconfig.defaults") -PathType Leaf))
        } |
        Select-Object -First 20 -ExpandProperty FullName)
    $idfProjects = @($idfProjects | Select-Object -Unique)
    $keilProjects = @(Get-ChildItem -Path $projectRoot -Recurse -File -Include "*.uvprojx","*.uvproj" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch $ignoredDirs } |
        Select-Object -First 30 -ExpandProperty FullName)
}

[ordered]@{
    timestamp = (Get-Date).ToString("s")
    projectPath = $projectRoot
    espIdfPath = $espIdf
    espIdfExport = if ($espIdf) { Join-Path $espIdf "export.ps1" } else { $null }
    keilUv4 = $keil
    jlinkTools = $jlinkTools
    serialPorts = $serialPorts
    pnpPorts = $pnpPorts
    espIdfProjectHints = $idfProjects
    keilProjectHints = $keilProjects
} | ConvertTo-Json -Depth 6
