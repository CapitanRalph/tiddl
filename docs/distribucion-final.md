# Distribucion final para macOS, Windows y Linux

Este documento define como convertir Tiddl en una aplicacion facil de instalar
para usuarios no tecnicos, especialmente en macOS y Windows. La idea principal
es evitar que el usuario tenga que instalar Homebrew, Python, Git, pip, uv,
compiladores, Qt o dependencias del sistema.

## Objetivo

El usuario final debe poder instalar Tiddl con una de estas rutas:

1. Descargar un instalador desde GitHub Releases y abrirlo.
2. Ejecutar un comando corto de instalacion que descargue el instalador correcto.
3. En Linux, descargar un AppImage o instalar un paquete `.deb`.

La terminal debe ser un camino alternativo, no el camino principal para macOS y
Windows.

## Principio de producto

Para usuarios de macOS y Windows, el instalador debe ser "a prueba de usuario no
tecnico":

- No pedir instalar Homebrew.
- No pedir instalar Python.
- No pedir instalar Git.
- No pedir instalar pip, uv ni poetry.
- No pedir configurar PATH manualmente.
- No pedir instalar Qt manualmente.
- No pedir abrir el proyecto desde codigo fuente.
- No depender de la shell que usa el usuario: zsh, bash, fish, Terminal.app,
  iTerm2, PowerShell o Windows Terminal.

Si algo falla, el error debe explicar que ocurrio y que accion concreta puede
tomar el usuario.

## Canales recomendados

### Canal principal: GitHub Releases

Cada version estable debe publicar assets preconstruidos:

| Plataforma | Asset recomendado | Usuario objetivo |
| --- | --- | --- |
| macOS Apple Silicon | `Tiddl-DDJ-macOS-arm64.dmg` | Macs M1, M2, M3, M4 |
| macOS Intel | `Tiddl-DDJ-macOS-x64.dmg` | Macs Intel |
| Windows | `Tiddl-DDJ-Windows-x64-Setup.exe` | Windows 10/11 |
| Linux | `Tiddl-DDJ-Linux-x64.AppImage` | Linux generico |
| Linux Debian/Ubuntu | `tiddl-ddj_1.2.0_amd64.deb` | Ubuntu/Debian |

La pagina del release debe decir claramente:

- "Mac con chip Apple: descarga arm64".
- "Mac Intel: descarga x64".
- "Windows: descarga Setup.exe".
- "Linux: descarga AppImage".

### Canal alternativo: comando terminal

macOS y Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/CapitanRalph/tiddl/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CapitanRalph/tiddl/main/install.ps1 | iex"
```

Estos scripts no deben compilar el proyecto. Solo deben:

1. Detectar sistema operativo.
2. Detectar arquitectura.
3. Consultar el ultimo release.
4. Descargar el asset correcto.
5. Instalar o abrir el instalador.
6. Mostrar instrucciones claras si algo falla.

## Herramienta de empaquetado

### Opcion recomendada para primera version: PyInstaller

PyInstaller es practico para este proyecto porque Tiddl ya es una app Python y
la interfaz desktop se abre con `pywebview`.

Ventajas:

- Incluye Python dentro del ejecutable o bundle.
- Incluye dependencias Python.
- Funciona para Windows, macOS y Linux.
- Permite crear un ejecutable por plataforma.

Limitaciones:

- Cada plataforma debe construirse en su propio sistema operativo.
- Para macOS Apple Silicon y macOS Intel conviene construir dos assets.
- Para experiencia final igual se necesita envolver el binario:
  - macOS: `.app` dentro de `.dmg`.
  - Windows: instalador `.exe`.
  - Linux: `.AppImage` o `.deb`.

### Opcion alternativa: Briefcase

Briefcase puede generar instaladores mas nativos para apps Python:

- `.app` y `.dmg` para macOS.
- `.msi` para Windows.
- `.AppImage`, `.deb` o `.rpm` para Linux.

Puede ser mejor a largo plazo, pero normalmente requiere adaptar configuracion
del proyecto y probar mas detalles por plataforma. Para avanzar rapido, se
recomienda empezar con PyInstaller y evaluar Briefcase despues.

## Arquitectura de release

### Fuente unica de version

La version debe salir de `pyproject.toml`.

El archivo `tiddl/version.py` ya debe leer esa version automaticamente para que:

- `tiddl --version`
- `tiddl-desktop --version`
- El titulo de la app desktop
- La version visible en la UI

usen el mismo valor.

Regla de release:

1. Subir `version = "x.y.z"` en `pyproject.toml`.
2. Crear tag `vx.y.z`.
3. GitHub Actions construye assets para ese tag.
4. El release se publica con los instaladores.

### Nombres de assets

Usar nombres predecibles facilita los scripts `install.sh` e `install.ps1`.

Ejemplo para `v1.2.0`:

```text
Tiddl-DDJ-v1.2.0-macOS-arm64.dmg
Tiddl-DDJ-v1.2.0-macOS-x64.dmg
Tiddl-DDJ-v1.2.0-Windows-x64-Setup.exe
Tiddl-DDJ-v1.2.0-Linux-x64.AppImage
tiddl-ddj_1.2.0_amd64.deb
checksums.txt
```

### Actualizaciones desde GitHub

La app desktop revisa GitHub Releases desde el front y usa la version actual
del paquete para decidir si hay una actualizacion disponible.

Flujo esperado:

1. Consultar `https://api.github.com/repos/CapitanRalph/tiddl/releases/latest`.
2. Comparar `tag_name` contra `pyproject.toml`.
3. Detectar plataforma: `macos-arm64`, `macos-x64`, `windows-x64`,
   `linux-x64` o variantes arm64.
