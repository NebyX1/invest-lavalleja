# Gianna · Invest Lavalleja

**Versión 1.0.0-rc1 · 28 de septiembre de 2026 · Candidata para validación.**

Backend Python/Flask con administración web, doble factor, gestión editorial de bases de conocimiento, indexación híbrida CPU y chat público. Incluye el corpus convertido de la guía entregada y una isla React para integrar en el portal Astro.

**Agente RAG · 29/10/2026 (rediseño completo).** Gianna ya no usa un planificador de reglas ni un catálogo de rubros escrito a mano. Ahora es un **agente con herramientas** sobre una base de conocimiento híbrida:

- La base se organiza en **fichas autosuficientes** (`better-rag/tools/restructure.py` fusiona los fragmentos sueltos de las tablas en su ficha padre) con una cabecera contextual (título, tema, sección, zonas) que se antepone al embedding y al BM25.
- Cada consulta hace una **búsqueda híbrida inicial** (denso Granite 97M + BM25 español de LanceDB, fusión RRF, 60 ms) y el modelo recibe la evidencia numerada. Si hace falta, **busca de nuevo** (`buscar_en_la_guia`, con filtros blandos de zona y tipo) o **lee una ficha** (`ver_ficha`), hasta 4 pasos.
- Responde en prosa breve con citas `[n]` validadas contra la evidencia realmente recuperada, respeta el nivel de evidencia de cada ficha (dato documentado, hipótesis, ejemplo didáctico) y, si la guía no cubre un rubro, lo dice y aporta lo que sí está documentado (zonas, condiciones, trámites, qué validar) en vez de abstenerse.
- **Robustez del proveedor:** reintentos con espera, modelo alternativo (`OLLAMA_FALLBACK_MODELS`), plazo total de 100 s (Gunicorn corta a los 120 s) y, si Ollama cae, respuesta degradada con las fichas recuperadas en lugar de un error.
- El cross-encoder mMARCO sale del camino de la consulta: en la evaluación con 51 preguntas no mejoró el híbrido y costaba ~5 s por búsqueda en CPU. Sigue disponible para el laboratorio.

Ver [arquitectura](docs/RAG_ENGINE.md), [diseño del agente](docs/AGENT_DESIGN.md) y [validación con resultados reales y límites](reports/VALIDACION.md). Las versiones Bekko/Horizon ya publicadas siguen consultables. El presupuesto artificial de 8.000 tokens por petición se eliminó: el corpus público completo ocupa unas 65.000 tokens y cada respuesta usa entre 4.000 y 15.000.

Perfil por defecto: `deepseek-v4.1-flash:1017` (`think: low`) con `deepseek-v4.1-flash` como alternativa. La evaluación automática no certifica exactitud factual ni vigencia; cualquier respuesta debe contrastarse con sus fuentes. No se publica nada automáticamente.

## Qué incluye

- Panel en español, responsive, con recursos locales y sin un segundo frontend Node para administrarlo.
- Contraseña Argon2id y código de seis dígitos por correo, válido durante diez minutos y de un solo uso, como en Buzón Ciudadano. Sesiones revocables y roles propietario, editor y consulta.
- Cargar JSON canónico, JSONL autocontenido, DOCX, Markdown o TXT. Los documentos desconocidos entran como internos. Conversión en cola persistente, nunca publicación automática.
- Editar texto, fuentes, tema, zonas, fechas, condiciones, audiencia y estado de cada registro. Búsqueda, filtros y aprobación del contenido público.
- Crear versiones vectoriales inmutables, progreso por lotes, caché de embeddings, reintento y cancelación cooperativa. Una base nueva no interrumpe ni reemplaza automáticamente a la publicada.
- Exploración de chunks reales, cantidad de tokens, contenido y metadatos. Mapa PCA 2D interactivo de hasta 1.200 puntos, con etiquetas temáticas: no es un clasificador ni una prueba de calidad.
- Laboratorio de recuperación y chat, evaluación de recuperación con preguntas cargables, publicación con confirmación, retorno a versiones previamente publicadas y borrado protegido de una base con sus versiones.
- Analítica agregada de consultas, latencia, tokens informados por el proveedor, referencias, feedback y temas recuperados. No se inventan montos facturados ni porcentajes de exactitud.
- Chat público de prueba `/chat`; isla React activa en `../src/components/islands/GiannaChat.tsx`; el agente (`services/agent.py`) controla la seguridad determinista, la búsqueda y la redacción con citas; historial cifrado acotado por tamaño, botón para olvidar y límites de uso. Ambos inicios de sesión exigen CAPTCHA.
- Compose, Dockerfile, migraciones MariaDB, importador único desde SQLite y workflow de pruebas. No contiene tokens, contraseñas, embeddings precalculados ni un índice LanceDB precalculado.

