# Arranque, reconciliación y diagnóstico

**Producción 1.0.0-rc3:** la persistencia usa MinIO y MariaDB; `/app/data` es
caché reconstruible. Seguir [el procedimiento MinIO](MINIO_PERSISTENCIA.md).
Las secciones de volúmenes locales siguientes documentan el modo anterior y
su mantenimiento, no un requisito del arranque productivo actual.

El backend inspecciona una instalación antes de permitir que el worker procese
escrituras. MariaDB conserva la autoridad editorial: publicación, versiones,
fotografías, fuentes y vectores. LanceDB es una representación física que puede
recuperarse únicamente cuando hay evidencia suficiente del mismo perfil.

## Orden de arranque

1. Configurar logs JSON y asignar un `boot_id` al proceso.
2. Resolver la configuración sin crear directorios de datos.
3. Inspeccionar el historial del esquema SQL. Aplicar las migraciones conocidas
   con exclusión entre procesos. Un historial con huecos o una imagen anterior
   al esquema existente produce un error identificado, sin improvisar una migración.
   También se comparan todas las columnas con un contrato generado de las
   migraciones. Defaults conocidos y estructuras técnicas aditivas se reparan
   mediante su DDL idempotente; una columna editorial perdida o una base ajena
   sin historial bloquea el arranque sin fabricar datos.
4. Iniciar HTTP administrativo y el worker supervisado. La ausencia del volumen
   no impide abrir el diagnóstico; sí impide procesar trabajos sobre datos.
5. Inventariar SQL, publicación, volumen, identidad, índices, modelos y cola.
6. Elegir un plan explícito. Sólo después de un inventario válido se crean
   directorios faltantes y se registra una identidad aún no inicializada.
7. Recuperar la publicación existente con un trabajo identificado: verificar
   fotografía y fuentes de vectores, artefactos, huella, colección, FTS e inferencia.
8. Habilitar conocimiento cuando termina la verificación. HTTP vivo y conocimiento
   disponible son señales diferentes.

La inspección no descarga modelos, no crea colecciones, no publica versiones y
no usa el borrador para reemplazar una fotografía. El inventario completo se
reutiliza durante un máximo de 15 segundos y se invalida al cambiar la publicación.
Los controles de escritura/identidad y los leases siguen siendo independientes.

## Matriz de decisiones

| Estado encontrado | Decisión |
| --- | --- |
| SQL nuevo, sin índices físicos | Inicializar directorios e identidad; dejar la instalación sin publicación |
| Usuarios/borradores/versiones, sin publicación | Conservarlos; permitir trabajo editorial; no elegir ni publicar una versión |
| Publicación coherente e índice completo | Verificar perfil, contenido físico e inferencia antes de informar disponibilidad |
| Publicación verificable e índice ausente/incompleto | Reconstruir la misma colección desde SQL, respaldo o caché verificables; preservar la colección sustituida |
| Modelos ausentes/incompletos | Recuperar exclusivamente las revisiones fijadas y validar sus SHA-256 fuera de HTTP |
| SQL vectorial dañado pero respaldo independiente válido | Usar el respaldo para recuperar el índice; informar fuentes inválidas; no reescribir SQL |
| Dos fuentes válidas discrepan | Bloquear con razón de validación; preservar ambas para revisión |
| SQL sin versiones pero volumen con colecciones anteriores | Bloquear: comprobar conexión SQL y restaurar metadatos; no inferir ni inventar una publicación |
| Puntero a una versión/base inexistente | Bloquear y mostrar la referencia inconsistente; no modificar el puntero |
| Perfil, huella o runtime incompatible | Bloquear con versión esperada/instalada; no reinterpretar vectores |
| Volumen ausente, temporal, de sólo lectura, sin espacio o sin permisos | Bloquear escrituras y mostrar ruta, montaje observado, código y acción |
| Volumen diferente del registrado | Bloquear; reconectar el original o seguir la adopción explícita y respaldada |
| Colecciones huérfanas, staging o cuarentena | Inventariar y preservar; nunca borrar ni adoptar automáticamente |

Un redeploy puede recuperar trabajos interrumpidos y dependencias reconstruibles.
No puede crear un montaje Docker en el servidor, recuperar información destruida
sin una copia, conocer la clave perdida ni decidir cuál de dos publicaciones
contradictorias es correcta. Esos límites quedan como bloqueos accionables.

## Montajes

`DATA_DIR` es opcional. El Dockerfile usa `/app/data` por defecto. También se acepta
un subdirectorio dentro de un montaje persistente, por ejemplo volumen en
`/app/data` y datos en `/app/data/runtime`. Se elige el montaje más específico:
un `tmpfs` o montaje de sólo lectura anidado no queda oculto por un padre válido.
No se acepta la capa raíz del contenedor como evidencia de persistencia.

