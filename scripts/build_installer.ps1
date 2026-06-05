param(
    [string]$Version = "",
    [string]$InnoSetupCompiler = "",
    [string]$SourceExe = "",
    [string]$BackendExe = "",
    [string]$OutputDir = "",
    [string]$DotnetPath = "",
    [string]$PyInstallerPath = "",
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [bool]$SelfContained = $true,
    [switch]$SkipBuild
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

function Find-Dotnet {
    param([string]$Requested)

    if ($Requested) {
        if (-not (Test-Path -LiteralPath $Requested)) {
            throw "dotnet executable not found: $Requested"
        }
        return (Resolve-Path -LiteralPath $Requested).ProviderPath
    }
    $cmd = Get-Command "dotnet" -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "dotnet was not found. Install the .NET 8 SDK or pass -DotnetPath."
    }
    $sdks = & $cmd.Source --list-sdks
    if (-not $sdks) {
        throw "No .NET SDKs were found. Install the .NET 8 SDK to publish the native tray."
    }
    return $cmd.Source
}

function Find-PyInstaller {
    param(
        [string]$RepoRoot,
        [string]$Requested
    )

    if ($Requested) {
        if (-not (Test-Path -LiteralPath $Requested)) {
            throw "PyInstaller executable not found: $Requested"
        }
        return (Resolve-Path -LiteralPath $Requested).ProviderPath
    }
    $venv = Join-Path $RepoRoot ".venv\Scripts\pyinstaller.exe"
    if (Test-Path -LiteralPath $venv) {
        return (Resolve-Path -LiteralPath $venv).ProviderPath
    }
    $cmd = Get-Command "pyinstaller" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "PyInstaller was not found. Install requirements in .venv or pass -PyInstallerPath."
}

function Publish-NativeTray {
    param(
        [string]$RepoRoot,
        [string]$Dotnet,
        [string]$Configuration,
        [string]$Runtime,
        [bool]$SelfContained
    )

    $project = Join-Path $RepoRoot "apps\XTray.Tray\XTray.Tray.csproj"
    $publishDir = Join-Path $RepoRoot "dist\native-tray"
    New-Item -ItemType Directory -Force -Path $publishDir | Out-Null
    $selfContainedValue = $SelfContained.ToString().ToLowerInvariant()
    & $Dotnet publish $project `
        --configuration $Configuration `
        --runtime $Runtime `
        --self-contained $selfContainedValue `
        /p:PublishSingleFile=true `
        /p:IncludeNativeLibrariesForSelfExtract=true `
        /p:EnableCompressionInSingleFile=true `
        --output $publishDir | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet publish failed with exit code $LASTEXITCODE."
    }
    $exe = Join-Path $publishDir "XTray.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "dotnet publish did not create: $exe"
    }
    return $exe
}

function Publish-PythonBackend {
    param(
        [string]$RepoRoot,
        [string]$PyInstaller
    )

    $spec = Join-Path $RepoRoot "packaging\XTray.Backend.spec"
    Push-Location $RepoRoot
    try {
        & $PyInstaller $spec --clean --noconfirm | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller backend build failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $exe = Join-Path $RepoRoot "dist\XTray.Backend.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "PyInstaller did not create: $exe"
    }
    return $exe
}

$repoRoot = Resolve-RepoRoot
if (-not $Version) {
    $Version = Get-XTrayVersion -RepoRoot $repoRoot
}

if ($SkipBuild) {
    if (-not $SourceExe) {
        $SourceExe = Join-Path $repoRoot "dist\native-tray\XTray.exe"
    }
    if (-not $BackendExe) {
        $BackendExe = Join-Path $repoRoot "dist\XTray.Backend.exe"
    }
} else {
    if (-not $SourceExe) {
        $dotnet = Find-Dotnet -Requested $DotnetPath
        $SourceExe = Publish-NativeTray `
            -RepoRoot $repoRoot `
            -Dotnet $dotnet `
            -Configuration $Configuration `
            -Runtime $Runtime `
            -SelfContained $SelfContained
    }
    if (-not $BackendExe) {
        $pyInstaller = Find-PyInstaller -RepoRoot $repoRoot -Requested $PyInstallerPath
        $BackendExe = Publish-PythonBackend -RepoRoot $repoRoot -PyInstaller $pyInstaller
    }
}

if (-not (Test-Path -LiteralPath $SourceExe)) {
    throw "Missing native tray executable: $SourceExe"
}
if (-not (Test-Path -LiteralPath $BackendExe)) {
    throw "Missing Python backend executable: $BackendExe"
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
    "/DBackendExe=$BackendExe" `
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