## Crear administradores y superadministradores

Desde la carpeta `backend`, con las dependencias y el `.env` de la instalación, se usa la misma sintaxis que en Buzón Ciudadano:

```bash
# Superadministrador
python -m flask create-admin "Nombre completo" "superadmin@example.com" "contraseña-de-al-menos-12-caracteres" true
# Administrador
python -m flask create-admin "Nombre completo" "admin@example.com" "otra-contraseña-de-al-menos-12-caracteres" false
```

Los valores son ejemplos: reemplazarlos antes de ejecutar. `true` corresponde al rol interno `owner` (Propietario en el panel): administra cuentas y configuración, y puede publicar y retirar conocimiento. `false` corresponde a `editor` (Editor en el panel): gestiona documentos, revisión e indexación, pero no administra cuentas ni publica. Si se omite el último argumento, se crea un administrador, igual que en Buzón. Solo se admiten `true` y `false`, sin distinguir mayúsculas; un valor incorrecto detiene el alta.

En la terminal del contenedor de Coolify funciona el mismo comando. Con Compose, anteponer `docker compose exec api` (y los overrides de la instalación cuando correspondan). No se necesitan variables nuevas ni recrear usuarios. Las cuentas existentes conservan sus permisos.

En esta instalación local Docker, si `DATABASE_URL` usa `host.docker.internal`, ejecutar dentro del contenedor, no con Python nativo de Windows. Para la pila local de prueba activa:

```bash
docker compose -f compose.yaml -f compose.human-test.yaml exec api python -m flask create-admin "Nombre completo" "superadmin@example.com" "contraseña-de-al-menos-12-caracteres" true
```

Usar `false` al final para un administrador. Esto utiliza la misma `DATABASE_URL`; no requiere otra conexión ni variables adicionales.

El doble factor por correo es obligatorio para todas las cuentas. Configurar `MAIL_*` antes del alta; el código se envía al correo de cada administrador al iniciar sesión y no requiere opciones adicionales. El comando sin argumentos y las opciones anteriores `--email` y `--name` conservan el alta interactiva de un **superadministrador**, con contraseña oculta. Las contraseñas posicionales pueden quedar en el historial de la terminal; usar el modo interactivo cuando no se quiera incluirlas allí. No hay credenciales por defecto ni se imprime la contraseña en el resultado.

Al desplegar esta versión, la migración cambia las cuentas existentes a segundo factor por correo, conserva sus contraseñas y permisos y revoca las sesiones y los desafíos del autenticador anterior. No hay que recrear cuentas ni cambiar claves del entorno. Para recibir un nuevo código, iniciar sesión nuevamente; los códigos anteriores quedan invalidados.

## Stack decidido

```text
Portal Astro / isla React
        ↓
Flask + Gunicorn + Jinja + MariaDB
        ↓
Granite 97M ONNX cuantizado (CLS/L2, 384 dimensiones, CPU)
        ↓
LanceDB: cosine + BM25 español + RRF (≈60 ms)
        ↓
Agente con herramientas (buscar_en_la_guia / ver_ficha), citas [n] validadas
        ↓
Ollama Cloud API: Authorization Bearer desde OLLAMA_API_KEY
```

