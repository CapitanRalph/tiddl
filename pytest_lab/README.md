# 🧪 Pytest Lab — Plan de testing para `tiddl`

Carpeta de aprendizaje: tests escritos con **pytest** que sirven a la vez para
**entender cómo funciona este repo** y para **aprender la librería pytest**.
Es independiente de la suite oficial que vive en [`tests/`](../tests/).

```bash
# Ejecutar todo el laboratorio (desde la raíz del repo)
uv run pytest pytest_lab -v

# Ejecutar una sola lección
uv run pytest pytest_lab/test_02_resource_parsing.py -v

# Ejecutar tests cuyo nombre contenga una palabra
uv run pytest pytest_lab -k "explicit" -v

# Ver cobertura de código (qué líneas ejercitan los tests)
uv run pytest pytest_lab --cov=tiddl --cov-report=term-missing
```

---

## 1. Cómo funciona `tiddl` (arquitectura)

`tiddl` es un descargador de Tidal con 3 capas bien separadas:

```
┌────────────────────────────────────────────────────────────┐
│  INTERFACES (lo que ve el usuario)                          │
│  tiddl/cli/app.py        → CLI con Typer                    │
│  tiddl/web/app.py        → API HTTP local con FastAPI + UI  │
│  tiddl/cli/commands/desktop.py → ventana desktop (webview)  │
├────────────────────────────────────────────────────────────┤
│  ORQUESTACIÓN (lógica de descarga)                          │
│  cli/commands/download/downloader.py → cola async, hilos    │
│  cli/config.py           → config.toml → Pydantic Config    │
│  cli/utils/resource.py   → parseo de URLs de Tidal          │
│  core/utils/format.py    → plantillas de nombres de archivo │
├────────────────────────────────────────────────────────────┤
│  NÚCLEO (habla con el mundo exterior)                       │
│  core/auth/    → OAuth2 device-flow contra auth.tidal.com   │
│  core/api/     → cliente HTTP cacheado de api.tidal.com/v1  │
│  core/metadata → tags FLAC/M4A con mutagen                  │
│  core/utils/   → parseo de manifiestos DASH/BTS, ffmpeg     │
│  updater.py    → busca releases nuevos en GitHub            │
└────────────────────────────────────────────────────────────┘
```

## 2. Con qué APIs se comunica

| API externa | Módulo | Para qué |
|---|---|---|
| `https://auth.tidal.com/v1/oauth2` | [core/auth/client.py](../tiddl/core/auth/client.py) | Login por device-flow (código que apruebas en el navegador), refresh y logout de tokens |
| `https://api.tidal.com/v1` | [core/api/client.py](../tiddl/core/api/client.py) | Catálogo: tracks, álbumes, playlists, favoritos, letras y **streams** (manifiestos de descarga) |
| CDN de Tidal (URLs de los manifiestos) | [core/utils/parse.py](../tiddl/core/utils/parse.py), [core/utils/download.py](../tiddl/core/utils/download.py) | Bajar los segmentos de audio/video |
| `https://api.github.com` | [updater.py](../tiddl/updater.py) | Buscar actualizaciones del fork |

Además **expone su propia API HTTP local**: [web/app.py](../tiddl/web/app.py) crea una
app FastAPI (`create_app()`) con endpoints como `POST /jobs`, `GET /partials/library`,
`POST /auth/start`… que la UI consume con htmx. Esa app también se puede testear
sin levantar un servidor, con `fastapi.testclient.TestClient` (lección 09).

Flujo típico de una descarga:

1. `TidalResource.from_string("https://tidal.com/album/123")` → identifica tipo e id.
2. `TidalAPI.get_album_items()` → pide el contenido a `api.tidal.com` (con caché sqlite).
3. `TidalAPI.get_track_stream()` → devuelve un **manifiesto en base64** (JSON "BTS" o XML DASH).
4. `parse_track_stream()` → extrae URLs de segmentos y decide extensión (`.flac`/`.m4a`).
5. `format_template()` → arma la ruta del archivo según tu plantilla del `config.toml`.
6. El downloader baja los segmentos, `metadata/` escribe los tags, `ffmpeg` convierte si pediste MP3/WAV.

## 3. DÓNDE conviene aplicar pytest (la pirámide)

De más fácil/valioso a más difícil/frágil:

1. **Funciones puras** (entrada → salida, sin red ni disco): `sanitize_string`,
   `TidalResource.from_string`, `format_template`, `get_existing_track_filename`,
   `parse_manifest_XML`. → *Máximo retorno, cero mocks. La mayoría de los tests deben vivir aquí.*
2. **Modelos y config** (Pydantic): `Config`, validadores, `model_post_init`.
   → Verifican el "contrato" con la API de Tidal y con tu `config.toml`.
3. **Funciones que tocan disco**: `resolve_existing_path_case`, `save_download_root_config`.
   → Se testean con la fixture `tmp_path` (carpeta temporal que pytest crea y borra sola).
