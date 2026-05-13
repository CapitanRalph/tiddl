# Tidal Downloader

Descarga tracks y videos desde Tidal en la mejor calidad disponible. `tiddl` es
una aplicación CLI y desktop local escrita en Python.

> [!WARNING]
> `Esta aplicación es solo para uso personal y no está afiliada a Tidal. Cada usuario debe asegurarse de que su uso cumpla con los términos de servicio de Tidal y con las leyes locales de copyright. Los tracks descargados son para uso personal y no deben compartirse ni redistribuirse. El desarrollador no asume responsabilidad por el uso indebido de esta herramienta.`

![PyPI - Downloads](https://img.shields.io/pypi/dm/tiddl?style=for-the-badge&color=%2332af64)
![PyPI - Version](https://img.shields.io/pypi/v/tiddl?style=for-the-badge)
[<img src="https://img.shields.io/badge/gitmoji-%20😜%20😍-FFDD67.svg?style=for-the-badge" />](https://gitmoji.dev)

# Instalación

Esta versión se instala desde el fork principal del proyecto:

```text
https://github.com/CapitanRalph/tiddl
```

> [!NOTE]
> La versión publicada en [PyPI](https://pypi.org/project/tiddl/) puede no incluir
> los cambios de este fork, como la aplicación desktop con FastAPI + HTMX. Para
> probar este proyecto tal como está documentado aquí, instala desde GitHub.

> [!IMPORTANT]
> Asegúrate también de tener instalado [`ffmpeg`](https://ffmpeg.org/download.html).
> Se usa para convertir los tracks descargados al formato correcto.

## Requisitos

- Python 3.12 o superior.
- `git`.
- `ffmpeg`.
- `uv`, recomendado para instalar y ejecutar el proyecto.
- En Linux, algunas dependencias de WebKit/GTK o Qt pueden ser necesarias para
  abrir la ventana nativa de `tiddl desktop`. Si no quieres instalar esas
  dependencias, puedes usar `tiddl desktop --browser`.

## Linux

### Ubuntu / Debian

Instala dependencias del sistema:

```bash
sudo apt update
sudo apt install -y git curl python3.12 python3.12-venv ffmpeg
```

Instala `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
```

Instala `tiddl` desde el fork:

```bash
uv tool install "git+https://github.com/CapitanRalph/tiddl.git"
```

Para usar la ventana nativa de la app desktop en Ubuntu/Debian, instala las
dependencias GTK recomendadas para webview:

```bash
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

Si tu distribución no tiene `gir1.2-webkit2-4.1`, prueba con
`gir1.2-webkit2-4.0` o ejecuta la app con `tiddl desktop --browser`.

Verifica la instalación:

```bash
tiddl --help
tiddl desktop --browser
```

### Fedora

```bash
sudo dnf install -y git curl python3.12 ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv tool install "git+https://github.com/CapitanRalph/tiddl.git"
tiddl --help
```

### Arch Linux

```bash
sudo pacman -Syu --needed git curl python ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv tool install "git+https://github.com/CapitanRalph/tiddl.git"
tiddl --help
```

## macOS

Instala [Homebrew](https://brew.sh/) si aún no lo tienes. Luego instala las
dependencias:

```bash
brew install git python@3.12 ffmpeg uv
```

Instala `tiddl` desde el fork:

```bash
uv tool install "git+https://github.com/CapitanRalph/tiddl.git"
```

Verifica la instalación:

```bash
tiddl --help
tiddl desktop
```

Si la ventana nativa falla por dependencias de webview, usa:

```bash
tiddl desktop --browser
```

## Windows

Abre PowerShell como usuario normal e instala `uv`:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Instala Python 3.12, Git y FFmpeg. Si usas `winget`:

```powershell
winget install Python.Python.3.12
winget install Git.Git
winget install Gyan.FFmpeg
```

Cierra y vuelve a abrir PowerShell para actualizar el `PATH`. Luego instala el
proyecto desde el fork:

```powershell
uv tool install "git+https://github.com/CapitanRalph/tiddl.git"
```

Verifica la instalación:

```powershell
tiddl --help
tiddl desktop
```

> [!TIP]
> En Windows 10/11 normalmente WebView2 ya está instalado. Si `tiddl desktop`
> no abre la ventana nativa, actualiza Microsoft Edge WebView2 Runtime o ejecuta
> `tiddl desktop --browser`.

## Instalación para desarrollo

Si quieres modificar el código, clona el fork e instala el paquete en modo
editable:

```bash
git clone https://github.com/CapitanRalph/tiddl.git
cd tiddl
uv sync --dev
```

En Windows PowerShell, la activación manual del entorno sería:

```powershell
.venv\Scripts\Activate.ps1
```

En Linux/macOS:

```bash
source .venv/bin/activate
```

# Uso

Ejecuta la aplicación con `tiddl`.

```bash
$ tiddl
 Usage: tiddl [OPTIONS] COMMAND [ARGS]...

 tiddl - download tidal tracks ♫

╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --omit-cache            --no-omit-cache      [default: no-omit-cache]                                       │
│ --debug                 --no-debug           [default: no-debug]                                            │
│ --install-completion                         Install completion for the current shell.                      │
│ --show-completion                            Show completion for the current shell, to copy it or customize │
│                                              the installation.                                              │
│ --help                                       Show this message and exit.                                    │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ──────────────────────────────────────────────────────────────────────────────────────────────────╮
│ auth       Manage Tidal authentication.                                                                     │
│ desktop    Run the local desktop-like web app.                                                              │
│ download   Download Tidal resources.                                                                        │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Autenticación

Inicia sesión con tu cuenta de Tidal ejecutando el siguiente comando y siguiendo
las instrucciones.

```bash
tiddl auth login
```

## Descarga

Puedes descargar tracks, videos, álbumes, artistas, playlists y mixes.

```bash
$ tiddl download url <url>
```

> [!TIP]
> No es necesario pegar URLs completas. También funcionan formatos como
> `track/103805726`, `album/103805723`, etc.

Ejecuta `tiddl download` para ver todas las opciones disponibles.

### Calidad

| Calidad | Extensión |        Detalles         |
| :-----: | :-------: | :---------------------: |
|   LOW   |   .m4a    |         96 kbps         |
| NORMAL  |   .m4a    |        320 kbps         |
|  HIGH   |   .flac   |    16-bit, 44.1 kHz     |
|   MAX   |   .flac   | Hasta 24-bit, 192 kHz   |

### Salida

Puedes formatear los nombres de archivo de los recursos descargados y ubicarlos
en distintos directorios.

Por ejemplo, usando la opción de salida
`"{album.artist}/{album.title}/{item.number:02d}. {item.title}"`, los tracks se
descargarán con una estructura como esta:

```
Music
└── Kanye West
    └── Graduation
        ├── 01. Good Morning.flac
        ├── 02. Champion.flac
        ├── 03. Stronger.flac
        ├── 04. I Wonder.flac
        ├── 05. Good Life.flac
        ├── 06. Can't Tell Me Nothing.flac
        ├── 07. Barry Bonds.flac
        ├── 08. Drunk and Hot Girls.flac
        ├── 09. Flashing Lights.flac
        ├── 10. Everything I Am.flac
        ├── 11. The Glory.flac
        ├── 12. Homecoming.flac
        ├── 13. Big Brother.flac
        └── 14. Good Night.flac
```

> [!NOTE]
> Aprende más sobre [plantillas de archivos](/docs/templating.md).

## Aplicación de escritorio

La instalación también registra un ejecutable directo para la app local:

```bash
tiddl-desktop
```

También puedes abrirla desde la CLI principal:

```bash
tiddl desktop
```

Esto inicia una interfaz FastAPI + HTMX en una ventana nativa con webview.
Reutiliza la misma sesión confiable que la CLI, permite iniciar sesión con el
flujo device login de Tidal y muestra `Autor: Psybots` en la interfaz.

La app permite:

- Listar playlists, álbumes y tracks favoritos.
- Hacer click en una playlist o álbum para ver una vista previa de su contenido
  en el panel derecho.
- Descargar con salida `RAW`, `WAV` o `MP3 320`.
- Configurar descargas paralelas entre 1 y 3 canciones al mismo tiempo.
- Ver una barra inferior con información de terminal, descarga actual y progreso.
- Revisar descargas en cola, descargas completadas y errores.

Si tu sistema no puede abrir una ventana nativa con webview, puedes usar el modo
en navegador:

```bash
tiddl-desktop --browser
```

o:

```bash
tiddl desktop --browser
```

> [!NOTE]
> Esta interfaz es para uso personal/local. También muestra decisiones técnicas
> útiles para portfolio: arquitectura backend, autenticación persistente,
> integración con API externa, descarga concurrente, manejo de archivos y una UI
> operativa sin convertir el proyecto en un producto distribuido.

## Archivos de configuración

Los archivos de la aplicación se crean en tu directorio home. Por defecto,
`tiddl` usa `~/.tiddl`.

Puedes crear un archivo `config.toml` para configurar la aplicación a tu gusto.

Puedes copiar la configuración de ejemplo desde
[config.example.toml](/docs/config.example.toml).

## Variables de entorno

### Ruta personalizada de la aplicación

Puedes definir la variable de entorno `TIDDL_PATH` para usar una ruta
personalizada para los archivos de `tiddl`.

Ejemplo de uso en CLI:

```sh
TIDDL_PATH=~/custom/tiddl tiddl auth login
```

### ¿La autenticación dejó de funcionar?

Define la variable de entorno `TIDDL_AUTH` para usar otras credenciales.

```text
TIDDL_AUTH=<CLIENT_ID>;<CLIENT_SECRET>
```

# Recursos

[Tidal API wiki (endpoints de API)](https://github.com/Fokka-Engineering/TIDAL)

[Tidal-Media-Downloader (inspiración)](https://github.com/yaronzz/Tidal-Media-Downloader)
