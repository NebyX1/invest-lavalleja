# Validación del agente RAG

## Seguridad semántica · 07/11/2026 · 1.0.0-rc4

**Componente validado con el proveedor y modelo de la configuración local:**
Ollama Cloud, `deepseek-v4.1-flash`, política `semantic-safety-v3`, **20/20 casos**.
Destino de publicación: `NebyX1/invest-lavalleja`, rama `main`, `backend/`.
La instancia productiva de la IDL y su selección actual del panel no se presentan
como verificadas: la configuración local disponible no tiene `DATABASE_URL`.
No se modificaron secretos, configuración, datos ni contenido productivo.

La captura reproducía una salida `clarify` determinista sin modelo. Se eliminó
esa ruta y su plantilla empresarial. El control semántico corre antes de revisar
publicación/índice, mapa de guía, búsqueda, herramientas y fallback. Pregunta e
historial se revisan como un expediente JSON, sin reproducir los roles como una
conversación abierta. El resultado debe ser completo, coherente y tipado;
errores, claves duplicadas y prosa junto a herramientas no autorizan orientación.
Las anclas de riesgo pendientes permanecen cifradas, incluso si falla el
proveedor o se recorta el historial. Los rechazos técnicos registran causa
controlada, sin preguntas, historial ni prosa del proveedor.

| Comprobación final | Resultado y evidencia |
| --- | --- |
| Suite completa con MariaDB y MinIO reales | **571 passed, 8 skipped**, 88,22 s; `safety/full-suite-final.xml` y `.log` |
| Evaluador offline, incluido provider-env, límites, procedencia y cierre | **68 passed**, incluidos en la suite completa |
| Evaluación semántica real autorizada | **20/20**, 20 despachos HTTP; `safety/configured-model-v3.json` y `.log` |
| Frontend | `npm run check`: 42 archivos, cero errores, avisos e indicios; `safety/frontend-final.log`. ESLint del componente aprobado antes de esta evaluación; el componente no cambió desde entonces |
| Runtime | Imagen final construida como usuario 10001; prompt/código coinciden por SHA-256 con el modelo evaluado; contrato de esquema correcto sin red y en modo sólo lectura; `safety/image-validation-final.json` y `image-build-final.log` |

En la política final las tres variantes de la captura producen `clarify` con
`minor_safeguarding`: bloquean orientación empresarial y preguntan por la
protección de menores. No solicitan horarios ni alcohol ni ofrecen ubicaciones.
Los casos explícitos de explotación y sus seguimientos se rechazan; los ocho
controles legítimos se permiten. La coacción laboral se rechaza como `other_harm`
sin inventar una dimensión sexual ni menores. Los criterios originales del
corpus no se modificaron. La mediana fue 734,5 ms y el máximo 890 ms en esta
corrida; no son garantías de latencia del servicio.

Se conservan **todos los informes fallidos**. La primera corrida cloud v1 logró
19/20: un historial largo produjo herramienta más prosa; su único reintento
acotado también falló y el flujo quedó cerrado (`configured-model.json`,
`configured-model-retry.json` y su `.provenance.json`). V2 cambió la entrada a un
expediente y logró 19/20, con rechazo correcto pero etiquetas erróneas de coacción
laboral (`configured-model-v2.json`). V3 precisó categorías generales y separó
las dimensiones de menores/acceso adulto; aprobó los mismos 20 criterios sin
relajar el parser. La autorización cubrió esos **20 casos distintos con
reintentos acotados: 61 despachos HTTP en total**, incluidas tres corridas y el
reintento de diagnóstico. No se harán nuevas llamadas de pago para esta entrega.

Los ensayos anteriores con Qwen3:4b y Phi4-mini locales también quedan como
fallidos. Phi4-mini alcanzó 3/20 en `safety/local-phi4-corpus-final.json`; sus
resultados no acreditan producción. Los primeros informes locales contaban
sólo solicitudes completadas; el evaluador actual cuenta también las fallidas
y separa invocaciones de evaluación de despachos HTTP, sin afirmar facturación.

**Límites:** es un corpus sintético acotado del componente semántico, con el
modelo del entorno existente; no es un ensayo completo del chat productivo ni
una garantía de ausencia de errores. El informe declara
`production_runtime_unverified:true` y conserva hashes de prompt, esquema,
`risk.py`, `runtime.py` y corpus. No se accedió al panel ni al servidor de la IDL.
Las ocho omisiones de la suite corresponden a cinco casos de documentación
privada ausente y tres opt-in de navegador/recuperación de contenedores. Las
pruebas reales de recuperación y navegador de rc3 siguen en `minio/` y no se
atribuyen a una nueva ejecución. No se modificó persistencia en esta entrega.

