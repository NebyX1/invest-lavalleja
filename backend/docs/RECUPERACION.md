# Persistencia, recuperación y despliegue seguro

Aplicable al backend institucional, MariaDB y LanceDB local. No cambia modelos,
prompts, versiones publicadas ni permisos. No ejecuta generación automáticamente.
El despliegue en producción necesita la autorización del responsable; este trabajo
prepara el código y el procedimiento sin intervenir Coolify.

## Qué se conserva

| Elemento | Ubicación/autoridad | Protección |
| --- | --- | --- |
| Usuarios, configuración, versiones, registros públicos/internos, fuentes, caché y puntero activo | MariaDB exclusiva de Gianna | Dump consistente y copia externa cifrada; volumen del propio servicio MariaDB |
| Fotografías y vectores de cada versión | `version_records`, `version_sources`, `chunks.vector_json/content_json` | Incluidos en el dump; permiten reconstrucción exacta si están completos |
| Colecciones y FTS | `/app/data/lance` (`Config.lance_dir`) | Volumen persistente más copia externa coherente |
| Pesos, tokenizadores y manifiestos SHA-256 | `/app/data/models` | Revisión fijada y recuperación automática; conviene conservar una copia offline para depender menos del hub |
| Documentos temporales de importación y exports | `/app/data/uploads`, `/app/data/exports` | Mismo volumen; conservar cargas de trabajos pendientes |
| Respaldo técnico validado por versión | `/app/data/recovery/backups` | JSON con huella, hash de fotografía y hash de filas físicas; incluir en backup externo |
| Identidad del volumen | `/app/data/.gianna-storage.json` y setting SQL | Conservar ambos junto al resto de los datos |
| Claves existentes | Gestor seguro de secretos | Custodia separada. No regenerar SECRET_KEY/ENCRYPTION_KEY en un redeploy |

Comprobar la ruta efectiva con `Config.lance_dir`: no renombrar un directorio
existente para adaptarlo a este documento. El código mantiene las rutas anteriores.

## Señales de salud y arranque

| Señal | Qué acredita |
| --- | --- |
| `GET /health/live` | Proceso HTTP vivo. Healthcheck de Docker/Coolify, sin modelos, SQL ni generador |
| `GET /health/ready` | Servicio administrativo y conexión SQL; no acredita RAG |
| `GET /health/knowledge` | 200 solo con conocimiento disponible; 503 estructurado durante preparación/fallo |
| `GET /api/config` | `enabled` es la decisión de habilitar chat; `available` exige dependencias verificadas. Agrega `knowledge_state`, `knowledge_code`, `knowledge_message` |
| `/admin/api/diagnostics` autenticado | Worker, modelos activo/construcción, conectividad física, conocimiento, espacio y RSS |

El worker inicia la verificación de la versión activa después de arrancar Gunicorn.
Los estados son `initializing`, `restoring_models`, `restoring_index`, `ready`,
`no_knowledge`, `failed`. No se descarga desde una solicitud HTTP. El frontend
puede consultar `/api/config` periódicamente y mostrar su mensaje sin interpretar
rutas o excepciones internas. Los campos anteriores del contrato siguen vigentes.

Un warmup tiene hasta tres intentos persistentes (esperas de 30 y 60 segundos).
La descarga tiene a su vez hasta tres intentos (esperas de 1 y 2 segundos), timeouts
de conexión/lectura y un plazo de 900 segundos por preparación de un modelo.
Una caída abrupta permite reclamar el trabajo tras vencer el lease de 120 segundos;
un `running` sin lease también se recupera. Una parada ordenada lo reencola.
Una cancelación solicitada por el administrador no se vuelve a crear automáticamente.
Agotados los intentos, revisar la causa y reintentar desde el panel: no reiniciar
Gunicorn en bucle. No modificar el número de workers: se conserva uno.

## Herramienta de diagnóstico y restauración

En la terminal del contenedor correcto, con su entorno existente:

```bash
# Diagnóstico/simulación: sin descargas, cambios SQL, backup ni cambios del índice.
python -m scripts.recover_knowledge
python -m scripts.recover_knowledge --version-id ID_COMPLETO

# Recuperación técnica de la MISMA fotografía, manteniendo el puntero activo.
python -m scripts.recover_knowledge --apply
```

La CLI no inicia Flask, aplica migraciones ni arranca otro worker. Devuelve JSON y
código de salida 0/1. Si el worker ya posee el lock, informa `recovery_busy`: esperar
su trabajo en lugar de competir. La preparación manual `scripts.prepare_models`
sigue disponible para mantenimiento pero ya no forma parte de cada redeploy.

