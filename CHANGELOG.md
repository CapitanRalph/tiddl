# Notas de actualización

## v1.1.12

- Se integró el logo de Tiddl DDJ en el encabezado de la app desktop.
- Se cambió la plantilla de nombres por defecto a un formato compatible con
  rekordbox: carpetas por artista/álbum y archivos con número, artista y título.
- Las playlists descargadas usan índice de playlist, artista y título con versión
  para mantener orden estable en crates/sets.
- La metadata de artistas conserva el orden original entregado por TIDAL en vez
  de ordenarse alfabéticamente.

## v1.1.11

- Se agregó una pestaña Archivos para explorar la carpeta absoluta de descargas
  de la app desde la interfaz desktop.
- La ruta raíz de descargas ahora se puede cambiar desde el explorador y queda
  persistida en `config.toml` como `download_path` y `scan_path`.
- El explorador detecta carpetas, archivos y playlists descargadas bajo la raíz
  configurada, con acciones para abrir carpetas desde el sistema.

## v1.1.10

- La aplicación visible ahora se llama Tiddl DDJ; Psybots queda sólo como autor
  en el front.
- Se agregó una primera integración de actualizaciones vía GitHub Releases:
  revisión desde la UI, detección de plataforma, selección de instalador,
  descarga, verificación SHA256 cuando GitHub entrega digest y apertura del
  instalador del sistema.

## v1.1.9

- Se redujo el tamaño visual de textos en vista previa y cola de descargas para
  que la app desktop se sienta más compacta y operativa.
- Se ajustaron badges, datos de descarga, rutas y filas de canciones sin cambiar
  el tamaño de los controles principales.

## v1.1.8

- Se modernizó la interfaz desktop con superficies más claras, header renovado,
  sombras sutiles y una distribución de descargas en cuatro estados.
- Se agregó cancelación de descargas en curso o en cola desde la tarjeta del job.
- La cancelación ahora es cooperativa: corta descargas activas, limpia temporales
  y mueve el trabajo a la columna Canceladas.
- La barra de estado muestra conteos de cancelación y trabajos cancelados.

## v1.1.7

- La app desktop ya no depende del CDN de HTMX para operar la interfaz local.
- Los errores de sesión, recurso inválido y carga de API ahora se muestran dentro
  de la UI en vez de aparecer como respuestas crudas del servidor.
- La biblioteca limita la carga inicial de favoritos de canciones/álbumes para
  evitar esperas largas en cuentas grandes.
- Los estados de descarga y mensajes finales quedaron normalizados en español.
- La barra de progreso de cada descarga se limita visualmente a 100%.
- Se agregaron pruebas para errores de UI, límite de biblioteca, runtime local y
  versionado automático.

## v1.1.6

- Se documentó la estrategia de distribución final para macOS, Windows y Linux.

## v1.1.5

- La versión visible se obtiene automáticamente desde `pyproject.toml`.
- Se protegió el versionado automático con pruebas.