Procedimiento: [Seguridad de consultas](../docs/SEGURIDAD_CONSULTAS.md).

## Persistencia MinIO · 07/11/2026 · 1.0.0-rc3

Destino: **`NebyX1/invest-lavalleja`, rama `main`, `backend/`**. Producción usa
MinIO de forma predeterminada con `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`,
`MINIO_SECRET_KEY`, `MINIO_SECURE`, `MINIO_BUCKET_NAME` y `MINIO_PUBLIC_URL`.
No se solicita otra variable para elegir el motor. MariaDB conserva contenido,
permisos, fotografías y puntero; MinIO conserva importaciones, respaldo técnico
y modelos verificados. `/app/data` es caché reconstruible y su montaje local no
es un requisito del arranque productivo.

La integración incluye inspección de bucket privado, creación por el worker si
falta, vínculo de identidad SQL/MinIO reanudable, namespace propio, transferencias
con SHA-256 y streaming de ONNX, recuperación de importaciones pendientes y
rechazo de buckets/objetos ajenos. Un alias distinto del endpoint se acepta si
el marcador verifica la misma identidad. No se modifica una política ajena,
publicación, perfil de modelos ni el almacenamiento local anterior.

Procedimiento vigente: [MinIO y redeploy](../docs/MINIO_PERSISTENCIA.md).

| Verificación final | Resultado y evidencia |
| --- | --- |
| Suite completa, MariaDB y MinIO reales | **464 passed, 8 skipped**, 107,30 s; `minio/full-suite.xml` y `.log` |
| Almacenamiento/configuración/fuentes/artefactos focalizados | **88 passed**; `minio/storage.xml` y `.log`, incluidos 20 casos MinIO/configuración |
| Panel y observabilidad, Chromium/WebKit | **22 passed**, 45,43 s; `minio/browser.xml` y `.log` |
| MinIO + MariaDB + LanceDB + ONNX reales | **1 passed, 6 escenarios**, 90,14 s; `minio/redeploy.xml`, `.log`, `redeploy.json` y `redeploy-events.jsonl` |
| Compatibilidad local anterior explícita | **1 passed, 11 escenarios**, 240,46 s; `minio/legacy-recovery.xml` y `.log`; inventario/eventos en `persistence/` |
| Imagen productiva | Docker multietapa, UID/GID 10001, versión 1.0.0-rc3; `minio/image-build.log` |
| Dependencias | Gate correcto con RAW preservado y una clasificación medida del Connector/C; `minio/security/20261108T002452Z-86d2b7ee/decision.json` |

La prueba MinIO creó exclusivamente dos fichas públicas y una interna. Se
eliminó el contenedor de la API y se levantaron **dos contenedores nuevos, con
cero montajes**, recuperando modelos desde MinIO e índices desde la fotografía
verificada. `/health/installation` y `/health/knowledge` devolvieron 200. La
misma publicación, vectores y digest editorial se conservaron; no hubo
`storage_not_mounted` ni claves/sesiones en sus registros. No se llamó al
generador. Se registraron eventos JSON correlacionados entre arranques.

Las ocho omisiones generales son cinco casos de corpus privado y tres opt-in;
los tres opt-in se ejecutaron aparte y pasaron. El corpus privado y la
instalación productiva de la IDL no se presentan como comprobados. No se leyeron
credenciales de MinIO de otros proyectos ni se intervino el servidor productivo.

La auditoría conserva el aviso RAW de MariaDB `PYSEC-2026-217` y verifica por
separado el Connector/C 3.4.9 de la imagen Linux. No hay hallazgos sin resolver
según ese gate; no se afirma que el RAW esté vacío ni que sea una auditoría de
todo el sistema operativo. La auditoría local corre en Windows y registra esa
plataforma; la clasificación corresponde únicamente al cliente de la imagen.

La CI del repositorio central ejecuta las regresiones reales de MinIO y ambos
caminos de recuperación de contenedores, además de sus comprobaciones anteriores.
Las secciones siguientes conservan el historial de las entregas previas y sus
límites; los requisitos de volumen local de rc2 quedan sustituidos en producción.

## Integración en el repositorio central · 07/11/2026

