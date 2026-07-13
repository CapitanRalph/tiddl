$ErrorActionPreference = "Stop"

$uv = Get-Command "uv" -ErrorAction SilentlyContinue
if ($uv) {
    $version = & $uv.Source run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
} else {
    $version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
}

$portableSource = "dist\Tiddl-DDJ-Portable.exe"
if (-not (Test-Path $portableSource)) {
    throw "No existe $portableSource. Ejecuta primero: uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec --clean --noconfirm"
}

$target = "dist\Tiddl-DDJ-v$version-Windows-x64-Portable.exe"
Copy-Item $portableSource $target -Force

Write-Host "Portable creado: $target"
