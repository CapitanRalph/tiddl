# Notas de actualización

## v1.2.0

Rediseño UX de la app desktop:

- La calidad de audio/video y el formato ahora se eligen en un solo lugar (la
  barra "Descarga directa"); todos los botones "Descargar" de vista previa y
  filas de canciones heredan esos ajustes. Antes cada fila repetía tres
  selectores (una playlist de 50 canciones mostraba 150 dropdowns).
- El tablero de descargas dejó de ser un kanban de cuatro columnas fijas (que
  desperdiciaba el ancho cuando había pocas descargas) y pasó a una lista única
  de tarjetas: activas primero, luego las más recientes, con chips de resumen
  (en curso / completadas / canceladas / con errores).
- Un job terminado con ítems fallidos ahora se distingue con el badge
  "Con errores"; mientras corre se mantiene como "En curso".
- Las filas de resultados dentro de cada tarjeta se compactaron: estado con
  color (verde/ámbar/rojo) y título, con la ruta como tooltip, en vez de ruta
  completa y botón "Abrir carpeta" por cada archivo.
- Las pestañas de biblioteca (Playlists/Álbumes/Canciones/Archivos) ahora
  marcan cuál está activa.
- Nuevo botón "Vista previa" en la barra de descarga directa para revisar un
  enlace pegado antes de descargarlo, y el campo acepta explícitamente enlaces
  completos de TIDAL (el placeholder y los errores lo dicen).
- Los mensajes de éxito ya no se pintan en rojo (p. ej. al guardar la ruta de
  descargas) y los errores de red del refresco automático ya no se apilan
  repetidos en pantalla.
- Se puede cancelar un intento de inicio de sesión pendiente.
- La ventana desktop define tamaño mínimo (1000×660) y usa el logo como icono
  de ventana.

Descargas:

- Descargar una canción que ya existe en otro formato ya no se bloquea con
  "Ya existía": si el track está en FLAC/M4A y pides MP3 320 o WAV, la app
  convierte la copia local (sin volver a descargar) y conserva el archivo
  original. El resultado se muestra como "Convertido a MP3 320" /
  "Convertido a WAV".
- En la vista previa de playlists se quitó el botón de descarga por canción:
  descargar un track suelto lo dejaba fuera de la carpeta de la playlist y sin
  numeración, lo que parecía un error. Las playlists se descargan completas
  con "Descargar todo" (la cabecera lo explica).
- El botón "Descargar" de la barra directa queda inactivo mientras no haya un
  enlace pegado, y el campo se limpia al iniciar la descarga, evitando
  descargas duplicadas o clics confusos mientras baja una playlist.

Empaquetado portable:

- **FFmpeg ahora viene incluido**: la app usa el binario estático de
  `imageio-ffmpeg` (macOS arm64/x64, Windows x64 y Linux), tanto en la
  instalación con `uv`/pip como dentro del `.dmg` y el `.exe` portable. Ya no
  hay que instalar ffmpeg aparte; `TIDDL_FFMPEG` permite apuntar a un binario
  propio. La detección de códec dejó de depender de `ffprobe` (que el binario
  embebido no trae) y ahora usa el propio `ffmpeg`.
- Windows ahora se publica como ejecutable portable único
  (`Tiddl-DDJ-vX.Y.Z-Windows-x64-Portable.exe`): sin instalador, se ejecuta
  desde cualquier carpeta. Los scripts de Inno Setup siguen en el repo para
  quien prefiera un instalador.
- El `.dmg` de macOS (arm64 y x64) se mantiene; la app se puede arrastrar a
  Applications o ejecutarse directamente.
- El mensaje del botón de actualización refleja el flujo portable: se descarga
  y abre la nueva versión, y basta cerrar la anterior.

## v1.1.17

- Se corrigió que las descargas en MP3 (y WAV) no se detectaran como ya
  completadas: el descargador base sólo predecía archivos `.flac`/`.m4a`, por lo
  que un `.mp3` ya convertido nunca se reconocía. Ahora, con `skip_existing`
  activo, los tracks ya convertidos aparecen como "Ya existía" y no se vuelven a
  descargar en cada corrida.
- La numeración por defecto ya no usa ceros a la izquierda: los nombres pasan de
  `001`/`01` a `1`, `2`, `3`… incrementándose automáticamente (álbumes por número
  de track, playlists por índice).
- La carpeta de descargas por defecto ahora es `~/Music/Tiddl DDJ` (antes
  `~/Music/tiddl`), más fácil de ubicar.
- Se rediseñó la interfaz desktop para hacerla más ergonómica: escala
  tipográfica y de espaciados unificada, cabecera y barra de estado más
  delgadas (más espacio útil), barra de descarga directa compacta en una fila,
  y tarjetas de descarga simplificadas (una sola línea de datos en vez de la
  rejilla de seis campos) para que no se corten en columnas angostas. El tablero
  de descargas ahora ajusta sus columnas al ancho disponible y las pestañas de
  biblioteca quedan en rejilla 2×2.
- Se corrigió que una descarga en curso con un ítem fallido apareciera a la vez
  en "En curso" y en "Errores": las columnas del tablero ahora son mutuamente
  excluyentes y un job sólo pasa a "Errores" cuando finaliza.
- La vista previa ya no muestra el identificador técnico del recurso
  (`playlist/uuid`, `album/id`) bajo el nombre; ensuciaba el front y no aporta
  al usuario.

## v1.1.16

- Los instaladores ahora generan iconos desde el logo oficial y los aplican al
  bundle macOS y al instalador Windows.

## v1.1.15

- Se optimizó la spec de PyInstaller para empaquetar solo los módulos Qt
  necesarios para la ventana desktop, reduciendo peso y ruido del build.

## v1.1.14

- Se agregó empaquetado de instaladores para GitHub Actions:
  `.dmg` macOS arm64 para MacBook M1/M2 y `Setup.exe` Windows x64.
- Se creó una spec de PyInstaller para construir la app desktop como bundle.
- Se agregó script macOS para generar DMG y script Windows con Inno Setup.
- El workflow de release publica los instaladores y `checksums.txt` cuando se
  empuja un tag `v*`.

## v1.1.13

- Las descargas de playlist ahora muestran el nombre real de la playlist en la
  tarjeta del job cuando la API ya lo conoce, dejando el recurso técnico como
  detalle secundario.
- Se agregó un divisor arrastrable entre Vista previa y Descargas para ajustar
  el alto de ambas áreas en escritorio.
- El mensaje de actualizaciones cuando aún no hay releases publicados en GitHub
  queda resumido para no ensuciar el header.

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