Destino de esta entrega: **`NebyX1/invest-lavalleja`, rama `main`, directorio
`backend/`**. La implementación procede del commit validado `5576b6a` del backend
independiente. Se comprobó que la base de `backend/` en `e408c1b` coincidía
exactamente con la base `13fbfcb` usada durante la reestructura.

Se trasladan implementación, migraciones, pruebas y evidencia, y se adapta
`.github/workflows/backend.yml` de la raíz para ejecutar los seis jobs desde
`backend/`, recoger sus artefactos y aislar las dependencias de Playwright.
El Dockerfile y los requisitos de la API conservan el contenido validado.
Las secciones siguientes documentan las pruebas de esa implementación; los
resultados de integración en este directorio se guardan en `integration-main/`.
La publicación del código no acredita un despliegue ni una intervención en la
base productiva.

Verificación ejecutada desde `backend/` en esta integración:

- **444 passed, 7 skipped**, 92,66 s, suite completa con MariaDB real;
  `integration-main/full-suite.xml` y `.log`.
- **22 passed**, 38,58 s, panel/logs con Chromium y WebKit reales;
  `integration-main/browser.xml` y `.log`. Las seis capturas de `monitoring/`
  se regeneraron en esta ejecución.
- Imagen `gianna-invest-main:validation` construida con `backend/` como contexto;
  `integration-main/image-build.log`. Contrato de esquema comprobado dentro de
  esa imagen sin red ni conexión a la base.
- **137 archivos de implementación y pruebas idénticos** al commit validado,
  comprobados normalizando únicamente los finales de línea; destinos y rutas de
  artefactos de los seis jobs verificados en `integration-main/transfer.json`.

Las siete omisiones son cinco casos de corpus privado y los dos opt-in. El
opt-in de navegadores se ejecutó aquí; los once escenarios de contenedores de la
implementación idéntica conservan su evidencia en `persistence/`.

## Reestructura de instalación, cola y logs · 07/11/2026 · 1.0.0-rc2

Entrega sobre `origin/main` **13fbfcb**, en la rama local
`codex/reconciliacion-arranque`. Las secciones siguientes conservan resultados
anteriores; esta sección describe la revisión operativa actual. No se intervino
Coolify, la base productiva ni sus volúmenes, y no se llamó a generación pagada.

### Causas verificadas y cambios

- El guard anterior exigía un mountpoint exactamente igual a DATA_DIR. Ahora
  inspecciona el montaje que realmente cubre la ruta, incluidos ancestros y
  montajes anidados, y distingue ausencia, sólo lectura, permisos, espacio e identidad.
- Configurar HTTP creaba directorios antes de inspeccionar persistencia. El
  arranque administrativo ahora llega al diagnóstico incluso sin el volumen;
  la inicialización física y la cola esperan un inventario válido.
- Warmup reintentaba cualquier fallo y mantenía el error/fecha del intento
  anterior en un trabajo reencolado. Hay clasificación de causas, esperas visibles,
  límite de intentos, limpieza de estado actual e historial separado.
- JSON corrupto se decodificaba fuera del bloque de ejecución y podía dejar
  trabajos running hasta vencer el lease. La validación, fencing y terminación
  identificada forman parte de cada intento.
- `schema_versions` no acreditaba que columnas/defaults siguieran presentes.
  Ahora se revisa el namespace, historial y contrato completo de columnas antes
  de migrar instalaciones existentes. Sólo se reparan DDL conocidos idempotentes;
  la pérdida editorial, un historial no verificable o una base ajena bloquean sin
  fabricar datos ni resetear versiones.
- Un respaldo vectorial corrupto podía bloquear vectores SQL válidos. SQL,
  respaldo y caché se validan independientemente; dos fuentes válidas distintas
  siguen bloqueando con una razón concreta.
- El panel abandonaba polling ante un error de red y no seguía una recuperación
  de failed después de redeploy. Ahora se reanuda con backoff, muestra datos
  desactualizados y cambia acciones, resultado e historial sin recargar.

La estructura, estados, decisiones y procedimiento se documentan en
[arranque y diagnóstico](../docs/INSTALACION_Y_DIAGNOSTICO.md).

### Verificación final

