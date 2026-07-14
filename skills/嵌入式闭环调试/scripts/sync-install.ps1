[CmdletBinding()]
param(
    [string]$SkillRoot,
    [string]$CodexSkills = "$env:USERPROFILE\.codex\skills",
    [string]$ClaudeSkills = "$env:USERPROFILE\.claude\skills",
    [string]$TraeSkills = "$env:USERPROFILE\.trae\skills",
    [string]$TraeCnSkills = "$env:USERPROFILE\.trae-cn\skills"
)

$ErrorActionPreference = "Stop"

if (-not $SkillRoot) {
    $SkillRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

if (-not (Test-Path -LiteralPath (Join-Path $SkillRoot "SKILL.md"))) {
    throw "SkillRoot does not contain SKILL.md: $SkillRoot"
}

$skillName = Split-Path $SkillRoot -Leaf
$destinations = @(
    (Join-Path $CodexSkills $skillName),
    (Join-Path $ClaudeSkills $skillName),
    (Join-Path $TraeSkills $skillName),
    (Join-Path $TraeCnSkills $skillName)
)

foreach ($dest in $destinations) {
    $parent = Split-Path $dest -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $resolvedDest = Resolve-Path -LiteralPath $dest -ErrorAction SilentlyContinue
    $resolvedSkill = Resolve-Path -LiteralPath $SkillRoot -ErrorAction Stop
    if ($resolvedDest -and $resolvedDest.Path -eq $resolvedSkill.Path) {
        Write-Host "Skip self-sync: $dest"
        continue
    }
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
    }
    Copy-Item -LiteralPath $SkillRoot -Destination $dest -Recurse -Force
    Write-Host "Synced: $dest"
}
