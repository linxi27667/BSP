[CmdletBinding()]
param(
    [ValidateSet('Detect', 'Build', 'Flash', 'CaptureRtt', 'Cycle')]
    [string]$Action = 'Detect',
    [string]$ProjectPath = (Get-Location).Path,
    [string]$Uvprojx,
    [string]$Firmware,
    [string]$Device,
    [ValidateSet('SWD', 'JTAG', 'FINE')][string]$Interface = 'SWD',
    [ValidateRange(1, 50000)][int]$Speed = 4000,
    [string]$UsbSerial,
    [ValidateRange(0, 15)][int]$RttChannel = 0,
    [ValidateRange(1, 3600)][int]$CaptureSeconds = 30,
    [ValidateRange(1, 10)][int]$RttConnectRetries = 3,
    [ValidateRange(1, 30)][int]$RttRetryDelaySeconds = 2,
    [string]$KeilExe,
    [string]$JLinkExe,
    [string]$JLinkRttLogger,
    [string]$EvidenceDirectory,
    [switch]$ConfirmOutputSafe,
    [switch]$AllowBuildWarnings,
    [string]$TestCommand,
    [string[]]$TestArguments = @(),
    [ValidateRange(0, 60)][int]$TestDelaySeconds = 2,
    [string[]]$RequiredLogPattern = @(),
    [string[]]$ForbiddenLogPattern = @('HardFault', 'FAULT:', 'assert failed')
)

$ErrorActionPreference = 'Stop'

function Find-FirstExisting([string[]]$Candidates) {
    return $Candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
}

function Find-SeggerTool([string]$Name) {
    $candidates = @(
        "C:\Program Files\SEGGER\JLink\$Name",
        "C:\Program Files (x86)\SEGGER\JLink\$Name"
    )
    $candidates += Get-ChildItem 'C:\Program Files\SEGGER' -Directory `
        -Filter 'JLink*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName $Name }
    return Find-FirstExisting $candidates
}

function Require-JLinkParameters {
    if (-not $Device) { throw '-Device is required for J-Link actions.' }
    if (-not $UsbSerial) {
        throw '-UsbSerial is required so the script never selects an ambiguous probe.'
    }
}

function Resolve-KeilProject {
    if ($Uvprojx) {
        return (Resolve-Path -LiteralPath $Uvprojx).Path
    }
    $projects = @(Get-ChildItem -LiteralPath $ProjectPath -Recurse -File `
        -Include '*.uvprojx','*.uvproj' -ErrorAction SilentlyContinue)
    if ($projects.Count -ne 1) {
        $projects | Select-Object FullName
        throw "Found $($projects.Count) Keil projects; pass -Uvprojx explicitly."
    }
    return $projects[0].FullName
}