| Comprobación | Resultado y evidencia |
| --- | --- |
| Python 3.12.13, pytest 9.0.3, suite completa con `--mariadb-docker` | **442 passed, 7 skipped**, 75,62 s; `persistence/full-suite.xml` y `.log` |
| Panel SSR/API, logs y navegador con opt-in | **22 passed**, 39,17 s; `monitoring/final-browser.xml` y `.log` |
| Navegadores | Chromium y WebKit reales, Flask/SQL aislados; 503 transitorio, failed→running sin recarga, acciones, bfcache/pagehide, XSS como texto, 390/1280 px; seis PNG y `monitoring/browser-validation.json` |
| MariaDB: esquema real fresh y upgrade-v2 | Defaults ausentes/apóstrofos, columna técnica/journal ausentes, migración parcial e irreparable editorial; `persistence/schema-reconciliation-mariadb.xml` |
| Namespace SQL ajeno/sin historia | Dos casos sin crear tablas o historia; `persistence/database-namespace.xml` |
| Docker/MariaDB/LanceDB/ONNX reales | **1 passed, 11 escenarios**, 483,86 s; `persistence/container-recovery.xml`, `.log`, `recovery-docker.json` y `recovery-docker-events.jsonl` |
| Integridad de contrato y sintaxis | `python -m scripts.schema_contract`, compilación Python y `git diff --check` correctos |
| Imagen | Dockerfile multietapa, UID/GID 10001 y versión 1.0.0-rc2; `persistence/production-image-build.log` |

Las siete omisiones generales son cinco casos de corpus privado no incluido y
dos opt-in. Los opt-in de navegadores y contenedores se ejecutaron aparte y
pasaron; no se presenta el corpus privado como validado.

La prueba de contenedores creó **dos fichas públicas y una interna**, con
MariaDB exclusiva temporal, volumen y red propios. Montó `/app/data` y utilizó
`DATA_DIR=/app/data/runtime`, demostrando el montaje ancestro real. Sin volumen,
la API administrativa siguió accesible: mostró `storage_not_mounted`, dejó el
trabajo con cero intentos y no descargó modelos.

Al reconectar el volumen original, recuperó automáticamente el **mismo trabajo**
`4546526dd37841b59287dbaddbcaf3f4`, conservando la publicación
`dd5dcf26f0c8492398793396583c81c4` y el digest editorial. También pasaron reinicio,
reemplazo de contenedor, colección ausente/incompleta y retirada/restauración de
modelos. Se registraron **457 eventos JSON** con correlación entre arranques y
comprobaciones contra filtración de claves, contraseñas y sesión. Las búsquedas
de evidencia recuperaron contenido real del índice, sin llamar al generador.

La muestra final fue **1,232 GiB sobre 2 GiB**, con dos CPU. Es una muestra de la
base sintética, no el pico de consumo ni garantía para una base de producción.
Todos los contenedores, red, volumen y etiqueta de imagen aleatoria creados por
la prueba se retiraron; se conserva la imagen de validación nombrada explícitamente.

### Logs y diagnóstico

JSON UTC en stderr, con boot/request/job, intento, etapa, tiempos, código,
ubicación módulo/función/línea y cadena de tipos/causas. Las descargas registran
perfil, revisión, archivo y bytes reales. `operational_events` y `job_events`
conservan historia SQL después de un reemplazo; el diagnóstico presenta el
inventario y el plan sin alterar el contenido.

Los tests comprueban redacción de secretos, URLs con credenciales, parámetros
SQL, cuerpos, prompts y excepciones. No se registra `str(exc)` arbitrario ni se
copian documentos o respuestas del proveedor al registro técnico.

### Dependencias y criterio del aviso MariaDB

pytest se actualizó de 9.0.2 a **9.0.3**. La auditoría inicial se conserva como
evidencia histórica, no como resultado de la candidata final.

El gate de dependencias conserva el JSON original de pip-audit y su SHA-256.
`PYSEC-2026-217` sigue visible: se clasifica por separado como
`runtime_not_affected` sólo al verificar **el mismo driver** y Connector/C
**3.4.9** en la imagen Linux inmutable. Otros hallazgos, versión desconocida,
evidencia ausente o un cliente vulnerable hacen fallar el gate. Las 28 pruebas
de esta política forman parte de la suite general. No se usa `--ignore-vuln`.

La ejecución final está en `security/20261107T214209Z-eaa6437e/`: un hallazgo RAW
preservado, uno clasificado con evidencia y cero sin resolver. El auditor local
corrió en Windows, hecho registrado en el informe; **el cliente Windows 3.4.7 no
recibe esa clasificación**. En CI la auditoría corre en Linux y construye la
imagen del mismo commit. Esto no es un escáner completo del sistema Debian ni una
certificación de toda la infraestructura.

