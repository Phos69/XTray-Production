param(
    [string]$Version = "",
    [string]$InnoSetupCompiler = "",
    [string]$SourceExe = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
}

function Get-XTrayVersion {
    param([string]$RepoRoot)

    $versionFile = Join-Path $RepoRoot "packaging\XTray.version"
    $text = Get-Content -LiteralPath $versionFile -Raw
    $match = [regex]::Match($text, "ProductVersion[`"']\s*,\s*[`"']([^`"']+)[`"']")
    if ($match.Success) {
        return $match.Groups[1].Value
    }
    $pyproject = Join-Path $RepoRoot "packages\xtray\pyproject.toml"
    $projectText = Get-Content -LiteralPath $pyproject -Raw
    $projectMatch = [regex]::Match($projectText, "(?m)^version\s*=\s*`"([^`"]+)`"")
    if ($projectMatch.Success) {
        return $projectMatch.Groups[1].Value
    }
    throw "Could not determine XTray version."
}

function Find-InnoSetupCompiler {
    param([string]$Requested)

    if ($Requested) {
        if (-not (Test-Path -LiteralPath $Requested)) {
            throw "Inno Setup compiler not found: $Requested"
        }
        return (Resolve-Path -LiteralPath $Requested).ProviderPath
    }

    $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }

    throw "ISCC.exe not found. Install Inno Setup 6 or pass -InnoSetupCompiler."
}

$repoRoot = Resolve-RepoRoot
if (-not $Version) {
    $Version = Get-XTrayVersion -RepoRoot $repoRoot
}
if (-not $SourceExe) {
    $SourceExe = Join-Path $repoRoot "dist\XTray.exe"
}
if (-not (Test-Path -LiteralPath $SourceExe)) {
    throw "Missing runtime executable: $SourceExe. Build packaging\XTray.spec first."
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot "dist\installer"
}

$compiler = Find-InnoSetupCompiler -Requested $InnoSetupCompiler
$iss = Join-Path $repoRoot "packaging\XTray.iss"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

& $compiler `
    "/DAppVersion=$Version" `
    "/DSourceExe=$SourceExe" `
    "/O$OutputDir" `
    $iss

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

$installer = Join-Path $OutputDir "XTray-Setup-$Version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Expected installer was not created: $installer"
}

Write-Host "Installer created: $installer"
