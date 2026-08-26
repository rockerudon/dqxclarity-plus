param(
    [switch] $NoBuild,
    [switch] $SkipNative
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$OutRoot = Join-Path $RepoRoot "local-build"
$PackageDir = Join-Path $OutRoot "dqxclarity"
$ZipPath = Join-Path $OutRoot "dqxclarity-mod.zip"
$LauncherExe = Join-Path $RepoRoot "launcher\bin\Release\net9.0-windows\win-x64\publish\dqxclarity.exe"

if (-not $NoBuild) {
    $BuildScript = Join-Path $PSScriptRoot "build-launcher.ps1"
    if ($SkipNative) {
        & $BuildScript -SkipNative
    }
    else {
        & $BuildScript
    }
}

if (-not (Test-Path $LauncherExe)) {
    throw "Launcher exe not found. Run scripts\build-launcher.ps1 first."
}

if (Test-Path $PackageDir) {
    $resolvedPackage = (Resolve-Path $PackageDir).Path
    $resolvedOut = if (Test-Path $OutRoot) { (Resolve-Path $OutRoot).Path } else { $OutRoot }
    if (-not $resolvedPackage.StartsWith($resolvedOut, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean unexpected path: $resolvedPackage"
    }
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

$AppDir = Join-Path $RepoRoot "app"
Get-ChildItem -LiteralPath $AppDir -Force | Where-Object {
    $_.Name -notin @("tests", "__pycache__") -and $_.Name -notlike "venv*"
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $PackageDir -Recurse -Force
}

# Recursive copies can contain local Python bytecode created while testing.
# It is never part of the application and may even reference deleted modules.
Get-ChildItem -LiteralPath $PackageDir -Directory -Recurse -Force |
    Where-Object Name -eq "__pycache__" |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $PackageDir -File -Recurse -Force -Include "*.pyc", "*.pyo" |
    Remove-Item -Force

foreach ($file in @("version.update", "pyproject.toml")) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot $file) -Destination $PackageDir -Force
}
# Include the default settings file in a fresh local package.
Copy-Item -LiteralPath (Join-Path $RepoRoot "user_settings.example.ini") `
    -Destination (Join-Path $PackageDir "user_settings.ini") -Force

Copy-Item -LiteralPath $LauncherExe -Destination (Join-Path $PackageDir "dqxclarity.exe") -Force

$MiscDir = Join-Path $PackageDir "misc_files"
New-Item -ItemType Directory -Force -Path $MiscDir | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "clarity_dialog.db") -Destination $MiscDir -Force

$PackageLanguagePacksDir = Join-Path $PackageDir "language-packs"
New-Item -ItemType Directory -Force -Path $PackageLanguagePacksDir | Out-Null

$SourceLanguagePacksDir = Join-Path $RepoRoot "language-packs"
$copiedSourceLanguagePacks = $false
if (Test-Path $SourceLanguagePacksDir) {
    Get-ChildItem -LiteralPath $SourceLanguagePacksDir -File | Where-Object {
        $_.Extension -in @(".zip", ".clpk")
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $PackageLanguagePacksDir -Force
        $copiedSourceLanguagePacks = $true
    }
}

$BundledLanguagePacksDir = Join-Path (Split-Path -Parent $LauncherExe) "language-packs"
if (-not $copiedSourceLanguagePacks -and (Test-Path $BundledLanguagePacksDir)) {
    Get-ChildItem -LiteralPath $BundledLanguagePacksDir -File | Where-Object {
        $_.Extension -in @(".zip", ".clpk")
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $PackageLanguagePacksDir -Force
    }
}

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -LiteralPath $PackageDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Package folder:"
Write-Host $PackageDir
Write-Host "Zip:"
Write-Host $ZipPath