La restauración examina primero el respaldo técnico disponible y lo contrasta con
la fotografía SQL. Solo usa vectores verificables del mismo perfil (SQL, respaldo
válido o caché con huella/hash exactos). No recalcula embeddings ni usa el borrador
para completar huecos. Crea una tabla staging, FTS español, verifica cada fila y
ejecuta inferencia y búsqueda local antes de informar disponibilidad. Conserva las
colecciones inválidas como `gianna_quarantine_*`; no las limpia automáticamente.

`snapshot_invalid`, `embedding_mismatch`, un perfil desconocido o datos insuficientes
exigen revisión supervisada. Conservar la publicación, buscar un dump/volumen o
runtime compatibles. Solo si resulta irrecuperable, proponer al administrador el
flujo editorial de otra versión: importar/revisar/aprobar/indexar/evaluar/publicar.
Nunca cambiar el puntero o la huella para ocultar el fallo.

## Recuperación del incidente y primera migración productiva

1. **Inventario sin cambios.** Identificar recurso, servidor y contenedor backend
   actuales, su imagen anterior y la base MariaDB. No pegar un `docker inspect`
   completo: incluye variables secretas. En el VPS, estas consultas solo muestran
   montajes y estado:

   ```bash
   docker inspect --format '{{json .Mounts}}' CONTENEDOR_API
   docker inspect --format '{{.Config.Image}} {{.State.Status}}' CONTENEDOR_API
   docker volume inspect NOMBRE_REAL_DEL_VOLUMEN
   ```

   Exigir un montaje de lectura/escritura en **exactamente `/app/data`**, con el
   Source/Name que contiene los archivos existentes. Inspeccionar también el volumen
   de MariaDB. Registrar nombres reales, servidor, tamaño y revisión de imagen.
   Un montaje en `/data`, un volumen anónimo nuevo o una ruta de DATA_DIR distinta
   no prueban que se esté utilizando el almacenamiento anterior.

2. **Respaldo recuperable antes de migrar.** Abrir una ventana de mantenimiento,
   impedir cambios editoriales y esperar que terminen importaciones/indexaciones.
   Generar un dump lógico desde el contenedor con el entorno existente:

   ```bash
   docker exec CONTENEDOR_API python -m scripts.backup --output /app/data/exports/pre-persistencia.sql
   docker cp CONTENEDOR_API:/app/data/exports/pre-persistencia.sql /RUTA_SEGURA/pre-persistencia.sql
   ```

   El destino debe ser nuevo; el script no sobrescribe. Con el backend detenido y
   sus datos inmóviles, archivar el volumen existente usando un helper con origen
   montado **solo lectura**, o la función de respaldo de almacenamiento de Coolify.
   Copiar dump, archivo, inventario y sumas SHA-256 fuera del VPS; cifrar y restringir
   permisos porque incluyen datos internos, cuentas y sesiones. Custodiar las claves
   por separado. Probar la importación del dump y la lectura del archivo en un entorno
   aislado antes de considerar recuperable la copia.

3. **Preservar datos existentes.** Si el almacenamiento ya es persistente, reutilizar
   su nombre exacto. No crear otro volumen para «normalizar» el nombre. Si los datos
   están en la capa del contenedor, conservar el contenedor detenido y extraer
   `/app/data/.` con `docker cp` a un destino nuevo y seguro **antes de recrearlo**.
   Montar un volumen vacío encima oculta esos archivos. Si una migración de ubicación
   es necesaria: copiar a un volumen nuevo vacío, con el origen de solo lectura;
   preservar el árbol completo, propietario UID/GID 10001, manifiestos e identidad.
   Comparar archivos, hashes, colecciones y tamaño. Mantener el origen y su backup
   intactos durante el periodo de validación. No ejecutar `down -v`, `volume prune`,
   borrados recursivos ni sobrescrituras para reparar la instalación.

4. **Configurar Coolify según la modalidad real.** En Dockerfile, configurar
   Persistent Storage del recurso para el mismo almacenamiento inspeccionado y
   destino `/app/data`; comprobar el resultado con Docker inspect después de desplegar.
   En Compose, los montajes se declaran en el Compose; conservar `gianna_data` y su
   ámbito real si ya apuntan a los datos correctos. Para fijar un volumen existente
   fuera del ámbito de proyecto, hay un override optativo:

   ```bash
   # Solo después de inspeccionar y respaldar este nombre EXISTENTE.
   export GIANNA_DATA_VOLUME='NOMBRE_REAL_INSPECCIONADO'
   docker volume inspect "$GIANNA_DATA_VOLUME"
   docker compose -f compose.yaml -f compose.persistent.yaml config --volumes
   ```

   `external: true` impide crear silenciosamente un volumen vacío. Usar ambos archivos
   en el recurso si la modalidad lo permite, o trasladar esa declaración de volumen
   al Compose que efectivamente interpreta Coolify. No cambiar build pack/proyecto
   como parte rutinaria de esta corrección. Los controles concretos de Coolify 4.6.0
   deben verificarse en esa instalación; las guías enlazadas reflejan la documentación
   consultada. Mantener una sola instancia y un solo servidor con este volumen local.