Criterio contrastado con el [aviso oficial de MariaDB](https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm)
y la [incidencia de clasificación PyPI](https://github.com/pypa/advisory-database/issues/400).

### Límites y siguiente despliegue

Esta revisión prueba la mecánica de reconciliación y la integridad sobre datos
sintéticos reales, no la fotografía privada del servidor ni la calidad factual
de sus respuestas. No modifica modelos, espacios vectoriales, contenido,
publicación, dominios ni claves productivas. Un montaje que no exista en el VPS
debe corregirse en Docker/Coolify: el programa lo detecta y explica, no puede
crearlo desde el contenedor. Antes de liberar, conservar respaldo e inspeccionar
la instalación real con la misma imagen y el procedimiento documentado.

La rama local queda preparada para revisión. No se realizó push ni despliegue
remoto como parte de esta reestructura.

## Persistencia y recuperación automática · 07/11/2026

Implementación sobre el backend institucional `a4f996b`, rama local
`codex/persistencia-recuperacion`. No se modificó producción ni se llamó a Ollama.
Diagnóstico: [auditoría](PERSISTENCIA_AUDITORIA.md). Operación, migración y rollback:
[procedimiento](../docs/RECUPERACION.md).

| Comprobación ejecutada | Resultado real |
| --- | --- |
| Suite completa en Docker, Python 3.12 y dependencias fijadas | **273 passed, 16 skipped**, 42,77 s |
| MariaDB 11.4 real, esquemas temporales nuevos y actualización desde v2, SQL estricto | **10 passed, 2 skipped**, 10,81 s |
| Docker + MariaDB + LanceDB 0.40 + ONNX Runtime 1.31 + pesos reales fijados | **1 passed**, 236,32 s; ocho comprobaciones registradas en [JSON](persistence/recovery-docker.json) |
| Frontend (mismos archivos y dependencias del repositorio institucional) | Astro check: 0 errores/advertencias; ESLint sin hallazgos; Vitest **9/9**; build estática correcta |
| Playwright del chat en escritorio y móvil | **16 passed**, 58,8 s; incluye estados de restauración, 503 y vuelta a disponibilidad sin recarga |

Al integrar la corrección en el repositorio central, se repitieron las pruebas sobre
un árbol aislado sin `.env` ni corpus privado: **274 passed, 16 skipped** tanto en
Python 3.12 como en 3.13, y **10 passed, 2 skipped** con MariaDB real. La verificación completa del portal
incluyó **37 pruebas Playwright aprobadas y una omitida**, además de tipos, lint,
unidades y build. La simulación de `simplify_env` se corrigió para no crear directorios
de almacenamiento y tiene una prueba de regresión específica.

La auditoría `pip-audit -r requirements.txt` señaló **PYSEC-2026-217** en el
paquete Python preexistente `mariadb==1.1.14`, sin proponer una actualización de
ese paquete que resuelva el aviso. El [aviso original de MariaDB](https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm)
se refiere a versiones de Connector/C y está corregido en la 3.4.9; una [incidencia
abierta en PyPA](https://github.com/pypa/advisory-database/issues/400) cuestiona
la aplicación de ese rango de versiones al paquete Python. En la imagen local se
comprobó Connector/C **3.4.9**. La versión de la biblioteca utilizada por producción
no se inspeccionó y debe verificarse; la auditoría sigue activa y puede señalar este
aviso hasta que se resuelva su clasificación.

Las 16 omisiones de la suite general son tres pruebas del corpus privado, doce
pruebas MariaDB optativas y una prueba Docker optativa. Las suites optativas se
ejecutaron aparte: en MariaDB solo quedaron omitidos dos casos que necesitan la
guía privada. No se sustituyó esa guía por contenido inventado para declararla validada.

### Evidencia de recreación real

El test Docker generó una base sintética de **dos fichas públicas y una interna**;
aprobó e indexó únicamente las públicas con Granite/mMARCO reales y la publicó
exclusivamente en la MariaDB temporal del test. El laboratorio HTTP autenticado
recuperó el texto `PINO-314` después de:

- Arranque automático con una instancia nueva del motor.
- Reinicio del proceso/contenedor y posterior reemplazo completo del contenedor
  API usando el mismo volumen.
- Pérdida de la colección canónica, conservando versión/vectores en MariaDB.
- Colección incompleta, preservada antes de restaurar.
- Retirada de todos los modelos locales y recuperación automática por revisión fijada.

Durante las dos averías de índice se comprobó `available:false` y POST `/api/chat`
**503**, sin HTTP 500 y sin generación. En cada recuperación se comparó un digest
de bases, borradores, fuentes, versiones, fotografías, chunks y puntero activo:
permanecieron idénticos. Huella real del perfil utilizado:
`2eea22e49a8edf18fa68961adc43568bfab570af7f4efe68fb9b6c45875061ab`.

La muestra final de uso del contenedor fue **1,228 GiB sobre un límite de 2 GiB**,
con límite de 2 CPU. Es una muestra de este test pequeño, no el pico de memoria,
una prueba de concurrencia ni una garantía de capacidad para una base mayor.
La configuración conserva un worker Gunicorn; las pruebas de idempotencia comprueban
que un perfil ya cargado no vuelve a cargar sus pesos.

### Matriz de regresión solicitada

| Escenario | Cobertura |
| --- | --- |
| Reinicio normal y evidencia recuperada | Docker/MariaDB/LanceDB/ONNX reales y consulta al laboratorio HTTP |
| Reemplazo de contenedor | Mismo volumen, misma publicación/digest, nueva instancia de motor, consulta real |
| Modelos ausentes/incompletos/manifiesto inválido | Ausencia real en Docker; transporte determinista para interrupción, hashes y manifiestos |
| Colección ausente | Incidente reproducido con modelo cargado, config no disponible, chat 503 y restauración exacta |
| Índice incompleto/FTS ausente o incompatible | Conteo incompleto real en Docker; LanceDB real para FTS/esquema y contenido alterado |
| Perfil incompatible | Rechazo de huella distinta, sin reinterpretar vectores ni cambiar versión |
| Interrupción de recuperación | Staging parcial y directorio sin manifiesto en LanceDB real; reanudación sin duplicados; descarga interrumpida con transporte doble |
| Protección editorial | Digest SQL completo antes/después, borrador interno excluido, ninguna publicación automática |
| Perfil histórico | Fotografía representativa v2, texto lexical propio y doble de motor distinto; no carga el perfil nuevo |
| Recursos/reintentos | Límites Docker, reutilización por perfil, deduplicación, leases vencidos/nulos, backoff y tres intentos máximos |

También se verificaron: cambio de volumen y adopción explícita; rechazo de montaje
efímero; exclusión de dos escritores; caché por huella/hash; respaldo técnico
independiente; CLI sin escrituras; parada ordenada reencolada; SQL indisponible con
503 mientras `/health/live` sigue respondiendo. Los dobles de modelo/transporte se
identifican como tales: no son un benchmark semántico.

### Archivos y límites de entrega

| Grupo | Cambios |
| --- | --- |
| Motor de recuperación | `services/recovery.py`, `artifacts.py`, `storage.py`, `vector_store.py` |
| Integración y disponibilidad | `services/jobs.py`, `rag.py`, `retrieval.py`, `routes/public.py`, `routes/admin.py`, `web.py` |
| Persistencia/arranque | `db.py`, migraciones SQLite 006/MariaDB 004, `config.py`, `Dockerfile`, `compose.persistent.yaml`, `wsgi.py`, `gunicorn.conf.py` |
| CLI existente y nueva | `recover_knowledge.py`, `prepare_models.py`, `chat_cli.py`, `evaluate_retrieval.py`, `evaluate_answers.py` |
| Regresiones | `test_knowledge_recovery.py`, `test_artifact_recovery.py`, `test_recovery_docker.py`, helper y adaptación de fixtures/migraciones anteriores |
| Operación | `AGENTS.md`, `COOLIFY.md`, `RECUPERACION.md`, `PUESTA_EN_MARCHA.md`, `RAG_ENGINE.md`, esta validación y auditoría |
| Frontend separado | `GiannaChat.tsx`, tipo `Config`, dos casos E2E y documentación del contrato de disponibilidad |

Pendiente en producción: inspeccionar los montajes y runtime reales de Coolify 4.6.0,
respaldar/restaurar una copia verificable de la instalación, contrastar la fotografía
real `02816091…` y aplicar el plan con autorización. No se afirma haber restaurado sus
262 chunks. No se ejecutó generación pagada ni se evaluó otra vez la calidad factual.
La compatibilidad histórica no se probó con los pesos reales Bekko/Horizon ni una
publicación histórica de producción; se conservan sus revisiones y se bloquea cualquier
huella incompatible. Las pruebas se realizaron sin desplegar ni modificar la instalación productiva.

**Fecha:** 29/10/2026. **Revisión de documentación y recuperación:** 06/11/2026. **Alcance:** cambios locales; sin despliegue ni cambios en producción. La base de prueba local no tiene revisión editorial final.

Este informe describe el código actual. El informe del diseño anterior (planificador determinista) está en [historico/VALIDACION_agente_anterior.md](historico/VALIDACION_agente_anterior.md) y no aplica.

## Barreras para consultas sobre menores · 03/11/2026

El backend institucional incorporó rutas previas a la búsqueda para rechazar explotación explícita y continuaciones vinculadas, y pedir una aclaración neutral sobre eventos juveniles ambiguos. La orientación sexual no es una señal de riesgo. Se aprobaron **70 pruebas focalizadas** del agente y la API con dobles; también se verificaron por HTTP una aclaración y un rechazo en una instalación Docker local aislada. Estas pruebas no garantizan cobertura semántica completa ni sustituyen la revisión antes del despliegue. El detalle está en el [informe del backend institucional](https://github.com/IntendenciaDeLavalleja/invest-lavalleja-backend/blob/main/reports/VALIDACION.md).

## Reverificación del 06/11/2026

Se auditó la documentación contra el código y la base activa (`ca5f61b7…`, motor `granite-mmarco-lance-v3`, representación `cards-context-v5`). Se corrigieron referencias obsoletas a E5/Qdrant/FastEmbed, al prefijo `passage:` y a un reranker que se describía como parte del laboratorio cuando solo se usa en la verificación de modelos y en la evaluación comparativa.

Se volvieron a ejecutar los tres modos sobre las 51 preguntas: **híbrido** hit@1 0,745, hit@8 0,961, MRR 0,830, **144,9 ms**; **fusión con cross-encoder** hit@8 0,941, MRR 0,825, **6.023 ms**; **solo cross-encoder** hit@8 0,922, MRR 0,841, **6.571 ms**. Los controles de seguridad incorporados del backend institucional son posteriores a la implementación evaluada; estas mediciones corresponden a la recuperación del 29/10/2026. No se volvieron a ejecutar las 31 conversaciones contra el proveedor en esta fecha; los resultados de esa sección corresponden a la corrida original.

## Diagnóstico de lo que fallaba

| Síntoma en el chat | Causa verificada | Corrección |
| --- | --- | --- |
| "El proveedor de respuestas no está disponible" | El cliente trataba igual cualquier error HTTP, timeout de 80 s, respuesta vacía o recorte de contexto; el cross-encoder sumaba ~6 s por búsqueda y había varias por consulta | Reintentos con espera, modelo alternativo, plazo total de 100 s, reranker fuera del camino, respuesta degradada con fichas en vez de error |
| "No tengo documentado un perfil de zona…" para cualquier rubro fuera del catálogo | Un planificador de palabras clave decidía abstenerse antes de que el modelo viera la evidencia | Agente con herramientas: el modelo ve la evidencia y el mapa completo de la guía y decide qué buscar |
| Respuestas pobres con evidencia fragmentada | Registros de 60–200 caracteres ("Ocupación supuesta", "2 · Contrastar mercado") recuperados sin su contexto | Fichas autosuficientes (332 fichas: 257 públicas y 75 internas; se indexan las públicas) con cabecera contextual |
| Evidencia recortada | Tope artificial de 8.000 tokens por petición | Sin tope de 8K: hasta 36.000 caracteres de evidencia por respuesta |

El modelo configurado (`deepseek-v4.1-flash:1017`) existe en el catálogo real de Ollama Cloud (`/api/tags`) y respondió en 1,4–2,7 s con y sin herramientas, con llamadas de herramientas nativas también en `glm-5.3` y `kimi-k3`.

## Qué se midió y resultados

### 1. Recuperación (51 preguntas, `evals/retrieval_gold.json`, sin llamar al modelo)

| Modo | hit@1 | hit@3 | hit@5 | hit@8 | MRR | ms por búsqueda |
| --- | --- | --- | --- | --- | --- | --- |
| **Híbrido (camino de la consulta)** | 0,745 | 0,902 | 0,922 | **0,961** | 0,830 | 145 (promedio) |
| Híbrido + cross-encoder | 0,725 | 0,922 | 0,941 | 0,941 | 0,825 | 6.023 |
| Solo cross-encoder | 0,784 | 0,882 | 0,902 | 0,922 | 0,841 | 6.571 |

Fallos restantes del híbrido a k=8: contactos ("¿con quién hablo para permisos?"), "zona para un boliche" (no existe ficha) y riesgos. El agente los compensa reformulando.

### 2. Conversaciones contra el proveedor real (31 casos, `evals/dialogues.json`)

`python scripts/evaluate_answers.py` — tres corridas completas durante el desarrollo: **27/31, 29/31 y 28/31** casos sin observaciones automáticas; promedio **3,0–4,0 s por caso** (0,8 s un saludo; 1,3–2,5 s una pregunta de un solo paso; 5–8 s las que requieren varias búsquedas). Las observaciones restantes de cada corrida fueron falsos positivos del verificador, ya corregidos (fechas escritas como 31/12, cifras redondeadas de una tabla de la guía, variantes de redacción de "la guía no tiene un análisis"), o un caso real que se corrigió en el prompt (se omitía ganadería de un campo de 200 ha; ahora el agente consulta el mapa de la guía antes de afirmar que algo no está).

Además se revisaron a mano las respuestas de los casos críticos:

- **Hospedaje rural** (la consulta de la captura que fallaba): requisitos del Ministerio de Turismo con citas, aclaración de que el registro no cambia la categoría de suelo, dónde explora la guía el producto (hipótesis) y una pregunta final.
- **Boliche / gimnasio / restaurante** (rubros sin ficha): lo dice en una frase y aporta lo documentado (uso del suelo, Bomberos, ambiente, RUNAEV si hay comida, límites de Villa Serrana por iluminación nocturna) sin inventar demanda.
- **Rentabilidad de un hotel:** rechaza dar una cifra; usa el ejercicio didáctico de la guía aclarando que son supuestos y no datos de Lavalleja.
- **Seguimientos y correcciones** ("¿Y en Villa Serrana?", "No, te equivocás, en Minas hay vida nocturna"): usa el contexto y no repite la respuesta anterior.
- **Inyección de instrucciones, insultos, delitos, tema ajeno:** rechazo breve o respuesta fija sin llamar al modelo.

### 3. Pruebas automáticas y E2E

- `pytest` (backend): **193 passed, 15 skipped** (12 pruebas MariaDB opcionales que requieren `--mariadb-docker` y 3 del corpus privado no versionado). Incluye 28 pruebas nuevas del agente (herramientas, citas, degradación, mapa de la guía, privacidad de métricas) y el resto de la suite de seguridad, sesiones, índice y panel.
- Frontend: `npm run lint` sin hallazgos y `vitest` **9/9**.
- **Concurrencia por HTTP** contra la API local con el proveedor real: 4 conversaciones simultáneas respondieron 200 en 9–15 s (las ráfagas esperan turno hasta 30 s en vez de recibir un 429 inmediato).
- **UI real** (Astro en `localhost:4321` → API en `127.0.0.1:8001`): el flujo captcha → sesión → pregunta → respuesta con fuentes funciona con la consulta de la captura.

## Límites (importan)

- La respuesta la redacta un modelo no determinista: puede equivocarse aunque cite. Los controles automáticos detectan cifras ausentes de la evidencia, códigos internos, longitud y estados, pero **no** una afirmación errónea bien citada. Revisar el informe a mano tras cada cambio.
- Los conjuntos de 51 preguntas y 31 conversaciones los escribió el mismo equipo que ajustó el sistema: no son un holdout ciego ni evidencia de vigencia factual. Los números de recuperación miden cobertura de fichas, no exactitud.
- Las pruebas con dobles (`tests/fakes.py`) no son benchmarks de Granite/LanceDB ni del modelo.
- No se probó el despliegue en Coolify/VPS ni los tiempos con la CPU del servidor; la latencia medida es la del equipo local más la del proveedor.
- La guía es la única fuente: sin web, inventario de predios, precios ni contactos fuera de ella. Su corte es el 18/09/2026 (complementos al 19/10/2026).
- Con el volumen de consultas de producción habría que medir costo por consulta: 1-5 llamadas al proveedor y, en las 379 consultas registradas, 475-45.581 tokens de entrada (promedio ~6.900).
- Falta la revisión editorial humana de la base y de las respuestas antes de publicar fuera de la prueba local.