4. **Clientes HTTP**: `TidalClient.fetch`, `AuthAPI`. → **Nunca contra la API real**:
   se reemplaza la capa HTTP con mocks/fakes (`monkeypatch`, inyección de dependencias).
5. **La app FastAPI**: con `TestClient`, sin levantar uvicorn ni tener sesión de Tidal.

**Dónde NO conviene** (costo > beneficio): descargas reales, conversión con ffmpeg,
la GUI de escritorio (PySide/webview), y el hilo de polling de login. Eso se prueba
a mano o con tests de integración marcados y opcionales.

## 4. CÓMO hacerlos (técnicas, una por lección)

| Lección | Módulo bajo prueba | Técnica de pytest que enseña |
|---|---|---|
| [test_01](test_01_sanitize_basics.py) | `core/utils/sanitize.py` | Anatomía de un test, `assert`, `@pytest.mark.parametrize` |
| [test_02](test_02_resource_parsing.py) | `cli/utils/resource.py` | `pytest.raises` para errores esperados |
| [test_03](test_03_quality_and_paths.py) | `cli/utils/download.py`, `cli/utils/path.py` | `tmp_path` (disco temporal), parametrize con ids |
| [test_04](test_04_format_template.py) | `core/utils/format.py` | **Fixtures factory** en `conftest.py`, objetos Pydantic de prueba |
| [test_05](test_05_config.py) | `cli/config.py` | Tests de config TOML, `ValidationError`, defaults |
| [test_06](test_06_manifest_parse.py) | `core/utils/parse.py` | Construir datos binarios/base64 de prueba |
| [test_07](test_07_auth_api.py) | `core/auth/` | **Fakes por inyección de dependencias**, `monkeypatch.setenv` |
| [test_08](test_08_tidal_client_http.py) | `core/api/client.py` | **Mockear HTTP** con `monkeypatch.setattr`, probar retries y refresh de token |
| [test_09](test_09_web_app.py) | `web/app.py` | `TestClient` de FastAPI, monkeypatch de estado global |

Conceptos clave que verás en el código:

- **Fixture**: función decorada con `@pytest.fixture` que prepara algo y se inyecta
  por nombre de parámetro. Las compartidas viven en [`conftest.py`](conftest.py).
- **Factory fixture**: fixture que devuelve una *función* para fabricar objetos con
  valores por defecto y overrides (`make_track(title="Otra")`). Ideal para modelos
  Pydantic grandes como `Track` (¡tiene ~25 campos obligatorios!).
- **`monkeypatch`**: fixture integrada para reemplazar temporalmente atributos,
  funciones o variables de entorno; pytest lo revierte solo al terminar el test.
- **Regla de oro del monkeypatch**: parchea el nombre *donde se usa*
  (`tiddl.web.app.load_auth_data`), no donde se definió.

## 5. PARA QUÉ hacerlos

- **Red de seguridad**: si mañana refactorizas `format_template`, los tests te dicen
  en segundos si rompiste los nombres de archivo.
- **Documentación viva**: `test_04` explica el sistema de plantillas mejor que cualquier doc,
  y no se desactualiza (si miente, falla).
- **Entender código ajeno/generado por IA**: escribir un test te obliga a descubrir
  qué entra y qué sale de cada función — exactamente el objetivo de esta carpeta.
- **Detectar contratos rotos**: por ejemplo, mientras escribía estos tests apareció un
  hallazgo real: en [web/app.py](../tiddl/web/app.py) se llama
  `get_existing_track_filename(item.audioQuality, track_quality, ...)` pasando la
  calidad en minúsculas (`"high"`) donde la función espera el literal de la API
  (`"LOSSLESS"`), así que la predicción de extensión siempre da `.m4a`. Hoy es
  inofensivo porque luego se reemplaza el sufijo, pero es el tipo de bug silencioso
  que un test (o mypy) atrapa.

## 6. CUÁNDO aplicarlos

- **Al escribir código nuevo**: un test por comportamiento, antes o justo después.
- **Antes de cada commit**: `uv run pytest` (rápido: todo esto corre sin red).
- **Al arreglar un bug**: primero escribe el test que lo reproduce (falla → rojo),
  luego arregla (pasa → verde). Ese test de regresión evita que el bug vuelva.
- **En CI**: un workflow de GitHub Actions que corra `uv run pytest` en cada push
  (siguiente paso natural para este repo).
- **Antes de actualizar dependencias**: la suite te dice si `pydantic` o `fastapi`
  rompieron algo.

## 7. Siguientes pasos sugeridos

1. Medir cobertura (`--cov`) y subir las funciones puras que falten.
2. Añadir GitHub Actions (`.github/workflows/test.yml`) con `uv run pytest`.
3. Tests basados en propiedades con `hypothesis` para `sanitize_string`/plantillas.
4. Tests de integración opcionales (marcados `@pytest.mark.integration`) que usen
   una cuenta real, excluidos por defecto.