4. Buscar un asset cuyo nombre contenga plataforma y arquitectura.
5. Descargar el instalador a la carpeta local `updates`.
6. Verificar SHA256 cuando GitHub entregue `digest`.
7. Abrir el instalador del sistema y pedir al usuario cerrar Tiddl DDJ cuando
   termine.

Para que el updater funcione, cada release debe incluir assets con nombres como
`Tiddl-DDJ-v1.2.0-Windows-x64-Setup.exe` o
`Tiddl-DDJ-v1.2.0-macOS-arm64.pkg`.

## macOS

### Experiencia ideal

1. Usuario descarga `.dmg`.
2. Abre el `.dmg`.
3. Arrastra `Tiddl DDJ.app` a Applications.
4. Abre la app desde Launchpad o Applications.

### Requisitos para que no sea doloroso

Para macOS, el instalador debe estar:

- Firmado con certificado Apple Developer ID.
- Notarizado por Apple.
- "Stapled", es decir, con la notarizacion adjunta al `.app` o `.dmg`.

Si no se firma y notariza, Gatekeeper puede mostrar mensajes confusos o bloquear
la app. Eso no es aceptable para una instalacion realmente simple.

### Construccion macOS

Se deben generar dos builds:

- `arm64` para Apple Silicon.
- `x64` para Intel.

En GitHub Actions, conviene usar runners separados:

- `macos-14` para arm64 si esta disponible.
- `macos-13` o runner Intel para x64.

Comando conceptual con PyInstaller:

```sh
uv run pyinstaller \
  --name "Tiddl DDJ" \
  --windowed \
  --collect-all PySide6 \
  --collect-all pywebview \
  tiddl/cli/commands/desktop.py
```

Luego se debe crear un `.dmg` con la app.

### Firma y notarizacion

Se necesitan secretos en GitHub Actions:

```text
APPLE_ID
APPLE_TEAM_ID
APPLE_APP_SPECIFIC_PASSWORD
MACOS_CERTIFICATE_P12
MACOS_CERTIFICATE_PASSWORD
```

Flujo conceptual:

```sh
codesign --deep --force --options runtime --sign "Developer ID Application: ..." "Tiddl DDJ.app"
xcrun notarytool submit "Tiddl-DDJ.dmg" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" --wait
xcrun stapler staple "Tiddl-DDJ.dmg"
```

### Instalador por terminal en macOS

El script `install.sh` debe usar `/bin/sh` para funcionar aunque el usuario use
zsh, bash o fish.

Debe instalar sin Homebrew:

1. Detectar arquitectura:

```sh
uname -m
```

Mapeo:

```text
arm64 -> macOS-arm64.dmg
x86_64 -> macOS-x64.dmg
```

2. Descargar el `.dmg`.
3. Montarlo con `hdiutil`.
4. Copiar la app a `/Applications` si hay permisos.
5. Si no hay permisos, copiar a `$HOME/Applications`.
6. Desmontar el `.dmg`.
7. Mostrar:

```text
Tiddl DDJ instalado.
Abre la app desde Applications.
```

No debe requerir `sudo` salvo que el usuario insista en instalar para todos los
usuarios.

## Windows

### Experiencia ideal

1. Usuario descarga `Tiddl-DDJ-Windows-x64-Setup.exe`.
2. Lo ejecuta.
3. El instalador crea acceso directo en el Menu Inicio.
4. El usuario abre Tiddl DDJ.

### Instalador recomendado

Usar uno de estos:

