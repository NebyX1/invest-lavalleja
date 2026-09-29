# Gianna · Invest Lavalleja

**Versión 1.0.0-rc1 · 28 de septiembre de 2026 · Candidata para validación.**

Backend Python/Flask con administración web, doble factor, gestión editorial de bases de conocimiento, indexación híbrida CPU y chat público. Incluye el corpus convertido de la guía entregada y una isla React para integrar en el portal Astro. No se modificaron repositorios remotos.

**Estado actual:** Gianna usa `deepseek-v4.1-flash` en la pila local de prueba. Un harness distingue conversación, consulta RAG, preguntas externas, burlas, privacidad y pedidos dañinos antes de recuperar documentos. Las respuestas sobre inversión requieren fuentes; la conversación no muestra citas irrelevantes ni rechazos en tercera persona. La pila Docker de prueba humana está aislada y avisa que el contenido no fue revisado. La base operativa permanece sin publicación y no está validada para producción. Se aprobaron 106 pruebas Python, 12 pruebas de navegador de Gianna (escritorio y móvil) y una batería real de 16/16 diálogos; esos resultados no certifican exactitud factual. SMTP real y Coolify remoto no están validados. Consultar `reports/VALIDACION.md` y completar `docs/PUESTA_EN_MARCHA.md` antes de abrirla al público.

## Qué incluye

- Panel en español, responsive, con recursos locales y sin un segundo frontend Node para administrarlo.
- Contraseña Argon2id, TOTP con QR, códigos de recuperación de un solo uso y alternativa de código por correo con SMTP TLS. Sesiones revocables y roles propietario, editor y consulta.
- Cargar JSON canónico, JSONL autocontenido, DOCX, Markdown o TXT. Los documentos desconocidos entran como internos. Conversión en cola persistente, nunca publicación automática.
- Editar texto, fuentes, tema, zonas, fechas, condiciones, audiencia y estado de cada registro. Búsqueda, filtros y aprobación del contenido público.
- Crear versiones vectoriales inmutables, progreso por lotes, caché de embeddings, reintento y cancelación cooperativa. Una base nueva no interrumpe ni reemplaza automáticamente a la publicada.
- Exploración de chunks reales, cantidad de tokens, contenido y metadatos. Mapa PCA 2D interactivo de hasta 1.200 puntos, con etiquetas temáticas: no es un clasificador ni una prueba de calidad.
- Laboratorio de recuperación y chat, evaluación de recuperación con preguntas cargables, publicación con confirmación, retorno a versiones previamente publicadas y borrado protegido de una base con sus versiones.
- Analítica agregada de consultas, latencia, tokens informados por el proveedor, referencias, feedback y temas recuperados. No se inventan montos facturados ni porcentajes de exactitud.
- Chat público de prueba `/chat`; isla React activa en `../src/components/islands/GiannaChat.tsx`; `AgentHarness` controla rutas, respuestas de seguridad y acceso al RAG; contexto corto cifrado de hasta seis intercambios, botón para olvidar y límites de uso. Ambos inicios de sesión exigen CAPTCHA.
- Compose, Dockerfile, scripts de arranque, copia/restauración de SQLite, migraciones y workflow de pruebas. No contiene tokens, contraseñas, embeddings precalculados ni un volumen Qdrant.

## Stack decidido

```text
Portal Astro / isla React
        ↓
Flask + Gunicorn + Jinja + SQLite WAL
        ↓
FastEmbed + multilingual-E5-small ONNX (384 dimensiones, CPU)
        ↓
Qdrant Server: dense + BM25 español + RRF
        ↓
Ollama Cloud API: Authorization Bearer desde OLLAMA_API_KEY
```

Solo dos servicios persistentes de aplicación: `api` y `qdrant`. El trabajo de indexación usa un hilo supervisado dentro del único proceso de la API y una cola SQLite durable. No se agregan Redis, Celery, MariaDB, MinIO, un servidor de embeddings ni un Ollama local. Se usa Qdrant por HTTP/REST con HTTPX, no hace falta `qdrant-client`.

`D:\Ai Projects\chat-onnx-local` se tomó como referencia de separación navegador → API → proveedor y de interacción conversacional. Aquí la interfaz se adapta a una isla React en Astro y la API a RAG con citas; no se trasladó su SPA ni su servidor llama.cpp local.

**Controlador de Gianna.** Primero aplica barreras locales para acusaciones directas sobre personas y pedidos explícitos de daño o ilícitos; las críticas a la asistente pasan a una respuesta conversacional contextual. Para los demás mensajes, el modelo propone una de seis rutas en JSON: `rag`, `chat`, `deescalate`, `allegation`, `refuse` u `out_of_scope`. El servidor valida la propuesta y solo `rag` puede consultar el índice público; una decisión inválida pide reformulación sin buscar. Las preguntas externas también reciben conversación natural, sin plantillas de “fuera del alcance”. Los saludos inequívocos evitan una clasificación. [Ollama Cloud no admite salidas con esquema](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx), por lo que Python valida el JSON. `deepseek-v4.1-flash` se usa con `think: false`, probado contra el proveedor; otros modelos conservan `think: low`. Una respuesta documental sin citas válidas recibe un único intento de reparación con la misma evidencia; nunca se publican citas fabricadas como respaldo. Esto no sustituye pruebas adversariales continuas ni revisión humana de afirmaciones factuales.

