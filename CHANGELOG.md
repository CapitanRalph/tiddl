# Notas de actualización

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