Un servicio de API: `api`; MariaDB conserva usuarios, sesiones, analítica, corpus y cola; LanceDB y los modelos permanecen en el volumen privado local. La indexación usa un hilo supervisado dentro del único proceso y una cola durable en MariaDB. No se agregan Redis, Celery, MinIO, un servidor de embeddings ni un Ollama local. Los perfiles de inferencia comparten el control de CPU. LanceDB se ejecuta embebido.

`D:\Ai Projects\chat-onnx-local` se tomó como referencia de separación navegador → API → proveedor y de interacción conversacional. Aquí la interfaz se adapta a una isla React en Astro y la API a RAG con citas; no se trasladó su SPA ni su servidor llama.cpp local.

**Controlador de Gianna.** El servidor mantiene las barreras de seguridad deterministas (`services/safety.py`: acusaciones, insultos y delitos graves se resuelven sin llamar al modelo). El resto de las consultas las resuelve el agente (`services/agent.py`): búsqueda híbrida inicial, hasta cuatro pasos con herramientas, validación de las citas contra la evidencia de esa solicitud y degradación a fichas si el proveedor falla. Las reglas del agente viven en código (`services/prompts.py`); el panel solo edita el tono. Ver [arquitectura](docs/RAG_ENGINE.md).

**Un proceso de Gunicorn.** No aumentar `workers` ni arrancar réplicas sin rediseñar la cola, los bloqueos de inferencia y los límites. La cuenta SQL de la API debe tener acceso solo a los esquemas de Gianna; no usar `root` ni compartir el esquema de Buzón Ciudadano.

## Arranque local con Docker

Requisitos del equipo destino: MariaDB 10.6 o posterior, Python 3 para generar `.env`, Docker con Compose y acceso a los registros de imágenes, PyPI, Hugging Face y Ollama Cloud. Crear una base y un usuario exclusivos para Gianna; la URL existente de `sample-backend` usa el esquema `buzon-ciudadano` y no debe copiarse literalmente ni compartirse.

```bash
python scripts/setup_env.py --local
# Editar .env: definir DATABASE_URL para la base de esta instalación,
# además de OLLAMA_API_KEY. El modelo se puede elegir luego en el panel.
docker compose -f compose.yaml -f compose.local.yaml up --build -d
docker compose -f compose.yaml -f compose.local.yaml exec api flask --app wsgi create-admin
```

Antes de ejecutar una importación antigua, detener la API y usar `scripts/migrate_sqlite_to_mariadb.py`; `DATABASE_URL` debe indicar un destino vacío. Abrir `http://localhost:8000/admin/login`. El comando solicita nombre, correo y contraseña sin imprimirla. Después de resolver el CAPTCHA e ingresar la contraseña, introducir el código enviado al correo de la cuenta. No hay usuario ni contraseña por defecto. En Windows está también `run.ps1`.

Configurar las variables habituales `MAIL_*` para enviar el segundo factor por correo, igual que en Buzón Ciudadano. Si falla el envío, se informa el problema y no se abre una sesión autenticada.

El panel permite trabajar con documentos antes de configurar Ollama. Para generar respuestas se necesita una clave válida y seleccionar un modelo que exista en el catálogo real. El botón **Cargar catálogo real de Ollama** evita adivinar nombres. Antes de indexar, ejecutar `docker compose run --rm api python -m scripts.prepare_models`. Las consultas solo leen los modelos locales verificados.

### Prueba humana local del chat

Esta opción es exclusiva de una instalación de pruebas cuyo `.env` contiene su propia `DATABASE_URL`, dirigida a un esquema MariaDB aislado. No usar la configuración de producción para esta prueba. `compose.human-test.yaml` hereda esa única URL, publica el puerto **127.0.0.1:8001** y crea un volumen LanceDB independiente; el nombre del proyecto Compose no aísla por sí solo la base MariaDB externa. Nunca aplicar este override en Coolify. El modo de prueba rechaza hosts y orígenes no locales y muestra un aviso de guía no revisada en `/gianna/`. En la raíz Astro, `.env.local` debe contener `PUBLIC_GIANNA_API_BASE=http://localhost:8001`; no contiene secretos y está ignorado por Git. Iniciar o reiniciar `npm run dev` para que Astro lo tome.