5. **Desplegar la imagen preparada.** Con autorización, apuntar la imagen/commit
   nuevos a los mismos SQL, claves, dominios y volumen. Las migraciones de trabajos
   agregan intentos y fecha de reintento; no modifican contenido ni publicación.
   Confirmar UID/GID, montaje real, espacio libre y conectividad al hub para artefactos
   faltantes. No ejecutar setup_env ni regenerar claves existentes.

6. **Recuperar automáticamente la publicación actual.** El worker debe encontrar
   `02816091d7d3435f882b04378a9c9c66` si sigue siendo la publicación administrativa,
   cargar su propio perfil y restaurar su colección a partir de sus 262 fragmentos
   si el diagnóstico confirma esa fotografía. No importar de nuevo el borrador ni
   publicar otra base para solucionar la ausencia física. Revisar el trabajo y
   `/health/knowledge`. Si falla, ejecutar la CLI en diagnóstico y corregir la causa
   antes de reintentar. Este documento no afirma haber examinado esos datos reales.

7. **Cambio de volumen detectado.** `storage_mismatch` bloquea recuperación y consultas.
   Primero corregir el montaje al original. Solo cuando el reemplazo sea deliberado,
   respaldado y comprobado, usar:

   ```bash
   python -m scripts.recover_knowledge --apply --adopt-storage
   ```

   La adopción es explícita, no omite la validación de fotografía/huella/índice y no
   publica. La primera instalación de esta protección no conoce el UUID anterior;
   por eso los pasos 1–3 son imprescindibles. Tampoco un mountpoint demuestra por sí
   solo que el host dispone de backups o un disco durable.

8. **Validar antes de reabrir.** Comprobar mismo ID activo y perfil, conteo esperado,
   modelo/reranker cargados, FTS, `available:true` y recuperación de fichas/citas reales
   en Laboratorio sin generación. Después, con autorización del responsable de cuota,
   probar una conversación real de Ollama, sus fuentes y el frontend público. Verificar
   estados temporales en la isla React. Reiniciar y recrear el contenedor conservando
   los mismos montajes; repetir **una consulta de evidencia**, no solo healthchecks.
   Registrar imagen, commit, huella, versión, tiempos y resultado.

## Rollback

Mantener la imagen previa y el volumen original durante la migración. Ante un fallo
de código, volver a la imagen previa con **los mismos SQL, claves y volumen**; revisar
su compatibilidad con el perfil de la publicación. Las columnas nuevas son aditivas:
no borrarlas ni restaurar un dump antiguo automáticamente. Las colecciones canónicas
restauradas siguen siendo LanceDB del mismo perfil. Si hubo una migración de ubicación,
volver al origen preservado solo tras detener escrituras y evaluar los cambios
producidos desde la copia; no descartar nuevas cargas o cambios administrativos.

Una restauración completa de SQL+volumen por desastre requiere mantenimiento y un
punto de recuperación coherente aprobado. Nunca reemplazar únicamente el puntero
activo o la huella. Ensayar el dump y el volumen en otra instancia, con las claves
correctas; verificar integridad, modelo exacto y recuperación antes de dirigir tráfico.

## Mantenimiento y pruebas

- Respaldar SQL y volumen de forma coherente, con al menos una copia externa. La
  frecuencia y retención las define el responsable según pérdida admisible; no hay
  borrado automático de backups o versiones. Verificar restauración periódicamente.
- Los pesos son recuperables por commit; un hub inaccesible puede impedir recuperar
  pesos perdidos. Conservar una copia verificada de los perfiles históricos necesarios.
- Vigilar espacio, trabajos agotados, RSS y duración de recuperación. Dos perfiles
  distintos solicitados pueden coexistir; no duplicar procesos para solucionarlo.
- Pruebas aisladas: `python -m pytest -q`; MariaDB real:
  `python -m pytest tests/test_mariadb_import.py --mariadb-docker -q`.
- Prueba definitiva aislada (Docker, red para pesos, sin .env ni Ollama):
  `python -m pytest tests/test_recovery_docker.py --recovery-docker -q -s`.
  Crea exclusivamente recursos temporales propios y registra evidencia en
  `reports/persistence/recovery-docker.json`. No apuntar fixtures a producción.

Referencias primarias: [almacenamiento persistente de Coolify](https://coolify.io/docs/core/persistent-storage/storage-mounts/overview)
y [ciclo de vida y backup de volúmenes Docker](https://docs.docker.com/engine/storage/volumes/),
consultadas el 07/11/2026. Un volumen persistente no sustituye un backup.