**Un proceso de Gunicorn.** No aumentar `workers` ni arrancar réplicas sin rediseñar la cola, los bloqueos de inferencia y los límites. El despliegue de SQLite necesita almacenamiento local persistente, no NFS compartido entre máquinas.

## Arranque local con Docker

Requisitos del equipo destino: Python 3 para generar `.env`, Docker con Compose y acceso a los registros de imágenes, PyPI, Hugging Face y Ollama Cloud.

```bash
python scripts/setup_env.py --local
# Editar .env: poner OLLAMA_API_KEY. El modelo se puede elegir luego en el panel.
docker compose -f compose.yaml -f compose.local.yaml up --build -d
docker compose -f compose.yaml -f compose.local.yaml exec api flask --app wsgi create-admin
```

Abrir `http://localhost:8000/admin/login`. El comando solicita nombre, correo y contraseña sin imprimirla. En el primer ingreso, configurar TOTP y guardar los códigos de recuperación fuera del servidor. No hay usuario ni contraseña por defecto. En Windows está también `run.ps1`.

Si hay SMTP configurado y se quiere el segundo factor por correo como en el Buzón Ciudadano, crear la cuenta con `flask --app wsgi create-admin --mfa email`. Sin SMTP, conservar TOTP; nunca desactivar el segundo factor para suplir la falta de correo.

El panel permite trabajar con documentos antes de configurar Ollama. Para generar respuestas se necesita una clave válida y seleccionar un modelo que exista en el catálogo real. El botón **Cargar catálogo real de Ollama** evita adivinar nombres. La primera indexación descarga la exportación E5; las siguientes reutilizan el volumen de modelos.

### Prueba humana local del chat

La instancia de prueba usa `compose.human-test.yaml`, el puerto **127.0.0.1:8001** y volúmenes SQLite/Qdrant distintos de los operativos. Nunca aplicar este override en Coolify. El modo de prueba rechaza hosts y orígenes no locales y muestra un aviso de guía no revisada en `/gianna/`. En la raíz Astro, `.env.local` debe contener `PUBLIC_GIANNA_API_BASE=http://localhost:8001`; no contiene secretos y está ignorado por Git. Iniciar o reiniciar `npm run dev` para que Astro lo tome.

```powershell
# Desde backend/, con .env local configurado (incluida la clave de Ollama):
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env up -d --build
docker cp knowledge/invest_lavalleja_2026.gianna.json gianna-invest-human-test-api-1:/app/data/invest_lavalleja_2026.gianna.json
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env exec -T api python -m scripts.enable_human_test /app/data/invest_lavalleja_2026.gianna.json
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env restart api
```

Esperar a que `http://127.0.0.1:8001/api/config` indique `available: true` y `test_mode: true`; abrir `http://localhost:4321/gianna/`. El script selecciona **solo** los registros marcados públicos, verifica conteos de SQLite/Qdrant y activa exclusivamente el puntero de la pila aislada. Su marca de aprobación es técnica y **no** sustituye revisión editorial. No copiar su volumen ni su base de datos a producción. Las preguntas y fragmentos recuperados se envían a Ollama Cloud, así que no introducir datos confidenciales. Para detener solo la pila de prueba, usar `docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env stop` (sin `down -v`).

La evaluación adversarial de diálogo se ejecuta **solo** por petición explícita, porque consume tokens de Ollama Cloud y usa la base técnica local: `docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env exec -T api python -m scripts.evaluate_dialogue`. Cubre humor, crítica, propuestas personales, hechos externos, actualidad, actividad sensible, corrección, explotación/coerción, privacidad, inversión con seguimiento e inyección para forzar un beneficio fiscal. El script verifica rutas, ausencia de citas improcedentes y algunos fallos de redacción; no es un juez semántico ni una validación jurídica.

## Primera base de conocimiento

1. Obtener la guía fuente por un canal autorizado, convertirla localmente con `python scripts/convert_guide.py <archivo.docx> --output knowledge` y cargar `knowledge/invest_lavalleja_2026.gianna.json` en **Bases**. El corpus contiene material editorial interno y no se versiona en Git.
2. Abrir el borrador, revisar contenido y fuentes. La conversión contiene 271 registros: 196 públicos y 75 internos. Revisar y aprobar los registros públicos que correspondan.
3. Crear la versión vectorial. Abrir su trabajo para ver progreso y errores. Esperar que finalice antes de probar o publicar.
4. En la versión, revisar chunks, temas y mapa. Cargar `knowledge/pruebas_recuperacion.json` en la evaluación y usar el laboratorio.
5. Seleccionar el modelo generativo en Ajustes y revisar manualmente las respuestas de los 12 casos de `knowledge/pruebas_respuestas_revision_humana.json`.
6. Publicar desde una cuenta propietaria con segundo factor reciente. Esa acción cambia el puntero activo de forma transaccional; los borradores continúan sin afectar el chat.