- Inno Setup.
- NSIS.
- MSI si se elige Briefcase.

Para usuarios no tecnicos, `Setup.exe` suele ser mas familiar que un `.zip`.

### Firma

Windows funciona sin firma, pero SmartScreen puede mostrar advertencias fuertes.
Para una experiencia profesional se recomienda firmar el instalador con un
certificado de code signing.

Secretos necesarios:

```text
WINDOWS_CERTIFICATE_PFX
WINDOWS_CERTIFICATE_PASSWORD
```

Flujo conceptual:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f certificate.pfx /p "$env:WINDOWS_CERTIFICATE_PASSWORD" Tiddl-DDJ-Windows-x64-Setup.exe
```

### Instalador por PowerShell

El script `install.ps1` debe:

1. Detectar arquitectura.
2. Descargar el ultimo `Setup.exe`.
3. Ejecutarlo.
4. Si la politica de ejecucion bloquea scripts, el comando recomendado debe usar:

```powershell
powershell -ExecutionPolicy Bypass -c "irm URL | iex"
```

El script debe evitar pedir herramientas externas. No debe pedir Git, Python ni
Visual Studio Build Tools.

## Linux

### Experiencia ideal

Linux puede tener dos caminos:

1. AppImage para cualquier distro moderna.
2. `.deb` para Ubuntu/Debian.

### AppImage

Ventajas:

- No requiere instalacion tradicional.
- Se descarga, se marca como ejecutable y se abre.
- Sirve para usuarios Linux que no quieren tocar dependencias del sistema.

Comando para usuario:

```sh
chmod +x Tiddl-DDJ-v1.2.0-Linux-x64.AppImage
./Tiddl-DDJ-v1.2.0-Linux-x64.AppImage
```

### `.deb`

Para Ubuntu/Debian:

```sh
sudo apt install ./tiddl-ddj_1.2.0_amd64.deb
```

### Dependencias graficas

La app desktop usa webview/Qt. En Linux pueden faltar librerias graficas,
dependiendo de la distro. Para reducir problemas:

- Preferir AppImage con la mayor cantidad de librerias incluidas.
- Documentar dependencias minimas solo si AppImage falla.
- Mantener `tiddl desktop --browser` como fallback.

## ffmpeg

Tiddl depende funcionalmente de ffmpeg para varias operaciones. Si el instalador
no incluye ffmpeg, el usuario final vuelve a caer en problemas externos.

Opciones:

### Opcion A: incluir ffmpeg en cada build

Ventaja:

- Mejor experiencia de usuario.
- No hay que instalar nada adicional.

Riesgo:

- Revisar licencias y origen del binario.
- Usar builds compatibles con redistribucion.

### Opcion B: descarga automatica en primer inicio

Ventaja:

- El instalador pesa menos.
- Permite elegir binario por plataforma.

Riesgo:

- Necesita internet al primer inicio.
- Puede fallar por antivirus, proxy o permisos.

### Recomendacion

Para version final simple: incluir ffmpeg si la licencia y el origen del binario
son aceptables. Si no, implementar descarga automatica con mensaje claro:

```text
Tiddl necesita ffmpeg para convertir y etiquetar archivos.
Lo descargaremos automaticamente. No necesitas instalar nada.
```

## Scripts de instalacion

### `install.sh`

Debe ser POSIX shell:

```sh
#!/bin/sh
set -eu
```

No usar features exclusivas de bash como arrays.

Debe detectar downloader:

```sh
if command -v curl >/dev/null 2>&1; then
  download="curl -fL"
elif command -v wget >/dev/null 2>&1; then
  download="wget -O-"
else
  echo "No encontramos curl ni wget para descargar Tiddl."
  echo "Descarga el instalador manualmente desde GitHub Releases."
  exit 1
