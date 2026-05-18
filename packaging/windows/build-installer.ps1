$ErrorActionPreference = "Stop"

$version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
$appDir = Resolve-Path "dist\Tiddl DDJ"
$appExe = Join-Path $appDir "Tiddl DDJ.exe"
$iconPath = "build\installer-icons\tiddl-ddj.ico"

if (-not (Test-Path $appExe)) {
    throw "No existe $appExe. Ejecuta primero: uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec --clean --noconfirm"
}

if (-not (Test-Path $iconPath)) {
    $uv = Get-Command "uv" -ErrorAction SilentlyContinue
    if ($uv) {
        & $uv.Source run python packaging\icons\build-icons.py
    } else {
        python packaging\icons\build-icons.py
    }
}

$env:APP_VERSION = $version
$env:PYINSTALLER_APP_DIR = $appDir.Path
$env:APP_ICON_PATH = (Resolve-Path $iconPath).Path

$iscc = Get-Command "iscc" -ErrorAction SilentlyContinue
if (-not $iscc) {
    $defaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $defaultIscc) {
        $iscc = [pscustomobject]@{ Source = $defaultIscc }
    }
}

if (-not $iscc) {
    throw "No encontramos Inno Setup Compiler (iscc). Instala Inno Setup 6 o usa el workflow de GitHub Actions."
}

& $iscc.Source "packaging\windows\tiddl-ddj.iss"

$installer = "dist\Tiddl-DDJ-v$version-Windows-x64-Setup.exe"
if (-not (Test-Path $installer)) {
    throw "No se creó el instalador esperado: $installer"
}

Write-Host "Instalador creado: $installer"