function Resolve-Firmware {
    if ($Firmware) { return (Resolve-Path -LiteralPath $Firmware).Path }
    $images = @(Get-ChildItem -LiteralPath $ProjectPath -Recurse -File `
        -Include '*.hex','*.elf','*.axf' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    if ($images.Count -eq 0) { throw 'No HEX/ELF/AXF found; pass -Firmware explicitly.' }
    if ($images.Count -gt 1) {
        Write-Warning "Multiple firmware images found; selecting newest: $($images[0].FullName)"
    }
    return $images[0].FullName
}

function Invoke-KeilBuild([string]$LogPath) {
    $project = Resolve-KeilProject
    Write-Host "[BUILD] $project"
    $buildProcess = Start-Process -FilePath $script:KeilExe `
        -ArgumentList @('-b', "`"$project`"", '-j0', '-o', "`"$LogPath`"") `
        -Wait -PassThru -NoNewWindow
    $text = Get-Content -Raw -LiteralPath $LogPath
    $summary = [regex]::Match($text, '(\d+) Error\(s\), (\d+) Warning\(s\)')
    if (-not $summary.Success) { throw "Keil summary missing: $LogPath" }
    $errors = [int]$summary.Groups[1].Value
    $warnings = [int]$summary.Groups[2].Value
    if ($errors -ne 0 -or (-not $AllowBuildWarnings -and $warnings -ne 0)) {
        throw "Keil build rejected: errors=$errors warnings=$warnings log=$LogPath"
    }
    Write-Host "[BUILD] PASS errors=$errors warnings=$warnings"
}

function Invoke-JLinkFlash([string]$Image, [string]$LogPath) {
    Require-JLinkParameters
    if (-not $ConfirmOutputSafe) {
        throw 'Flash/Cycle requires -ConfirmOutputSafe after checking motors, relays and power outputs.'
    }
    $commandFile = Join-Path ([IO.Path]::GetTempPath()) `
        ("jlink-cycle-{0}.jlink" -f [guid]::NewGuid())
    try {
        @('r', 'h', "loadfile `"$Image`"", 'r', 'g', 'q') |
            Set-Content -LiteralPath $commandFile -Encoding ascii
        $args = @('-USB', $UsbSerial, '-Device', $Device, '-If', $Interface,
                  '-Speed', $Speed, '-AutoConnect', 1,
                  '-CommandFile', "`"$commandFile`"", '-Log', "`"$LogPath`"")
        Write-Host "[FLASH] device=$Device probe=$UsbSerial image=$Image"
        $flashProcess = Start-Process -FilePath $script:JLinkExe `
            -ArgumentList $args -Wait -PassThru -NoNewWindow
        $text = Get-Content -Raw -LiteralPath $LogPath
        if ($text -notmatch 'O\.K\.' -or
            $text -match '(?i)verify failed|cannot connect|connection failed|error:') {
            throw "J-Link program/verify failed: $LogPath"
        }
        Write-Host '[FLASH] PASS program/verify'
    }
    finally {
        Remove-Item -LiteralPath $commandFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-RttCapture([string]$LogPath) {
    Require-JLinkParameters
    $args = @('-Device', $Device, '-If', $Interface, '-Speed', $Speed,
              '-USB', $UsbSerial, '-RTTChannel', $RttChannel, "`"$LogPath`"")
    Write-Host "[RTT] channel=$RttChannel duration=${CaptureSeconds}s log=$LogPath"
    $process = $null
    for ($attempt = 1; $attempt -le $RttConnectRetries; $attempt++) {
        Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $script:JLinkRttLogger `
            -ArgumentList $args -PassThru -NoNewWindow
        Start-Sleep -Milliseconds 800
        $process.Refresh()
        $hasData = (Test-Path -LiteralPath $LogPath) -and
                   (Get-Item -LiteralPath $LogPath).Length -gt 0
        if (-not $process.HasExited -or $hasData) { break }
        if ($attempt -lt $RttConnectRetries) {
            Write-Warning "RTT connect attempt $attempt failed; retrying in ${RttRetryDelaySeconds}s."
            Start-Sleep -Seconds $RttRetryDelaySeconds
        }
    }
    $hasData = (Test-Path -LiteralPath $LogPath) -and
               (Get-Item -LiteralPath $LogPath).Length -gt 0
    if ($null -eq $process -or ($process.HasExited -and -not $hasData)) {
        throw "RTT failed to connect after $RttConnectRetries attempts."
    }
    try {
        if ($TestCommand) {
            Start-Sleep -Seconds $TestDelaySeconds
            Write-Host "[TEST] $TestCommand $($TestArguments -join ' ')"
            & $TestCommand @TestArguments
            if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
                throw "Test command failed with exit code $LASTEXITCODE"
            }
        }
        $deadline = [DateTime]::UtcNow.AddSeconds($CaptureSeconds)
        while (-not $process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 200
            $process.Refresh()
        }
    }
    finally {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }
    }
    if (-not (Test-Path -LiteralPath $LogPath)) {
        throw "RTT output was not created: $LogPath"
    }
    $text = Get-Content -Raw -LiteralPath $LogPath
    $failures = @()
    foreach ($pattern in $RequiredLogPattern) {
        if ($text -notmatch $pattern) { $failures += "required pattern missing: $pattern" }
    }
    foreach ($pattern in $ForbiddenLogPattern) {
        if ($text -match $pattern) { $failures += "forbidden pattern found: $pattern" }
    }
    if ($failures) { throw "RTT acceptance failed: $($failures -join '; ')" }
    Write-Host "[RTT] PASS bytes=$((Get-Item -LiteralPath $LogPath).Length)"
}

$resolvedProject = (Resolve-Path -LiteralPath $ProjectPath).Path
$ProjectPath = $resolvedProject
if (-not $EvidenceDirectory) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $EvidenceDirectory = Join-Path $ProjectPath "logs\jlink-cycle-$stamp"
}
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null

if (-not $KeilExe) {
    $KeilExe = Find-FirstExisting @(
        'C:\Keil_v5\UV4\UV4.exe', 'C:\Keil\UV4\UV4.exe',
        'D:\Keil_v5\UV4\UV4.exe', 'E:\Keil_v5\UV4\UV4.exe'
    )
}
if (-not $JLinkExe) { $JLinkExe = Find-SeggerTool 'JLink.exe' }
if (-not $JLinkRttLogger) { $JLinkRttLogger = Find-SeggerTool 'JLinkRTTLogger.exe' }

$script:KeilExe = $KeilExe
$script:JLinkExe = $JLinkExe
$script:JLinkRttLogger = $JLinkRttLogger
$buildLog = Join-Path $EvidenceDirectory 'keil-build.log'
$flashLog = Join-Path $EvidenceDirectory 'jlink-flash.log'
$rttLog = Join-Path $EvidenceDirectory 'rtt.log'

if ($Action -eq 'Detect') {
    [pscustomobject]@{
        ProjectPath = $ProjectPath
        KeilExe = $KeilExe
        JLinkExe = $JLinkExe
        JLinkRttLogger = $JLinkRttLogger
        KeilProjects = @(Get-ChildItem $ProjectPath -Recurse -File -Include '*.uvprojx','*.uvproj').FullName
        FirmwareImages = @(Get-ChildItem $ProjectPath -Recurse -File -Include '*.hex','*.elf','*.axf').FullName
    } | Format-List
    return
}

if ($Action -in @('Build', 'Cycle')) {
    if (-not $KeilExe) { throw 'Keil UV4.exe not found; pass -KeilExe.' }
    Invoke-KeilBuild $buildLog
}
if ($Action -in @('Flash', 'Cycle')) {
    if (-not $JLinkExe) { throw 'JLink.exe not found; pass -JLinkExe.' }
    Invoke-JLinkFlash (Resolve-Firmware) $flashLog
}
if ($Action -in @('CaptureRtt', 'Cycle')) {
    if (-not $JLinkRttLogger) { throw 'JLinkRTTLogger.exe not found; pass -JLinkRttLogger.' }
    Invoke-RttCapture $rttLog
}

Write-Host "[CYCLE] PASS evidence=$EvidenceDirectory"