fi
```

Debe detectar OS:

```sh
os="$(uname -s)"
arch="$(uname -m)"
```

Mapeo:

```text
Darwin + arm64  -> macOS-arm64.dmg
Darwin + x86_64 -> macOS-x64.dmg
Linux + x86_64  -> Linux-x64.AppImage
```

Debe tener mensajes humanos:

```text
Detectamos macOS Apple Silicon.
Descargando Tiddl DDJ...
Instalando en ~/Applications...
Listo. Abre Tiddl DDJ desde Applications.
```

### `install.ps1`

Debe usar PowerShell nativo:

```powershell
$ErrorActionPreference = "Stop"
```

Debe detectar arquitectura:

```powershell
$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
```

Debe descargar con:

```powershell
Invoke-WebRequest -Uri $url -OutFile $installer
Start-Process -FilePath $installer -Wait
```

Debe mostrar mensajes claros si falla:

```powershell
Write-Host "No pudimos descargar el instalador."
Write-Host "Puedes descargarlo manualmente desde GitHub Releases:"
Write-Host "https://github.com/CapitanRalph/tiddl/releases/latest"
```

## GitHub Actions

### Workflow objetivo

Crear `.github/workflows/release.yml` que se active al publicar tags:

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --all-groups
      - run: uv run pytest
      - run: uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec
      - run: powershell packaging/windows/build-installer.ps1
      - uses: actions/upload-artifact@v4
        with:
          name: windows-installer
          path: dist/*.exe

  build-macos-arm64:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --all-groups
      - run: uv run pytest
      - run: uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec
      - run: sh packaging/macos/build-dmg.sh
      - uses: actions/upload-artifact@v4
        with:
          name: macos-arm64-dmg
          path: dist/*.dmg

  build-linux:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --all-groups
      - run: uv run pytest
      - run: uv run pyinstaller packaging/pyinstaller/tiddl-desktop.spec
      - run: sh packaging/linux/build-appimage.sh
      - uses: actions/upload-artifact@v4
        with:
          name: linux-appimage
          path: dist/*.AppImage
```

Luego un job final debe:

1. Descargar artifacts.
2. Crear `checksums.txt`.
3. Publicar GitHub Release.

## Estructura sugerida del repo

```text
packaging/
  pyinstaller/
    tiddl-desktop.spec
  macos/
    build-dmg.sh
    entitlements.plist
  windows/
    build-installer.ps1
    installer.iss
  linux/
    build-appimage.sh
    tiddl.desktop
    tiddl.png
install.sh
install.ps1
.github/
  workflows/
    release.yml
```

## Checklist de release

Antes de publicar:

- [ ] Subir version en `pyproject.toml`.
- [ ] Ejecutar `uv run pytest`.
- [ ] Crear tag `vx.y.z`.
- [ ] GitHub Actions genera todos los assets.
- [ ] Verificar que `checksums.txt` existe.
- [ ] Probar Windows en una VM limpia.
- [ ] Probar macOS Apple Silicon en una maquina limpia.
- [ ] Probar macOS Intel si se mantiene soporte.
- [ ] Probar AppImage en Ubuntu limpio.
- [ ] Confirmar que la app abre sin instalar Python.
- [ ] Confirmar que la app abre sin instalar Homebrew.
- [ ] Confirmar que la app abre sin instalar Git.
- [ ] Confirmar que ffmpeg funciona o se instala automaticamente.
- [ ] Confirmar que `tiddl-desktop --version` muestra la version del release.
- [ ] Confirmar que la UI desktop muestra la misma version.

## Criterios de aceptacion

La distribucion se considera lista cuando:

- Un usuario macOS puede instalar desde `.dmg` sin Homebrew.
- Un usuario Windows puede instalar desde `Setup.exe` sin Python.
- Un usuario Linux puede ejecutar AppImage sin preparar el repo.
- Los instaladores muestran la version correcta.
- Los scripts `install.sh` e `install.ps1` descargan el asset correcto.
- Los errores de instalacion son comprensibles.
- La documentacion no pide clonar el repo para usar la app final.

## Roadmap recomendado

### Fase 1: Release manual empaquetado

- Crear spec de PyInstaller.
- Construir localmente en cada sistema.
- Publicar assets manualmente en GitHub Releases.
- Validar experiencia con usuarios reales.

### Fase 2: Scripts de instalacion

- Agregar `install.sh`.
- Agregar `install.ps1`.
- Ambos descargan desde GitHub Releases.
- Ambos fallan con mensajes claros.

### Fase 3: CI/CD de release

- Automatizar builds con GitHub Actions.
- Automatizar checksums.
- Automatizar publicacion del release.

### Fase 4: Firma y notarizacion

- Firmar Windows.
- Firmar macOS.
- Notarizar macOS.
- Staple del `.dmg`.

### Fase 5: ffmpeg integrado

- Decidir origen legal de ffmpeg.
- Incluirlo en builds o descargarlo al primer inicio.
- Agregar test manual de conversion por plataforma.

## Decision recomendada

Para la proxima version final:

1. Mantener `pyproject.toml` como fuente unica de version.
2. Crear release con PyInstaller.
3. Publicar `.dmg`, `.exe`, `.AppImage` y `.deb`.
4. Agregar `install.sh` y `install.ps1` como wrappers de GitHub Releases.
5. Priorizar macOS firmado/notarizado antes de decir que la instalacion es
   realmente simple para usuarios no tecnicos.