```powershell
# Desde backend/, con .env local configurado (incluida la clave de Ollama):
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env up -d --build
docker cp knowledge/invest_lavalleja_2026.gianna.json gianna-invest-human-test-api-1:/app/data/invest_lavalleja_2026.gianna.json
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env exec -T api python -m scripts.enable_human_test /app/data/invest_lavalleja_2026.gianna.json
docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env restart api
```

Esperar a que `http://127.0.0.1:8001/api/config` indique `available: true` y `test_mode: true`; abrir `http://localhost:4321/gianna/`. El script selecciona **solo** los registros marcados públicos, verifica conteos de MariaDB/LanceDB y activa exclusivamente el puntero de la pila aislada. Su marca de aprobación es técnica y **no** sustituye revisión editorial. No copiar su esquema ni su volumen a producción. Las preguntas y fragmentos recuperados se envían a Ollama Cloud, así que no introducir datos confidenciales. Para detener solo la pila de prueba, usar `docker compose -f compose.yaml -f compose.human-test.yaml --env-file .env stop` (sin `down -v`).

Herramientas de calidad (se ejecutan con `.venv\Scripts\python.exe` desde `backend/`, o dentro del contenedor):

- `python scripts/ingest_corpus.py CORPUS.gianna.json [--approve-technical] [--activate]`: importa, indexa y opcionalmente publica un corpus. `--approve-technical` es un atajo de pruebas locales, no una revisión editorial.
- `python scripts/evaluate_retrieval.py --modes hybrid fused --verbose`: mide hit@k y MRR contra `evals/retrieval_gold.json` (51 preguntas con fichas esperadas). No llama a Ollama.
- `python scripts/evaluate_answers.py --report informe.md`: corre `evals/dialogues.json` (31 conversaciones) contra el agente real y revisa citas, cifras sin respaldo en la evidencia, códigos internos, longitud y estados. **Consume cuota de Ollama.** El informe se lee a mano: no es un juez semántico.
- `python scripts/chat_cli.py "pregunta 1" "pregunta 2" [--separate] [--trace]`: conversación de prueba sin HTTP ni captcha.
- `python scripts/run_local.py --port 8001 --human-test`: API nativa en Windows (sin Docker) para la prueba humana con `npm run dev`.

## Primera base de conocimiento

1. Obtener la guía fuente por un canal autorizado, convertirla localmente con `python scripts/convert_guide.py <archivo.docx> --output knowledge` y cargar `knowledge/invest_lavalleja_2026.gianna.json` en **Bases**. El JSON de trabajo queda fuera de Git (ver nota de GitHub al final).
2. Abrir el borrador, revisar contenido y fuentes. La conversión contiene 271 registros: 196 públicos y 75 internos. Revisar y aprobar los registros públicos que correspondan.
3. Crear la versión vectorial. Abrir su trabajo para ver progreso y errores. Esperar que finalice antes de probar o publicar.
4. En la versión, revisar chunks, temas y mapa. Cargar `knowledge/pruebas_recuperacion.json` en la evaluación y usar el laboratorio.
5. Seleccionar el modelo generativo en Ajustes y revisar manualmente las respuestas de los 12 casos de `knowledge/pruebas_respuestas_revision_humana.json`.
6. Publicar desde una cuenta propietaria con segundo factor reciente. Esa acción cambia el puntero activo de forma transaccional; los borradores continúan sin afectar el chat.

**Aprobar es una decisión editorial, no una verificación automática de veracidad o vigencia.** La guía conserva su corte del 18/09/2026. Sus normas, contactos y estadísticas no se actualizaron con información externa durante la conversión.

Para importar el corpus sin aprobarlo desde la consola, usar `python scripts/ingest_corpus.py <corpus.gianna.json>` (ver arriba). Para un corpus con fragmentos sueltos, generar antes las fichas con `python better-rag/tools/restructure.py ENTRADA.gianna.json SALIDA.gianna.json`; el JSON recomendado es `better-rag/consolidated/Invest_Lavalleja_2026_10_19_fichas.gianna.json` (257 registros públicos, mediana 1.088 caracteres). El script no sustituye la revisión y publicación desde el panel.

