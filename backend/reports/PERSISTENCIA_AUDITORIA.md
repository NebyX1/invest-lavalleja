# Auditoría y diseño de persistencia — 07/11/2026

Base de trabajo: backend institucional `a4f996b3c303aa7ac69042713de0723c120d990f`.
No se accedió al VPS, a Coolify ni a la base de producción. Los datos del incidente
(versión `02816091d7d3435f882b04378a9c9c66`, 262 fragmentos, colección ausente)
son los aportados por el responsable. La causa concreta del montaje productivo
permanece pendiente de la inspección descrita en `docs/RECUPERACION.md`.

## Causas comprobables en el código anterior

| Hallazgo | Lugar y consecuencia |
| --- | --- |
| Warmup sin recuperación de artefactos | `gunicorn.conf.py:post_worker_init` → `Jobs.start` → `execute_job(warmup)` → `Embeddings.load`. `verified_manifest` solo aceptaba pesos locales; no los recuperaba cuando faltaban. El trabajo fallaba y no había una política de reintento automático acotada. |
| Falso disponible | `routes/public.py:chat_config` comprobaba el modelo/huella, pero no el índice de la versión activa. Recuperar únicamente los pesos habilitaba un chat sin colección. |
| Salud insuficiente | `LanceStore.health` ejecuta `list_tables`: mide conectividad, no la existencia de `versions.collection_name`. `/health/ready` mide SQL/administración. Ninguna de esas señales prueba RAG listo. |
| Excepción física sin traducción | Abrir una colección perdida desde `LanceStore.search` propagaba la excepción de almacenamiento hasta el manejador genérico HTTP 500. |
| Datos físicos fuera de SQL | `Config.data_dir`, `model_dir` y `lance_dir` concentran pesos, tokenizadores, manifiestos, uploads, exports e índices bajo `/app/data`. Sin un montaje externo real, los pierde el reemplazo del contenedor. |
| Nombre dependiente del recurso | `compose.yaml` usa `gianna_data`, con ámbito de proyecto. Cambiar el proyecto/recurso puede seleccionar otro volumen. Un despliegue Dockerfile no aplica automáticamente ese Compose. |
| Cancelación confundida con parada | `progress` lanza `Cancelled` tanto por petición administrativa como por detener el proceso. Ahora la parada ordenada reencola; una cancelación administrativa se conserva. Una terminación abrupta se recupera al vencer el lease. |

La desaparición simultánea de modelos e índice es compatible con pérdida del
montaje, cambio de volumen o de DATA_DIR; el código local no prueba cuál ocurrió
en Coolify. No se modificó un recurso productivo para comprobarlo.

## Datos recuperables y frontera editorial

MariaDB es la autoridad editorial: `versions`, `version_records`, `version_sources`,
`chunks` y `active_knowledge`. `chunks.vector_json` contiene los vectores persistidos;
`chunks.content_json` conserva texto, representación lexical original (`sparse_text`),
metadatos y hash. Esto permite reconstruir el índice físico sin volver a fragmentar,
reescribir contenido ni calcular nuevos embeddings. El caché solo sirve si coinciden
huella y hash. Un respaldo técnico validado puede completar vectores ausentes.

La restauración rechaza: conteos/cobertura incompletos, audiencia interna, fuentes
no incluidas en la versión, metadatos inconsistentes, hash distinto, dimensiones
incorrectas, valores no finitos, vectores vacíos o huella distinta del runtime.
También contrasta el contenido completo de la tabla física, no solo su cantidad.
La ausencia de una prueba suficiente conserva la publicación y deja el chat en 503.

No se utiliza `records` ni `sources` del borrador para restaurar. No se actualizan
`active_knowledge`, fotografías, perfil, estado editorial, fechas de publicación
ni vectores SQL. Publicar/despublicar sigue siendo una operación administrativa.
Una construcción editorial explícita sí conserva su flujo habitual.

## Arquitectura implementada