El inventario muestra el destino y tipo de filesystem, acceso, UID/GID, espacio e
identidad. No muestra la fuente del montaje, URLs de conexión ni secretos.
Reutilizar el almacenamiento existente; consultar `RECUPERACION.md` antes de
cambiar su ubicación o adoptar otro UUID.

## Trabajos e intentos

Cada intento tiene etapa, comienzo, heartbeat, límite de intentos, error tipado,
acción y registro histórico. Los payloads se validan dentro del intento protegido:
un JSON dañado termina identificado y no retiene el lease indefinidamente.

Los fallos temporales conocidos tienen backoff y próximo intento visible. Los
bloqueos de configuración o integridad no se reintentan ciegamente. Una vez
corregido el entorno, el arranque puede recuperar el mismo trabajo de preparación
fallido una sola vez por proceso, conservando su versión e historial. Las
cancelaciones explícitas no se revierten automáticamente.

Un lease perdido impide que el proceso anterior informe un resultado o elimine
la carga del nuevo propietario. Una parada ordenada reencola el trabajo; un
proceso interrumpido se recupera al vencer su lease. Se mantiene un proceso
Gunicorn y un worker de trabajos; no hay otro servicio que deba iniciarse a mano.

## Pantallas y herramientas

- **Diagnóstico:** `/admin/diagnostics`, autenticado. Incluye inventario, comprobaciones,
  plan, worker e historial técnico.
- **Trabajo:** estado actual, espera hasta el próximo intento, heartbeat, causa,
  etapa fallida, acción, identificadores e historial. La actualización automática
  reintenta fallos de red y señala cuando los datos están desactualizados.
  Las descargas informan archivo y bytes reales, sin inventar un porcentaje global.
- **API administrativa:** `/admin/api/diagnostics`, `/admin/api/jobs/ID` y
  `/admin/api/operations?job_id=ID`. No devuelven payloads ni tokens de propiedad.
- **Salud:** `/health/live` para Docker/Coolify; `/health/ready` para administración
  SQL; `/health/installation` para preflight; `/health/knowledge` para consultas.

En la terminal del contenedor correcto, usando su entorno existente:

```bash
# Inventario sin cambios ni descargas, también cuando no hay publicación.
python -m scripts.recover_knowledge --inspect-installation

# Diagnóstico de la fotografía publicada, sin reparaciones.
python -m scripts.recover_knowledge

# Recuperación verificable de la misma publicación; no publica ni reindexa borradores.
python -m scripts.recover_knowledge --apply
```

Una inspección bloqueada devuelve código de salida 1 y un JSON con comprobaciones
y acciones. Un error inesperado conserva su ubicación y cadena de tipos en stderr
JSON, sin copiar el mensaje del driver, SQL o valores privados.

## Logs y correlación

Cada línea de stderr es JSON con fecha UTC, nivel, nombre de evento, logger,
proceso/hilo, `boot_id`, ubicación módulo/función/línea y campos operativos.
Las solicitudes tienen `request_id`, devuelto también en `X-Request-ID`; los
trabajos añaden `job_id`, intento, etapa, código, duración y próxima espera.

Los eventos de cola, arranque y reconciliación se conservan en MariaDB
(`operational_events` y `job_events`). El informe de instalación registra su
`report_id`. El panel muestra los últimos 100 eventos operativos y hasta 30 del
trabajo; el historial SQL no desaparece al reemplazar el contenedor.

No se registran prompts, documentos, respuestas del proveedor, cuerpos de HTTP,
cookies, contraseñas, claves ni parámetros SQL. Las excepciones conservan tipos,
códigos, causas y stack frames, sin mensajes arbitrarios, variables locales o
líneas de código con valores. La redacción se aplica también al logging heredado.

Para investigar: copiar el `job_id` o `request_id` de la pantalla, localizar su
evento fallido, seguir el `boot_id` hasta `database.schema_inspected` y
`installation.reconciled`, revisar el código/etapa y ejecutar el inventario de
sólo lectura. Compartir esos datos sanitizados, no un volcado del entorno.

Docker conserva su rotación de stderr; los eventos SQL requieren la política de
retención y respaldo de la institución. No se eliminan automáticamente durante
una recuperación.

## Validación antes de liberar una imagen

```bash
python -m pytest -q
python -m pytest tests/test_mariadb_import.py --mariadb-docker -q
python -m pytest tests/test_recovery_docker.py --recovery-docker -s
```

La última suite crea su propia MariaDB, red y volumen; usa LanceDB y ONNX reales,
simula el fallo de montaje de la captura y reemplaza contenedores. No usa la base
productiva ni llama a generación pagada. Los tests con motores dobles validan
contratos e integridad, no calidad semántica. Los resultados de esta revisión se
registran en `reports/VALIDACION.md`.