**Aprobar es una decisión editorial, no una verificación automática de veracidad o vigencia.** La guía conserva su corte del 18/09/2026. Sus normas, contactos y estadísticas no se actualizaron con información externa durante la conversión.

Para importar la guía sin aprobarla desde la consola del contenedor, copiar el JSON a `/app/data` y ejecutar `python -m scripts.load_knowledge /app/data/invest_lavalleja_2026.gianna.json`. La opción `--technical-smoke` indexa el subconjunto público en una **SQLite de prueba separada, nunca publicada** y realiza una consulta real; `--evaluations /app/data/pruebas_recuperacion.json` añade la batería de recuperación. El smoke no sustituye la revisión y publicación desde el panel.

## Configuración

Los secretos permanecen en `.env` local o en las variables de ejecución de Coolify. El panel no puede leer ni modificar sus valores. `SECRET_KEY` y `ENCRYPTION_KEY` son diferentes y deben conservarse. Cambiar la clave de cifrado sin migración vuelve ilegibles los secretos TOTP y el contexto cifrado.

Las variables operativas completas están en `.env.example`. Nombre, saludo, tono, aviso, modelo generativo, parámetros de recuperación, tamaño/solapamiento de chunks, límites y retención se administran desde Ajustes. El modelo E5 y su espacio vectorial no se cambian con un selector genérico que pudiera mezclar vectores incompatibles.

Antes de producción, fijar `E5_REVISION` al commit resuelto que muestra el perfil de indexación. `main` facilita la primera descarga, pero no es una referencia reproducible. La aplicación detecta cambios de huella y falla de forma cerrada en lugar de mezclar modelos.

## Documentación

- `docs/COOLIFY.md`: despliegue, variables, dominio y red privada.
- `docs/MANUAL_ADMIN.md`: operación cotidiana y roles.
- `docs/SEGURIDAD_Y_OPERACION.md`: controles, límites, copias y recuperación.
- `docs/REVISION_DOCUMENTAL.md`: conversión, trazabilidad y límites de la fuente.
- `docs/INVESTIGACION.md`: referencias técnicas primarias y decisiones.
- `docs/PUESTA_EN_MARCHA.md`: comprobaciones reales pendientes.
- `integration/README.md`: contrato de conexión; la implementación activa está en `../src/pages/gianna.astro` y `../src/components/islands/GiannaChat.tsx`.

**GitHub:** `backend/samples/Invest_Lavalleja_2026.gianna.json` y `knowledge/` se excluyen porque contienen material editorial interno. La mención al ZIP anterior se refiere a una entrega separada, no a este repositorio. Para recrear el corpus, obtener la guía fuente por un canal autorizado y seguir el comando local de conversión indicado arriba.
- `reports/VALIDACION.md`: qué se ejecutó y qué no.

## Pruebas en el equipo destino

```bash
python -m venv .venv
# Activar .venv según el sistema operativo.
python -m pip install -r requirements-test.txt
python -m pytest -q
```

El workflow de GitHub prueba Python 3.12 y 3.13 y agrega revisión de dependencias. Está incluido, pero no se ejecutó desde esta entrega. Las dependencias directas están fijadas; falta resolver y congelar el árbol transitivo en el entorno destino después de verificar compatibilidad y vulnerabilidades.

## Límites de alcance

No hay editor de temas visuales sin código, passkeys/WebAuthn, recuperación por correo de contraseñas, OCR/PDF, buscador web autónomo, entrenamiento del LLM, analítica comercial de inversiones ejecutadas ni un sistema de gestión de expedientes. El borrado se realiza por base completa, no mediante un botón independiente para cada versión histórica. La publicación solo usa la colección pública, incluso en el laboratorio; el anexo interno queda disponible a los administradores como material editorial.

Validar que una cita existe no demuestra que respalda una afirmación. El RAG implementa aislamiento, trazabilidad y abstención, no una garantía de corrección jurídica o factual. El contenido enviado a Ollama incluye la consulta y las piezas públicas seleccionadas; no es un servicio completamente local.

## Código y materiales

Implementación original inspirada en el patrón funcional del Buzón Ciudadano; no es una copia de su código ni de su `.env`. La guía aportada conserva su autoría y clasificación. Las licencias de bibliotecas, modelos y cualquier material institucional deben revisarse en el despliegue. `knowledge/` está excluido de Git por precaución, aunque se entrega dentro del ZIP para cargarlo administrativamente.
