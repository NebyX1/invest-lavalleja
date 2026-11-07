# Validación del agente RAG

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