## Configuración

Los secretos permanecen en `.env` local o en las variables de ejecución de Coolify. El panel no puede leer ni modificar sus valores. `SECRET_KEY` y `ENCRYPTION_KEY` son diferentes y deben conservarse. Cambiar la clave de cifrado sin migración vuelve ilegible el contexto cifrado.

La configuración requiere una sola `DATABASE_URL` (MariaDB dedicada) por instalación, `SECRET_KEY`, `ENCRYPTION_KEY`, `CORS_ORIGINS`, los tres campos de Ollama y `MAIL_*`. El mismo nombre se usa en local y en Coolify, con el valor que corresponde a cada instalación. No necesita variables adicionales de base de datos, Qdrant, E5, CPU, tamaño de archivos, workers ni rutas de datos. `gianna/config_profiles.py` separa desarrollo, producción y pruebas; `gianna/config.py` centraliza los valores técnicos. El volumen `/app/data` conserva LanceDB, modelos, cargas y exports, no la base SQL.

Para simplificar una instalación existente, ejecutar `python -m scripts.simplify_env` para verificar y luego `python -m scripts.simplify_env --apply` para aplicar. El script comprueba equivalencia, conserva las claves, el modelo y el correo, y deja un respaldo `.env.before-simplify-*` excluido de Git y Docker. Si encuentra opciones personalizadas que no puede retirar sin cambios, se detiene sin sobrescribir. Los nombres antiguos siguen siendo compatibles durante la transición; no deben mezclarse con los nuevos (los nuevos tienen prioridad).

En producción, `CORS_ORIGINS` debe incluir los orígenes HTTPS exactos del portal **y de la API** si usa un dominio separado. De esa lista se deriva la validación de hosts, sin comodines. El perfil de producción conserva cookies seguras, SameSite estricto, HTTPS y un único proxy de Coolify; la API no debe tener un puerto publicado directamente a Internet.

Nombre, saludo, tono, aviso, modelo generativo, parámetros de recuperación, tamaño/solapamiento de chunks, límites y retención se administran desde Ajustes. `OLLAMA_MODEL` inicia el valor de instalaciones nuevas; no sobrescribe el modelo ya elegido en el panel. Los modelos de embedding/reranker y su espacio vectorial no se cambian con un selector genérico que pudiera mezclar vectores incompatibles.

Las revisiones y artefactos están fijados en `gianna/services/neural.py`; el preparador verifica SHA-256. La aplicación detecta cambios de huella y exige una versión nueva.

## Documentación

- `docs/COOLIFY.md`: despliegue, variables, dominio y red privada.
- `docs/MANUAL_ADMIN.md`: operación cotidiana y roles.
- `docs/SEGURIDAD_Y_OPERACION.md`: controles, límites, copias y recuperación.
- `docs/REVISION_DOCUMENTAL.md`: conversión, trazabilidad y límites de la fuente.
- `docs/INVESTIGACION.md`: referencias técnicas primarias y decisiones.
- `docs/PUESTA_EN_MARCHA.md`: comprobaciones reales pendientes.
- `integration/README.md`: contrato de conexión; la implementación activa está en `../src/pages/gianna.astro` y `../src/components/islands/GiannaChat.tsx`.

**GitHub:** el repositorio es público. `backend/samples/Invest_Lavalleja_2026.gianna.json`, `knowledge/` y el JSON de trabajo de la raíz de `better-rag/` quedan fuera de Git. El documento sectorial (`better-rag/Conocimiento_Sectorial_Lavalleja_2026_10_19.docx`) y su versión consolidada (`better-rag/consolidated/`) se publicaron por decisión del responsable del proyecto; antes de cualquier nueva subida conviene revisar la clasificación del material. La mención al ZIP anterior se refiere a una entrega separada, no a este repositorio. Para recrear el corpus de trabajo, obtener la guía fuente por un canal autorizado y seguir el comando local de conversión indicado arriba.
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