1. **Persistencia:** DATA_DIR explícito en la imagen; Compose existente preservado;
   override externo optativo que exige un volumen ya creado. En producción, el
   guard verifica un montaje exacto, rechaza tmpfs/ramfs/capa overlay y compara un
   UUID del volumen con MariaDB. Un volumen diferente requiere adopción supervisada.
   La primera asociación solo se registra después de validar y recuperar la versión.
2. **Arranque:** Flask migra SQL sin cargar modelos. Un proceso Gunicorn inicia un
   worker de trabajos; este deduplica un warmup para el perfil activo. Los pesos
   válidos se verifican offline y se reutilizan. Los ausentes se descargan por
   revisión fijada, verificando LFS SHA-256 o Git blob del commit y manifiesto local
   SHA-256. Timeouts y reintentos finitos; ninguna descarga en HTTP.
3. **Recuperación:** validar fotografía → recuperar/cargar el perfil original →
   verificar huella → reconstruir staging si hace falta → crear FTS español →
   contrastar todas las filas → promoción local → inferencia y búsqueda de prueba
   → respaldo técnico → disponible. El índice dañado se conserva en cuarentena.
4. **Concurrencia:** lock MariaDB independiente de las transacciones cortas y lock
   de archivo del volumen; incluyen CLI, construcciones, eliminaciones y recuperación.
   El proceso mantiene una instancia por perfil solicitado y comparte su presupuesto
   de inferencia. No aumenta la cantidad de workers Gunicorn.
5. **Interrupción:** merges por ID sobre staging determinista; promoción por rename
   de directorio local dentro del mismo volumen. LanceDB OSS 0.40 no implementa
   `rename_table`; se verificó con su librería real que datos y FTS sobreviven al
   movimiento del dataset local. Una interrupción entre cuarentena y promoción se
   retoma sin sobrescribir el original ni modificar el puntero SQL.
6. **Disponibilidad:** proceso, SQL/administración y conocimiento tienen señales
   separadas. `/health/knowledge` y `/api/config` requieren modelo compatible,
   colección, esquema, conteo, FTS operativo y comprobación completa en este proceso.
   Cambiar la versión física/inodo invalida esa comprobación. Las búsquedas físicas
   fallidas se traducen en 503 estructurado incluso si el daño sucede tras el chequeo.
7. **Operación:** CLI de diagnóstico por defecto, aplicación explícita y adopción
   supervisada; estados/logs y política de tres intentos con backoff. No hay limpieza
   automática de índices, copias ni cuarentenas. El healthcheck Docker sigue siendo
   `/health/live`, sin descargas ni consultas al generador.

## Límites y riesgos de migración

- La identidad del volumen detecta sustituciones accidentales; no es una firma
  criptográfica del servidor ni detecta por sí sola una copia deliberada del UUID.
  La validación de la fotografía/índice aporta un control distinto.
- El primer despliegue con esta protección todavía no tiene una identidad previa.
  Es obligatorio inspeccionar y respaldar el almacenamiento existente antes de
  asociarlo. Cambiar arbitrariamente el nombre del volumen puede ocultar datos.
- La huella incluye ONNX Runtime. Si producción utilizó otra versión de runtime,
  se conserva el bloqueo: recuperar la imagen/runtime exactos o un respaldo
  compatible. No se reescribe una huella ni se reembebe en otro espacio.
- Bekko/Horizon conserva su perfil y representación originales. Las pruebas de
  compatibilidad histórica usan una fotografía representativa y un doble de modelo;
  no sustituyen una restauración de una publicación histórica productiva real.
- Los respaldos JSON locales son otra copia técnica en el mismo almacenamiento,
  no un respaldo ante pérdida del VPS. Es obligatorio un dump y copia externa
  verificable del volumen, además de las claves de cifrado custodiadas aparte.
- El montaje es local a un servidor. Esta solución conserva una instancia API;
  no propone almacenamiento compartido multiserver ni varios workers ONNX.
- Las consultas hacen verificaciones acotadas del dataset y FTS; la comparación
  completa ocurre en el worker/CLI. No se promete detectar corrupción de hardware
  que no cambie metadatos ni falle al leer; para eso existen respaldos y simulacros.

Resultados reproducibles: `reports/VALIDACION.md` y `reports/persistence/`.
