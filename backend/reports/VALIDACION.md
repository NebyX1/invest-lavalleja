# Informe de validación de la entrega

## Diagnóstico de inicialización Bekko/Horizon en Coolify · 21/10/2026

Los logs de producción suministrados muestran dos fallos distintos: un intento inicial de vectorización no encontró `/app/data/models/bekko/<revisión>/manifest.json`; más tarde Gunicorn recibió `SIGSEGV` y levantó un worker nuevo aproximadamente cada dos minutos. El export no incluye un stack nativo ni la última operación de la biblioteca, así que no permite atribuir el `SIGSEGV` a OpenVINO u ONNX Runtime.

Se agregó progreso por etapa al trabajo y registro del servidor (verificación de hashes, tokenizadores, sesión ONNX de Horizon y compilación OpenVINO de Bekko). `scripts.prepare_models` ahora ejecuta una prueba local de embedding y reranking tras descargar/verificar los pesos; `scripts.check_model_runtime` repite solo esa prueba en el contenedor configurado, sin red ni cambios de base. Esto evita confundir la descarga íntegra de archivos con una inicialización/inferencia comprobada.

Verificación local:

- Suite Python: **295 aprobadas, 15 omitidas, una advertencia de deprecación de PydanticGraph**. Las omitidas corresponden a tres casos sin paquete documental privado y doce pruebas MariaDB optativas ejecutadas previamente en la validación de importación.
- En contenedor Linux local `linux/amd64`, con las dependencias fijadas (`OpenVINO 2026.4.1`, `ONNX Runtime 1.31.0`, `tokenizers 0.23.3`), los artefactos locales de Bekko/Horizon y límites Docker de 2 CPU/2 GiB, `scripts.check_model_runtime` llegó por todas las etapas y completó embedding de 384 dimensiones y reranking en aproximadamente 30 segundos.
- La misma carga con ejecución concurrente en hilo también pasó. Esto no reproduce el `SIGSEGV` del VPS; el problema de producción no se declara resuelto hasta ejecutar la nueva comprobación en el contenedor api de Coolify y revisar su resultado. No se reinició ni modificó el servicio remoto.

## Importación en MariaDB estricta y valores por defecto · 21/10/2026

Se reprodujo el fallo de conversión/importación con la guía local de **271 registros y 50 fuentes** en una MariaDB 11.4 nueva con `STRICT_TRANS_TABLES`: `IntegrityError: Field 'description' doesn't have a default value`. La migración MariaDB 001 había omitido nueve valores por defecto existentes en el esquema original. El importador dependía de `bases.description`; la preparación de versiones dependía también de `versions.report_json`. Los datos que ya se habían migrado a la instalación local no ejercitaban una importación nueva desde ese esquema.

La nueva migración **003** restaura los nueve valores de bases, versiones, auditoría y consultas. Se aplica en el arranque, tanto desde cero como sobre el esquema 002, mediante cambios de defaults: no reescribe registros, no relaja SQL estricto ni las restricciones y no modifica claves, cuentas, sesiones, corpus o publicación. No se añadieron variables de entorno ni se alteraron los modelos RAG. No se editaron los archivos documentales privados.

Verificación ejecutada:

- Antes de la corrección, las ocho regresiones iniciales contra MariaDB real fallaron por la misma ausencia de `description`, incluidas las dos cargas HTTP autenticadas de la guía privada sobre esquema nuevo y actualizado.
- Después de la corrección: **12 pruebas de integración aprobadas**, mediante `python -m pytest tests/test_mariadb_import.py --mariadb-docker -q`. Comprueban defaults, importación/exportación íntegra, preparación de versiones con solo contenido público aprobado, recuperación sin duplicados, reintento del mismo trabajo fallido sin cargar otra vez el archivo, rollback sin filas parciales y conservación exacta de cuentas, sesiones, bases, fuentes, versiones, auditoría y puntero activo al repetir la migración. Docker efímero exclusivo, SQL estricto y credenciales de prueba aleatorias, sin usar `.env` ni bases existentes.
- En el checkout institucional: **10 integraciones aprobadas y 2 omitidas** porque allí no está la guía privada. Los cuatro archivos de migración/pruebas coinciden con los verificados en el proyecto fuente. Las dos cargas de la guía privada se comprobaron en el proyecto fuente y en la prueba HTTP con contenedores.
- Suite general: **293 aprobadas, 15 omitidas** (tres por ausencia del paquete documental privado en la ruta histórica de tests y doce integraciones Docker optativas, ejecutadas por separado). Una advertencia previa de deprecación de PydanticGraph. La primera ejecución detectó una aserción inestable anterior: buscaba `QR` en todo el HTML y coincidió con un token aleatorio de seguridad. Se ajustó solo la prueba para revisar el texto visible y la ausencia de imagen/URI de autenticador, sin modificar los tokens ni la seguridad.
- Imagen de comprobación construida sobre las dependencias locales estables, incorporando el código y la migración nuevos. Prueba HTTP con **Gunicorn, MariaDB 11.4 estricta y SMTP Mailpit reales** en contenedores/red desechables: arranque saludable, contraseña y CAPTCHA, correo recibido y segundo factor verificado, carga multipart, trabajo de importación `done` y pantalla de base HTTP 200. Los **271 registros (196 públicos y 75 internos) y las 50 fuentes** se exportaron iguales a los originales. No se aprobó ni publicó contenido ni se llamó a Ollama. No es una reconstrucción limpia de dependencias ni una evaluación de embeddings.

Los recursos desechables de comprobación se retiraron al terminar. No se modificó el servidor de producción ni su base. Tras desplegar en Coolify, verificar esquema >= 3 y usar **Reintentar de forma segura** en el trabajo fallido; el archivo se conserva cuando falla la transacción. La carga seguirá en borrador y requerirá revisión/aprobación antes de indexar y publicar. Esta prueba local no confirma por sí sola el redeploy ni la recuperación del trabajo en producción.

## Errores de login dentro del formulario · 21/10/2026

Se tomó como referencia el manejo de errores del login de Buzón Ciudadano. Los errores de correo/contraseña y CAPTCHA se muestran dentro del mismo formulario, conservando el correo, dejando la contraseña vacía y renovando el CAPTCHA. Las credenciales inválidas y el CAPTCHA inválido/vencido devuelven HTTP 200; una falla de envío del segundo factor se muestra en el formulario con HTTP 503. Se mantienen CSRF, validación de origen, límites de intentos y segundo factor por correo, sin cambios de cuentas, claves ni variables de entorno.

Verificación ejecutada:

- Pruebas de regresión de login y HTTP: **30 aprobadas** en el proyecto fuente y **30 aprobadas** en el checkout institucional. Cubren credenciales inválidas, cuentas inexistentes/inactivas, CAPTCHA ausente/incorrecto/vencido/reutilizado, reintento exitoso hasta el segundo factor, escape de correo y fallo SMTP.
- Chromium contra Gunicorn y MariaDB locales, en escritorio (1440 × 1000) y móvil (390 × 844): errores de CAPTCHA y credenciales dentro del formulario, misma URL, correo conservado, contraseña vacía, sin desbordamiento horizontal ni errores JavaScript. Revisión visual de ambas capturas correcta.
- Imagen de comprobación construida sobre las dependencias de la imagen local estable; API local actualizada y `/health/ready` HTTP 200. No se presenta como reconstrucción limpia de dependencias ni como validación de producción.

La publicación en GitHub no despliega por sí sola el backend: queda pendiente el redeploy en Coolify y la comprobación de acceso en producción.

## Segundo factor institucional por correo · 21/10/2026

Se contrastaron `app/routes/admin/routes.py`, `app/models/user.py`, `app/services/mail_service.py` y la pantalla de verificación del `main` de Buzón Ciudadano, commit `3198d34ed3c15cee47caa33ef73e94dbfd16b6ed`. Gianna utiliza el mismo flujo: contraseña y CAPTCHA, código aleatorio de seis dígitos enviado al correo del administrador, hash Argon2id, diez minutos de vigencia y consumo de un solo uso. Conserva además el límite de seis intentos y las protecciones CSRF, origen, roles y sesiones del backend.

Se retiraron el enrolamiento con autenticador, QR, códigos de recuperación, selector de método y opción `--mfa`. El comando `python -m flask create-admin NOMBRE CORREO CONTRASEÑA true/false`, el alta interactiva, las cuentas del panel y la reconfirmación usan correo automáticamente. Las migraciones MariaDB 002 y SQLite 005 convierten las cuentas anteriores, conservan contraseñas/roles/estado, revocan las sesiones del autenticador y retiran sus claves, códigos y desafíos. El segundo arranque conserva los nuevos códigos de correo pendientes. No se añadieron variables al entorno.

Verificación ejecutada:

- Suite completa del proyecto fuente: **283 aprobadas, 3 omitidas** por ausencia del paquete documental privado; una advertencia de deprecación de PydanticGraph. En el checkout institucional, las **65 pruebas de seguridad, migración, comandos y HTTP** aprobaron. Incluyen vencimiento, formato, reutilización, sustitución de códigos, concurrencia y permisos.
- Imagen Docker de comprobación construida sobre las dependencias de la imagen local estable, con `qrcode` desinstalado y el código actualizado. Una reconstrucción completa desde PyPI se interrumpió durante las descargas; no se presenta como build limpio aprobado.
- MariaDB 11.4 desechable preparada con la imagen anterior: dos cuentas TOTP, sesiones, desafíos y un dato de control. La API nueva migró del esquema 1 al 2 conservando cuentas, hashes de contraseña, permisos y el dato de control. Gunicorn y SMTP Mailpit reales completaron CAPTCHA → contraseña → correo recibido → código → panel para propietario y editor. Se comprobaron rechazo antes del código, errores visibles en el mismo formulario, consumo, permisos y creación por panel y CLI `true/false`.
- Con el servidor SMTP de prueba detenido, el login devolvió **503**, invalidó el desafío y no creó sesión. No se imprimieron códigos ni credenciales. Mailpit fue un buzón local aislado: no se enviaron mensajes a cuentas reales ni se certificó entrega SMTP de producción.
- Instancia local actualizada tras comparar conexión, claves, correo y volumen persistente con la configuración existente. Respaldo previo en `/app/data/exports/pre-email-2fa-20261021-033632.sql`. La comparación exacta antes/después conservó datos de cuentas, 678 registros, 948 chunks, cuatro versiones y el puntero activo; esta instalación local no tenía administradores. Esquema MariaDB 2, `/health/ready` y `/admin/login` HTTP 200. No se modificó el corpus ni el índice LanceDB.

Los contenedores, volumen SQL y red desechables de QA se retiraron al terminar. La corrección se publica en `main` del backend institucional. El despliegue en Coolify y un acceso autenticado con correo real en producción siguen siendo verificaciones diferentes de las pruebas locales anteriores.

## Formularios de acceso y segundo factor: 403 por origen nulo · 21/10/2026

Se reprodujo el rechazo con un formulario HTML nativo en Chromium contra `https://mapi.invest.lavalleja.uy`. La respuesta del servidor contiene `Referrer-Policy: no-referrer`; el navegador envía `Origin: null` y el middleware devuelve 403 antes de comprobar credenciales o códigos. La comprobación HTTP anterior había fijado manualmente el origen y no reproducía ese comportamiento del navegador. Se cambió la cabecera de respuesta a `same-origin`: conserva el origen de los formularios propios y omite las referencias hacia otros sitios. Se mantienen la comparación estricta de origen, CSRF, CSP, cookies seguras, permisos y segundo factor. No se añadieron variables al entorno.

Verificación ejecutada:

- **280 pruebas Python aprobadas y 3 omitidas** por ausencia del paquete documental privado; permanece una advertencia de deprecación de PydanticGraph. Las dos nuevas regresiones completan login y segundo factor TOTP/correo con el esquema HTTPS reenviado por el proxy. Orígenes `null`, del portal y ajenos siguen rechazados; omitir CSRF también se rechaza, sin consumir el código MFA. El correo usa transporte simulado, sin envío SMTP real.
- Reproducción remota con una sesión anónima nueva: un formulario dirigido a `/admin/mfa`, con CSRF válido y sin desafío pendiente, produjo `Origin: null` y HTTP 403. Al sustituir únicamente la cabecera del documento recibido dentro del navegador de prueba por `same-origin`, produjo `Origin: https://mapi.invest.lavalleja.uy` y la redirección esperada al login, HTTP 302. No se modificó el servidor remoto ni se enviaron credenciales o códigos reales.
- Imagen Docker reconstruida y recorrido completo en Chromium contra la imagen corregida y una **MariaDB 11.4 desechable**: contraseña y CAPTCHA, HTTP 302 al segundo factor; enrolamiento TOTP, HTTP 200 con recuperación; acceso al panel, HTTP 200; cero errores de consola. La cuenta de prueba, la base temporal, ambos contenedores y las dos redes de prueba se eliminaron al terminar. No se utilizó la base operativa para crear cuentas.
- API local recreada después de comprobar que `DATABASE_URL`, las claves de sesión/cifrado y el volumen persistente coinciden con el contenedor existente. `/health/ready` y `/admin/login` respondieron HTTP 200; el login local ya devuelve `Referrer-Policy: same-origin`.

La corrección sigue local: no se hizo push ni despliegue en Coolify. El dominio público conserva la cabecera anterior hasta desplegar el backend actualizado. No se solicitaron generaciones a Ollama ni envíos SMTP reales en esta verificación. La prueba local con MariaDB y el contraste anónimo remoto no equivalen a un inicio de sesión autenticado en producción.

## Alta por consola compatible con Buzón Ciudadano · 21/10/2026

Se contrastó `app/commands.py` del repositorio `IntendenciaDeLavalleja/buzon-ciudadano-backend`. Gianna ahora acepta `python -m flask create-admin NOMBRE CORREO CONTRASEÑA true/false`, sin necesitar `--app`, desde la carpeta del backend o la terminal del contenedor. `true` utiliza el rol existente `owner` (superadministrador) y `false`, `editor` (administrador). Omitir el booleano equivale a `false`; otros valores se rechazan. No se migraron roles, no se añadieron variables al `.env` y no se modificó la autenticación. Se mantiene el comando interactivo anterior y su alta de propietario, así como `--mfa email` cuando SMTP está configurado. Los duplicados no sobrescriben cuentas ni elevan permisos; la contraseña se guarda con Argon2id y no se incluye en la salida ni en la auditoría. Una contraseña posicional sí puede quedar en el historial de la terminal; el modo interactivo permite evitarlo.

Verificación ejecutada:

- **278 pruebas Python aprobadas y 3 omitidas** por el paquete documental privado ausente; permanece la advertencia de deprecación de PydanticGraph. Son 24 regresiones nuevas del comando: ambos perfiles, booleano omitido y mayúsculas, validaciones, duplicados, compatibilidad interactiva, TOTP y correo con transporte simulado.
- Las pruebas HTTP completaron contraseña, CAPTCHA y enrolamiento TOTP para cada perfil. Ambos entran al panel; solo el superadministrador accede a usuarios, configuración y auditoría y puede crear otra cuenta. Los controles de permisos y el segundo factor siguen vigentes.
- Imagen real reconstruida y prueba adicional en Docker con **MariaDB 11.4 nueva y desechable**, en una red interna sin puertos publicados. Se ejecutaron subprocessos reales `python -m flask create-admin`, sin `--app`, para los dos perfiles y para el booleano omitido. Se comprobaron hashes, auditoría, duplicados, rechazo de booleanos inválidos y permisos HTTP con CAPTCHA y TOTP. La base y el contenedor de prueba se eliminaron al finalizar; no se usó la base operativa para crear cuentas.
- Contenedor local de Gianna actualizado con su volumen y conexión conservados, estado `healthy`. La ayuda del comando funciona en el contenedor. `/health/live`, `/health/ready`, `/admin/login` y el portal `/gianna/` respondieron HTTP 200. Se conservaron la versión activa `16d7029f120c49aa84b7be74974a89de`, sus 360 fragmentos (948 entre todas las versiones) y el conteo de usuarios operativos, que sigue en cero. No se hicieron llamadas a Ollama ni envíos SMTP reales; no se desplegó en Coolify ni se modificaron repositorios remotos en esta tarea.

Limitación local comprobada: invocar la ayuda con Python nativo de Windows usando el `.env` destinado a Docker falla al conectar con `host.docker.internal`. No se cambió la URL operativa ni se creó otra variable para solventarlo. La ejecución documentada para esta instalación se realiza dentro del contenedor actualizado, donde ese host sí funciona. No se afirma haber validado el comando contra MariaDB desde Python nativo de Windows con esta URL.

## Una única conexión MariaDB · 21/10/2026

Se retiró `DATABASE_URL_HUMAN_TEST` del `.env` local, la plantilla y Compose. Cada instalación usa únicamente `DATABASE_URL`; el archivo canónico tiene **15 campos**. El generador, el simplificador, el aprovisionamiento y el importador SQLite/MariaDB siguen ese contrato. El simplificador solo reconoce el nombre retirado como entrada antigua para eliminarlo; conserva la URL principal salvo reemplazo explícito. El aprovisionamiento crea una única base dedicada. El README principal ahora describe el arranque habitual y la publicación desde el panel; las pruebas humanas son una opción de desarrollo separada.

En este equipo, la única URL conserva exactamente la conexión de la API local que ya estaba funcionando. Se verificó igualdad de todos los demás valores del `.env`, incluidas las claves y credenciales, y se guardó un respaldo local ignorado por Git y Docker. No se migraron, eliminaron ni publicaron datos de MariaDB.

Verificación ejecutada:

- Backend en el entorno virtual Windows: **254 aprobadas, 3 omitidas** por ausencia del paquete documental privado; una advertencia de deprecación de PydanticGraph. Incluye regresiones para retirar la URL secundaria sin cambiar la principal, conservar secretos y aprovisionar una sola base (sin acceso real a un servidor en esa prueba).
- Compose de producción, local y prueba humana: `config --quiet` correcto con el único campo `DATABASE_URL`. El perfil Python de producción también se validó con los 15 campos canónicos.
- Imagen Docker reconstruida y API local recreada con su volumen persistente: contenedor saludable, `/health/live` y `/health/ready` con HTTP 200, `/api/config` con `available: true`. El portal local respondió HTTP 200.
- La versión activa `16d7029f120c49aa84b7be74974a89de` mantiene **360 fragmentos en MariaDB y 360 vectores en LanceDB**, idénticos antes y después de recrear la API.

No se solicitaron generaciones a Ollama ni se desplegó en Coolify durante esta verificación. Esta validación de configuración y arranque local no certifica una puesta en producción remota.

## Migración de SQLite a MariaDB · 20/10/2026

Esta es la verificación vigente del backend local y sustituye las referencias anteriores a SQLite como base de ejecución. Se tomó la URL de conexión autorizada de `sample-backend` solo para aprovisionar dos esquemas nuevos y aislados (`gianna_invest` y `gianna_invest_human_test`) y una cuenta de aplicación con privilegios limitados. No se usaron ni alteraron el esquema `buzon-ciudadano` ni sus tablas. Las URLs quedaron en el `.env` local; se conservaron `SECRET_KEY`, `ENCRYPTION_KEY`, el modelo, Ollama y SMTP. El `.env` tiene respaldo local excluido de Git.

La API de prueba se detuvo después de verificar un respaldo en línea de SQLite: `integrity_check=ok`, 22 tablas y 24.748.032 bytes, en `/app/data/backups/gianna-pre-mariadb-20261020.sqlite3`. El importador transfirió y verificó **4.883 filas en 20 tablas** a MariaDB. El archivo SQLite original y su respaldo siguen intactos para recuperación; ninguno se usa en runtime.

Tras levantar la API contra MariaDB: contenedor `healthy`; `/health/live` y `/health/ready` respondieron 200. Los conteos de las 18 tablas persistentes comparadas coinciden con el respaldo. La única sesión de chat que ya estaba vencida fue eliminada por el mantenimiento normal de la aplicación; el arranque creó y completó un trabajo `warmup`. La versión activa conserva **360 chunks y 360 vectores LanceDB**. No se solicitó una generación a Ollama ni se hizo despliegue remoto.

La suite del backend ejecutada sobre la imagen Linux: **246 aprobadas, 3 omitidas**, una advertencia de deprecación de PydanticGraph sin fallos. Compose validó la configuración sin imprimir secretos y `git diff --check` no reporta errores de whitespace. SQLite queda limitado a pruebas unitarias y al importador de transición; desarrollo y producción exigen `DATABASE_URL` MariaDB.

## Configuración simplificada a partir de `sample-backend` · 20/10/2026

Antecedente inmediatamente anterior a MariaDB: se adoptó la organización de Flask del proyecto de referencia, no sus credenciales ni servicios ajenos a Gianna. En esa etapa el `.env` pasó de 30 a **14 campos**; la migración descrita arriba añadió inicialmente dos URLs de base dedicadas y lo llevó a 16 variables. Se eliminaron las opciones obsoletas de Qdrant/E5 y parámetros operativos que ya tienen valores predeterminados. Los perfiles desarrollo/producción/pruebas viven en `gianna/config_profiles.py`; `gianna/config.py` mantiene compatibilidad con nombres anteriores. El motor RAG y los modelos no cambiaron.

Migración ejecutada con `python -m scripts.simplify_env --apply`: configuración efectiva equivalente; comprobación adicional de igualdad de `SECRET_KEY`, `ENCRYPTION_KEY`, token y modelo de Ollama y contraseña de correo. Respaldo local `.env.before-simplify-20261020T171723582005Z`, excluido de Git y Docker. El migrador rechaza opciones desconocidas, duplicadas o personalizadas que no pueda retirar sin cambios. El generador de instalaciones nuevas sigue negándose a sobrescribir `.env` o rotar claves existentes. `sample-backend/` se excluyó de Git y del contexto de construcción del portal; no se modificó ningún archivo de referencia.

Seguridad conservada: CORS exacto sin comodines, hosts derivados de los orígenes configurados, HTTPS y cookies seguras en producción, CSRF, CSP, CAPTCHA, anti-replay, roles, sesiones y cifrado. El perfil local no confía en encabezados reenviados; producción presupone el único proxy privado de Coolify y ningún puerto público directo. Una nueva prueba detectó un fallo previo al rechazar un Host: la plantilla de error intentaba construir enlaces sin adaptador URL. Se corrigió para devolver 400 sin renderizar esa plantilla, sin desactivar la validación.

Pruebas ejecutadas:

- Backend: **243 aprobadas, 3 omitidas** por ausencia del paquete documental privado; incluye 39 pruebas nuevas de configuración, compatibilidad, migración, generación de claves y seguridad HTTP. Aviso previo de deprecación del bucle asyncio en PydanticGraph, sin fallos. Antes de los cambios faltaba PyArrow en el entorno virtual local; se instalaron PyArrow 26.0.0 y LanceDB 0.40.0, ya declarados en requirements. `pip check`: sin dependencias rotas.
- Navegador de Gianna: **12/12 aprobadas**, escritorio y móvil. Estas pruebas simulan respuestas del proveedor; no certifican calidad de generación ni son un benchmark de los modelos.
- Compose: configuración base, local y de prueba humana validadas mediante `config --quiet`, sin imprimir secretos.
- Astro: revisión de 43 archivos, sin errores, advertencias ni indicaciones.
- Docker: imagen reconstruida desde el Dockerfile existente; API local recreada con las 14 variables, mismo volumen persistente, contenedor healthy y cero reinicios. `pip check` dentro del contenedor: sin dependencias rotas.
- HTTP real tras el reinicio: `/health/live`, `/api/config` y el portal `/gianna/` devuelven 200; chat disponible y modo local identificado. Verificados CORS, cabeceras del panel, autenticación requerida, rechazo CSRF, origen no permitido 403, Host no permitido 400, CAPTCHA y anti-replay, creación/revocación de sesión y validación de mensaje vacío sin llamar al modelo.
- Recuperación real tras el reinicio: Bekko/LanceDB devolvieron 8 resultados públicos; Horizon reordenó 4. Modelo, puntero activo, base, huella, registros y conteos de LanceDB coinciden con el estado anterior. Se descifraron correctamente los 60 registros cifrados existentes (sesiones/TOTP), sin imprimir su contenido. No se reindexó ni se modificó el corpus.
- Frontend unitario: **7 aprobadas y 2 fallidas** por copias antiguas de los banners/mapa en `public/media/`. Esos archivos ya están versionados y no se modificaron en esta tarea; las fallas no corresponden al backend.

Antes del reinicio se creó `/app/data/backups/before-config-refactor-20261020.sqlite3`. La base activa registrada para comparación es `16d7029f120c49aa84b7be74974a89de`: 332 registros públicos, 360 chunks y 360 filas LanceDB, con modelo generativo `deepseek-v4.1-flash:1017`.

No se desplegó en Coolify remoto, no se enviaron correos reales ni se consumieron generaciones pagas. El SMTP local sigue sin servidor configurado, tal como estaba. La disponibilidad local no equivale a aprobación editorial ni validación de producción.

## Gianna como agente con memoria (PydanticAI) · 19/10/2026

**Esta sección sustituye el flujo descrito en «Respuestas coherentes y orientadas al inversor»** (planificador de búsqueda + generación de un solo paso), que se probó y resultó insuficiente.

Problema observado (prueba humana, captura del responsable): ante «Quiero poner un boliche», Gianna respondió con un orden de trámites («primero conviene definir quién será el titular…», RUNAEV, habilitaciones). Causa: la intención se decidía con regex (`poner` ∈ `REQUIREMENT_WORDS` → *requisitos*), el plan arrastraba facetas de permisos que se enviaban al modelo, y el prompt no definía a quién se le habla, por lo que trataba a la persona como alguien que debía ser guiado en pasos básicos. Tampoco había memoria del hilo más allá de campos derivados por regex.

Referencia estudiada: `giana-lex` (agentes PydanticAI sobre el endpoint compatible de Ollama, el modelo interpreta *todos* los turnos con salida estructurada validada, historial nativo, memoria de estado y una lectura adicional acotada). Se adoptó el patrón; no se copió su dominio.

Cambios:

- **`services/agents.py` (nuevo)**: intérprete de turnos (`TurnPlan`: acto, tipo de pedido, necesidad, consulta autosuficiente, búsquedas y **memoria actualizada**), agente de respuesta con `output_validator` y reintento nativo, y agente de conversación. Memoria `InvestorMemory` (proyecto, intereses, opciones presentadas, preferencias; seis ítems por lista) persistida cifrada en la sesión. Dependencia `pydantic-ai-slim[openai]==2.57.0` y transporte `Ollama.agent_model` (endpoint `/v1`, transporte por solicitud).
- **Intención por el modelo**: el harness solo conserva las puertas de seguridad deterministas. Si el modelo falla, el plan determinista anterior actúa de respaldo y conserva la memoria.
- **Trato y tarea**: `ANSWER_SYSTEM` define a un inversor adulto y informado (sin «primero definí…», sin pasos que no pidió) y `policy_for` pide, para «dónde», qué experiencia, público o ventaja ofrece cada zona; los trámites solo si los pide o si cambian la elección. Se retiraron las facetas de permisos del contexto del modelo y las etiquetas en inglés del corpus.
- **Recuperación**: se fusionan con RRF la afinidad entre búsquedas y el reranker (el reranker pequeño en CPU hundió los perfiles de zona que todas las búsquedas habían encontrado: puntaje 0,04 frente a 0,28 de «Horticultura»); el reranker usa las palabras de la persona y su necesidad; para pedidos de ubicación se recuperan por tipo de registro y se reservan hasta tres perfiles de zona en el contexto. Segunda lectura (`buscar_en_la_base`) solo para datos puntuales: en pedidos amplios añadía ruido y latencia (trajo una ficha de demografía para un boliche). Las fuentes declaradas que no comparten título ni contenido con la respuesta se depuran.

Verificación real (DeepSeek `deepseek-v4.1-flash:1017`, API local con CAPTCHA y sesión):

- Antes de esta revisión: «Quiero poner un boliche» → trámites. Primera versión del agente → ya describía zonas, pero con evidencia ruidosa (cine, horticultura) y sin los perfiles de zona.
- Después: «Quiero poner un boliche» abre con «Hay varias zonas…» y describe Minas, Solís–Aguas Blancas, Arequita y las localidades de los Días de los Pueblos con el perfil documentado de cada una; en tres corridas seguidas se mantuvieron los perfiles de zona. Seguimiento de la misma conversación: «Me quedo con Villa Serrana, ¿qué experiencias puedo ofrecer?» retoma el boliche, ofrece experiencias, público y la restricción lumínica del plan local; «¿Y qué permisos necesitaría para eso?» se responde para esa actividad y esa zona; «Gracias» recibe una cortesía.
- Regresión: eólico (antecedente Minas I, EIAUPOT, prohibición en Arequita, sin atribuir aptitud a localidades que la ficha excluye), turismo, madera, fiscal, requisitos de un restaurante, clima, criptominería y premisa falsa de exoneración del 100% se respondieron con el contrato esperado.
- Intérprete: entre 1,7 y 2,7 s por turno. Consulta completa: 16–28 s (reranker en CPU 8–10 s, intérprete 2–3 s, respuesta 6–10 s).
- Pruebas: backend **204 pasaron y 3 se omitieron** (paquete privado ausente), sin llamadas pagas (`FunctionModel` sobre el transporte de prueba); frontend `astro check`, ESLint, Vitest y 12/12 e2e de Gianna en verde.

Limitaciones: el modelo no responde idéntico en cada ejecución y algunas respuestas incluyen razonamientos de encaje débiles cuando la base no trata la actividad (p. ej. público de «Días de los Pueblos» para un boliche); no se agregó un umbral de relevancia por no estar calibrado el reranker. La latencia total sigue dominada por el reranker. Esta evidencia usa una base de pruebas locales y no sustituye la revisión editorial ni las 62 preguntas y 12 situaciones humanas del checklist.

## Respuestas coherentes y orientadas al inversor · 19/10/2026

**Esta sección sustituye parcialmente «Rol institucional informativo»**, que había fijado un rol sin orientación a partir de una devolución de la Dirección de Desarrollo Económico. Por pedido del responsable del proyecto, tras una prueba de uso, Gianna vuelve a orientar al inversor **con lo que respalda la base de conocimiento**, sin inventar y sin asesoramiento definitivo. Conviene confirmar este cambio de criterio con la Dirección antes de una publicación.

Problema observado (prueba humana local): respuestas entrecortadas, con «según la guía» y «hipótesis 1/2», y negativas del tipo «No encontré…» ante «¿Dónde puedo instalar un parque eólico?» o «¿Dónde abrir un bar o boliche?» aunque la recuperación había traído las fuentes correctas (antecedente de 42 MW, autorización departamental y EIAUPOT, prohibición en el Parque Nacional Arequita). Causas: reglas de prompt y validadores que prohibían orientar y forzaban dos o tres frases, una política «solo lugares vinculados expresamente a la actividad», citas `[C#]` obligatorias en cada párrafo, vocabulario copiado del corpus y consultas de dominio sin interpretación previa. Contraste con el proyecto de referencia `giana-turismo`: contrato de salida único, fuentes mostradas aparte, el modelo decide si la evidencia alcanza y sin validadores regex que reescriban o rechacen respuestas.

Cambios (sin tocar modelo, corpus, vectores ni reglas de seguridad previas a la generación):

- Nuevo prompt y contrato (`ESTADO` + `FUENTES`), voz «mi base de conocimiento», sin «hipótesis», ventaja comparada por zona, apertura con lo útil y salvedades en una frase. Saneador de vocabulario como última salvaguarda.
- Planificador de búsqueda con el modelo y respaldo determinista; hasta cuatro búsquedas; los últimos cuatro turnos como contexto.
- «Boliche» ya no obliga a una pregunta de aclaración; se responde para bar, pub o local bailable.
- Se retiraron los validadores de «voz asesora», longitud, pregunta final y cita por línea, y el encabezado automático por actividad. Se conserva el guard de atribución para nombres propios específicos.
- Regla explícita contra la extrapolación: una referencia regional que la fuente declara no aplicable a ciertas localidades no se presenta como opción para ellas. Fue necesario añadirla: una primera versión permisiva listó Mariscala, Pirarajá y Zapicán como aptas para eólica contra lo que dice la ficha.
- Interfaz y persona: «base de conocimiento» en lugar de «guía»; las fuentes se listan sin etiquetas `[C#]`. La persona anterior se migra por coincidencia exacta.

Verificación real (DeepSeek `deepseek-v4.1-flash:1017`, API local con CAPTCHA, base `e03fdbd8…`):

- Antes: eólico → `insufficient_evidence` con títulos crudos; bar/boliche → `insufficient_evidence`; turismo y madera → respuestas con «La guía…» e «hipótesis».
- Después: eólico y bar/boliche → `answered`, abren con las opciones («Hay varias zonas…»), comparan el perfil documentado de cada zona, recuerdan las condiciones que cambian la decisión y aclaran en una frase que no hay inventario de predios; sin «guía» ni «hipótesis». Seguimiento «¿Y qué permisos necesito para el que sería en Villa Serrana?» resuelto con el contexto. Cripto y clima → «No encontré…» sin especular. La premisa falsa «exoneración del 100% sin fuentes» se corrige con la base.
- Latencia de 15–25 s por consulta; el reranker Horizon en CPU aporta 7–11 s (sin cambios) y el planificador unos 2–3 s. Un caso aislado tardó 55 s por lentitud del proveedor y otro devolvió 503 transitorio del proveedor.
- Pruebas finales: backend **192 pasaron y 3 se omitieron** (paquete privado ausente), ejecutadas en contenedor con la imagen del proyecto. Frontend: `astro check` 0 errores, ESLint limpio, Vitest 9/9 y 12/12 e2e de Gianna en verde.

Limitaciones: la calidad sigue dependiendo del modelo y de una recuperación acotada; las respuestas varían entre ejecuciones y una redacción fluida no certifica cada afirmación. Esta evidencia usa una base de pruebas locales y no sustituye la revisión editorial ni las 62 preguntas y 12 situaciones humanas del checklist.

## Activación de la base consolidada por solicitud del usuario · 19/10/2026

La solicitud explícita «Debes reemplazar la base de conocimiento actual con la nueva» autorizó importar, aprobar la selección pública y publicar el consolidado previamente revisado. Se usaron los servicios de dominio existentes, sin modificar controles HTTP, prompts, routing, modelos ni configuración persistida. La operación quedó auditada como administración local, sin atribuirla a una cuenta humana ni presentar la aprobación como recertificación factual.

**Nueva versión activa:** `16d7029f120c49aa84b7be74974a89de`, base `0f9f89d09b9c477eaf0586b9247ae7ac`. Contiene **332 registros públicos, 360 fragmentos y máximo 419 tokens Bekko**; los **75 internos se conservaron en el borrador administrativo, sin aprobarse ni entrar al snapshot/índice público**. Se comprobó igualdad exacta entre el snapshot y los registros públicos importados, cobertura de todos ellos y coincidencia de conteos SQLite/LanceDB. DeepSeek continúa en `deepseek-v4.1-flash:1017`.

Antes de importar se creó un respaldo SQLite consistente, con `integrity_check=ok`, en el volumen persistente: `/app/data/backups/knowledge-20261019-f6405e1db9cc-before.sqlite3`. Es confidencial y no se copió al repositorio. La versión anterior `e03fdbd8a46a4c9aab37e2b44c77b463`, su base y su colección LanceDB permanecen para reversión; no se eliminó ninguna. El trabajador indexó la nueva colección antes del cambio del puntero activo.

**Verificación posterior sobre el índice publicado: 5/5 consultas**, con Bekko/OpenVINO, Horizon/ONNX y LanceDB reales y el perfil configurado en el servidor: parques eólicos, autoconsumo, olivicultura, vertidos y mantenimiento industrial. Los contextos contienen fichas esperadas y exclusivamente registros públicos de la nueva versión. API `/health/live`, `/health/ready` y página `/gianna/`: HTTP 200; `/api/config`: `available=true`, `enabled=true`. No hubo llamadas al proveedor ni generación de respuestas en esta comprobación; no es una certificación de calidad conversacional o exhaustividad factual.

[Registro local de publicación, validación y reversión](../../better-rag/consolidated/publicacion.json). El [manifiesto](../../better-rag/consolidated/manifest.json) y el [informe](../../better-rag/consolidated/Informe_consolidacion.html) reflejan ahora la publicación efectiva. Los resultados y afirmaciones de «base sin modificar» de la sección siguiente corresponden a la etapa anterior de consolidación aislada, no al estado actual del portal.

## Consolidación documental para nueva ingestión · 19/10/2026

Se creó el paquete local `better-rag/consolidated/` a partir del JSON y el Word de `better-rag`, sin modificar los originales, el flujo del agente, las credenciales ni la base del portal. El contrato se contrastó con `gianna/corpus.py`, `services/knowledge.py` y el fragmentador real. El archivo principal usa `gianna.corpus.v1`: **407 registros, 332 públicos candidatos a revisión, 75 internos y 172 fuentes**. Conserva exactamente los 271 registros y las 50 fuentes originales. Las 128 fichas del Word se consolidaron en 127 —dos describían el mismo evento de ecopuntos— y se añadieron nueve unidades de contexto territorial. Las 127 entradas bibliográficas nuevas se redujeron a 122 URLs únicas conservando alias y localizadores. El diagnóstico y la metodología del Word permanecen en el archivo administrativo de trazabilidad, no como instrucciones del agente.

**Pruebas:** 10/10 regresiones de conversión; 21/21 comprobaciones de esquema, importación/exportación SQLite, preservación y bloqueo de indexación sin aprobación. En almacenamiento temporal con Bekko/OpenVINO, Horizon/ONNX y LanceDB reales: **390/390 comprobaciones**, 360 fragmentos, máximo **419 tokens** frente al límite 420, todos los 332 registros públicos representados y cero internos indexados. Las **13/13 consultas** recuperaron alguna ficha pertinente esperada en el contexto: parques eólicos, restricciones de Arequita, autoconsumo, biogás, olivos, vid, saneamiento serrano, residencias, audiovisual, vertidos, ecopuntos, mantenimiento y poscosecha. No se llamaron proveedores ni se generaron respuestas: estos resultados no certifican calidad conversacional, exhaustividad ni exactitud factual de toda la base.

La versión temporal no se activó. La lectura de la base de servicio antes y después mantuvo `e03fdbd8a46a4c9aab37e2b44c77b463`. El paquete contiene material interno y quedó fuera de Git y de `public/`. Resultados reproducibles y límites: [informe local](../../better-rag/consolidated/Informe_consolidacion.html), [validación del importador](../../better-rag/consolidated/validacion-importador.json), [pruebas nativas](../../better-rag/consolidated/validacion-nativa.json) y [manifiesto](../../better-rag/consolidated/manifest.json). Los scripts y las regresiones están en `better-rag/tools/`.

Se contrastaron puntualmente fuentes primarias de IMPO y MIEM; no se recertificó toda la bibliografía. Se mantuvieron fechas históricas, hipótesis, condiciones y audiencias. El informe señala revisiones temporales y una posible discrepancia entre título/año y URL en la referencia ACAU. La importación y publicación efectiva quedan pendientes de revisión editorial y autorización, no se simularon como realizadas.

## Retirada de atajos temáticos y recuperación general · 19/10/2026

**Esta sección sustituye las conclusiones de ausencia basadas en los filtros temáticos anteriores.** La implementación anterior sí buscaba, pero luego descartaba candidatos por palabras de una lista y reemplazaba la respuesta con una negativa armada por tema. Las pruebas previas que confirmaban esas negativas verificaban ese comportamiento restringido, no la capacidad general del RAG. No debieron presentarse como prueba de que la base carecía de información pertinente.

Se retiraron `matches_information_scope`, la clasificación energética enumerada, los requisitos léxicos de padrón/porcentaje, la proyección que quitaba secciones y las prioridades fijas de fichas/temas. La recuperación usa siempre la pregunta original sobre todo el snapshot público, fusiona candidatos de búsqueda híbrida y los pasa por Horizon. Las referencias explícitas pueden sumar candidatos sin excluir otros. Las consultas nuevas o una ruta desconocida/fuera de alcance no producen una negativa sin búsqueda. No se cambiaron modelos, corpus, vectores, configuración persistida, diseño ni controles de acceso.

El generador lee las fuentes para responder total o parcialmente, o redactar el dato puntual que no encontró. Ese último caso usa un JSON validado con texto generado e IDs opcionales de otros fragmentos recuperados; no usa una respuesta negativa por nombre del tema ni un menú de fichas preferidas. Un fallo de formato/validación es un fallo de respuesta, no una afirmación de que falta conocimiento. Las citas, límites de rol, privacidad y audiencias se conservan; no se exige un número fijo de localidades ni rellenar la respuesta con perfiles.

### Evidencia encontrada y primera corrida real

Por la API real, «Quiero invertir en energías renovables» recuperó y citó información parcial sobre **energía para venta a red** (`s17-01-04`), eficiencia como servicio (`O09`) y ausencia de tarifas publicadas (`s32-04-01`). Se inspeccionaron los tres textos públicos para comprobar esas afirmaciones. Esto no documenta parques disponibles ni convierte eficiencia en generación renovable: sí demuestra por qué la negativa temática previa no era una conclusión válida sobre todo el corpus.

La [primera corrida real](rag-migration/general-rag-initial.json) cumplió **8/9** checks conjuntos. Las cinco consultas públicas recorrieron búsqueda, reranking y generación; agua/efluentes, equipos digitales y eficiencia citaron O10/O08/O09. Micropropagación de orquídeas terminó en falta de información redactada por el modelo. En los pares sintéticos aislados, micropropagación respondió con la fuente y se abstuvo sin ella. El caso energético sintético inicial no cumplió la expectativa positiva: solo describía un proceso físico ficticio, pero preguntaba por invertir en Lavalleja, sin documentar una propuesta de inversión. Se conserva ese resultado; no se cambió el motor para obligarlo a responder afirmativamente. Se precisó la consulta física correspondiente y se añadió un par separado que sí documenta una propuesta de inversión **sintética**, manteniendo la misma exigencia de responder con evidencia y abstenerse sin ella.

### Corrida final con motores reales

[Informe final, respuestas, trazas y hashes](rag-migration/general-rag-final.json): **11/11** checks conjuntos, con el mismo DeepSeek `deepseek-v4.1-flash:1017`, Bekko/OpenVINO, Horizon/ONNX y LanceDB. Se separan cinco consultas por la API pública real de seis ejecuciones en corpus sintéticos temporales:

| Consulta del par sintético | Con fuente pertinente | Sin esa información |
|---|---|---|
| Información sobre generación eléctrica renovable, descrita mediante luz del sol | Responde y cita el documento, conservando que es ficticio | Falta de información redactada para la pregunta |
| Micropropagación, descrita como multiplicación de tejidos in vitro | Responde y cita, sin depender de un tema del antiguo catálogo | Falta de información, sin inventar el procedimiento |
| «Quiero invertir en energías renovables», con una propuesta sintética de capital privado | Describe esa propuesta atribuida al documento y su carácter ficticio; no la presenta como oferta real | Falta de información, después de buscar, reordenar y generar |

En la API pública volvió a responder con información parcial sobre energía para venta a red y límites de la documentación; agua/efluentes, equipos digitales y eficiencia respondieron con sus fuentes. Micropropagación de orquídeas no encontró respaldo pertinente. Todas las trazas acreditan búsqueda global, reranking y generación; no se decidió la disponibilidad por un enum o por el score del reranker. Los hashes de los siete módulos del flujo probado coinciden con los archivos locales.

La sesión pública de evaluación se borró y la versión del portal permaneció `e03fdbd8a46a4c9aab37e2b44c77b463`. No se publicó ningún documento sintético en la base del portal. Los pares aislados comprueban cambio de respuesta con la evidencia, no un benchmark independiente de recuperación: contienen una sola fuente pública y una privada excluida. La prueba sobre el corpus público sí recorre el índice existente. Los scores, citas y checks estructurales no certifican la verdad ni la exhaustividad de todas las respuestas; persisten la variación de redacción y la necesidad de revisión humana.

### Regresiones automatizadas

**174 pruebas Python aprobadas y 3 omitidas** por el paquete documental privado no versionado. Incluyen temas fuera del antiguo catálogo, paráfrasis sin la palabra temática en el documento, fuentes privadas excluidas, entrada efectiva a búsqueda/reranking/generación, respuestas parciales, abstenciones generadas validadas, fallos de validación diferenciados de falta de datos y preservación de memoria, citas y seguridad. Los dobles no se presentan como evaluación de los modelos reales. Los fixtures del router y del formato de abstención se actualizaron al nuevo contrato; las expectativas de negativas fijas y perfiles territoriales obligatorios se sustituyeron por pruebas de búsqueda y evidencia.

## Falta de información específica y otros temas disponibles · 19/10/2026

Se corrigió la respuesta genérica de la captura «Quiero invertir en energías renovables». La abstención identifica el tema reconocido o el detalle faltante y, en un párrafo separado, ofrece hasta tres temas presentes en fichas públicas no vacías de la misma versión que usa la consulta. No se presenta eficiencia energética como respuesta sobre generación renovable ni como recomendación para invertir en otra actividad. Los nombres proceden de títulos de fichas, no del generador; no se ofrecen registros internos, versiones ajenas, títulos inseguros ni las fichas identificadas como el tema fallido. Sin otros temas verificables no se promete un catálogo inexistente.

El cambio se aplica tanto cuando no se recupera evidencia pertinente como cuando el modelo devuelve `[NO_EVIDENCE]`, sin forzar un segundo intento ni repetir detalles inventados. Las respuestas válidas siguen informando con fuentes y sin ese menú. No se cambiaron diseño, modelo, corpus, índices ni configuración persistida. El evaluador distingue el menú separado de una sustitución incorrecta del dato solicitado; sigue rechazando perfiles turísticos usados como supuestas ubicaciones renovables.

**Prueba pública local: 3/3**, con CAPTCHA y sesión reales, versión `e03fdbd8a46a4c9aab37e2b44c77b463` y DeepSeek `deepseek-v4.1-flash:1017`:

- La consulta de la captura reconoce que falta información suficiente sobre inversiones en renovables y ofrece información de eficiencia energética como servicio, hospitalidad serrana con operador y servicios rurales y mantenimiento móvil, sin citas ajenas ni recomendaciones.
- La consulta por padrones disponibles expresa que no hay un listado verificado para ese proyecto; no afirma disponibilidad de terrenos.
- Al elegir información sobre eficiencia energética, responde con la ficha O09 y su cita, sin mantener la negativa anterior ni insertar otro menú.

[Respuestas y comprobaciones completas](rag-migration/missing-information-after.json). Se verificó que las tres fichas ofrecidas existen como públicas en el snapshot; el filtro temático de renovables no encontró registros. Ese filtro es conservador y léxico: no certifica ausencia semántica exhaustiva. La sesión de prueba fue eliminada.

**Regresión final: 172 pruebas Python aprobadas y 3 omitidas** por el paquete documental privado no versionado. Cubre menú máximo de tres temas, ausencia de otras fichas, audiencia interna, snapshot capturado frente a otra publicación, no repetir una ficha fallida, abstención del proveedor sin reparación, casos positivos y evaluación del menú separado. Contenedor `healthy`, configuración pública disponible. No se modificó el frontend en esta corrección ni se presenta como una nueva evaluación visual. No se hizo push ni despliegue público.

## Corrección de identidad: portal de inversiones · 19/10/2026

El ajuste anterior de tono introdujo incorrectamente «desarrollo económico» como identidad de Gianna. Se corrigieron la persona, las instrucciones de conversación, la respuesta de respaldo y los textos de presentación del portal a **información sobre inversiones en Lavalleja**. Se conserva el rol informativo: responder lo pedido, sin asesoramiento ni consejos no solicitados. No se cambiaron diseño, modelo, recuperación, vectores ni corpus.

La compatibilidad reconoce tanto los defaults originales como los informativos incorrectos por coincidencia exacta; no reemplaza personalizaciones. En la configuración local persistida se comprobó que solo cambiaron `persona` y `greeting`, manteniéndose `deepseek-v4.1-flash:1017` y todos los demás ajustes.

Verificación específica de esta corrección:

- **90 pruebas Python aprobadas** (`test_information_role.py`, `test_jobs_and_rag.py`, `test_web.py`), incluidas migración de ambos defaults, conservación de personalizaciones e identidad de inversiones. No se presenta como una nueva ejecución de la suite completa.
- Astro check: cero errores, warnings e hints; lint correcto; build de 32 páginas.
- **4/4 Playwright**, escritorio y móvil: presentación/enlaces sin JavaScript y consulta con API interceptada. Comprueban título, encabezado, bienvenida, placeholder y ausencia de la identidad incorrecta; no son una evaluación del proveedor.
- API local real con CAPTCHA y sesión, usando DeepSeek: «Hola» → **«Hola, ¿en qué puedo ayudarte?»**; «¿Qué podés hacer?» → **«Informo sobre inversiones en Lavalleja: actividades, zonas, requisitos y fuentes publicadas en el portal.»** Ambas respuestas conversacionales fueron breves y sin citas ajenas. La sesión de prueba se borró al terminar.

El contenedor quedó `healthy` y `/api/config` disponible con el saludo corregido. Las conversaciones anteriores del usuario no se borraron ni reescribieron. Esta comprobación verifica identidad y presentación, no certifica la calidad factual del RAG. No se hizo push ni despliegue público.

## Rol institucional informativo · 19/10/2026

Por la devolución de la Dirección de Desarrollo Económico se cambió el contrato: Gianna informa lo pedido y no actúa como asesora ni construye recomendaciones de inversión. **Esta sección sustituye los criterios anteriores que exigían recomendar, proponer una prueba y cerrar con preguntas.** Los informes históricos no se borraron ni se presentan como validación del rol actual.

Antes de cambiarlo se fijó y ejecutó el escenario `information`: información de eficiencia energética → zonas mencionadas → ubicaciones renovables → padrones eólicos disponibles → información de poscosecha en Varela → rentabilidad garantizada. Cumplía **0/6**: las respuestas añadían pasos, métricas y preguntas; la consulta de renovables producía encajes inventados desde perfiles de Minas y Villa Serrana. [Baseline completo](rag-migration/information-before.json).

Cambios aplicados sin cambiar modelo, corpus ni vectores:

- Rol informativo como regla superior a las preferencias editoriales; tono institucional sencillo, sin voz de asesora, interrogatorio sobre recursos ni pregunta de cierre obligatoria. Pedir información no puede convertirse en una recomendación por decisión del clasificador. Se actualizaron el saludo, la persona predeterminada, el encabezado, el texto editorial, el ejemplo y el placeholder del portal. Los defaults anteriores se migran por coincidencia exacta y se preservan las personalizaciones.
- Tema energético acotado en la memoria del servidor para los seguimientos. Eficiencia como servicio no prueba ubicaciones para generación renovable. Los filtros exigen evidencia del tema y, para inventarios, identificadores de sitios; no sustituyen un listado inexistente por requisitos de un predio. La consulta explícita de eficiencia ahora se enruta localmente y no depende de una clasificación generativa.
- Una falta de información devuelve un mensaje breve controlado, sin contactos fabricados ni tareas para la persona. Ya no se reintenta una abstención legítima para forzar una respuesta. Cuando sí existe el dato se responde: se comprobaron las fichas reales O09/O03 y un caso positivo de inventario público **sintético** en las pruebas, no un padrón real.
- La lectura humana de una corrida que ya aprobaba los checks encontró que seguían apareciendo métricas y «entrada y prueba». Para preguntas generales se prioriza la ficha nombrada y se envían al generador sus párrafos descriptivos literales, sin esos apartados no solicitados. Los registros, extractos de citas y límites editoriales no se alteran; las preguntas específicas por condiciones/indicadores conservan el texto completo.

Se conservan la [corrida intermedia](rag-migration/information-intermediate.json), que reveló el fallo de enrutamiento de eficiencia, y la [revisión previa a recortar el contexto](rag-migration/information-before-context-trim.json). No bastó obtener un estado correcto o un score verde para cerrar el trabajo.

### Prueba final por API pública real

**6/6** casos. Tres respuestas documentales con fuentes pertinentes y tres faltas de datos explícitas, sin consejos ni preguntas no solicitadas. Las tres negativas se resolvieron por falta de evidencia pertinente, sin una generación forzada. [Respuestas, trazas y hashes finales](rag-migration/information-after.json).

| Consulta | Palabras antes | Palabras después | Resultado final |
|---|---:|---:|---|
| Información de eficiencia energética | 262 | 81 | Descripción y alcance de O09; sin pasos ni métricas |
| Zonas donde la menciona la guía | 206 | 29 | Minas, Solís y Varela, atribuidos a O09 |
| Ubicaciones de generación renovable | 192 | 15 | No cuenta con ubicaciones documentadas |
| Padrones eólicos disponibles | 132 | 14 | No cuenta con un listado verificado |
| Información de poscosecha en Varela | 250 | 81 | Descripción de O03; sin plan de inversión |
| Rentabilidad garantizada | 223 | 16 | No tiene cifras verificadas ni asegura rendimiento |

Se mantuvieron `deepseek-v4.1-flash:1017`, `think:low`, temperatura 0,1 y 4.096 tokens, Bekko/Horizon/LanceDB y la versión `e03fdbd8a46a4c9aab37e2b44c77b463`. Persona y saludo informativos quedaron aplicados en los ajustes locales persistidos, sin modificar los parámetros del modelo.

### Regresiones y límites

Python/Flask/LanceDB: **166 aprobadas, 3 omitidas** por el paquete privado no versionado. Incluye 15 pruebas específicas del rol, selección descriptiva sin alterar fuentes, inventario positivo sintético, persistencia del tema, ausencia de recomendaciones y no reparar abstenciones. Los fixtures anteriores que daban consejos o exigían un primer paso se adaptaron al nuevo contrato sin retirar controles de fuentes, privacidad o seguridad.

Portal: check sin errores/warnings/hints; lint y 9 pruebas unitarias correctos; build de 32 páginas. Playwright Gianna escritorio/móvil, con API interceptada: **12/12** en la corrida final. Un lote anterior tuvo 11/12 y un timeout móvil de 30 s al abrir las fuentes; el caso aislado pasó y la repetición completa posterior aprobó. No se confunden esos dobles con la prueba real del proveedor.

La API quedó `healthy`, `/api/config` disponible y `/gianna/` respondió HTTP 200. Las sesiones de evaluación se borraron al finalizar. Es una regresión pequeña conocida, con checks léxicos y revisión de texto, no una certificación factual ni una garantía de que nunca haya errores. Los filtros son conservadores y pueden omitir paráfrasis o requerir adaptación con otro corpus. La revisión editorial sigue pendiente; no se hizo push ni despliegue público.

## Recomendaciones enfocadas y próximos pasos · 19/10/2026

Se reprodujo la conversación de las capturas por CAPTCHA/sesión/API/Ollama: «Hola» → «¿Cómo estás?» → «¿Qué me recomendás para invertir en el norte?» → «Profundiza con Varela» → «¿Cómo arranco?». Antes del cambio cumplía **1/5** casos: repetía su presentación, acumulaba opciones y condiciones, y el último seguimiento terminaba en `clarify`. El norte tenía 427 palabras; Varela, 296. Evidencia original: [antes](rag-migration/recommendations-before.json).

El problema no era solo el estilo del generador. El plan clasificaba profundizar como un dato y no conservaba qué opción había ofrecido; la recuperación completaba contexto con otras fichas de la misma zona. La validación podía aprobar citas correctas aunque faltara una recomendación, incluso después de quitar una orientación inicial sin referencia. Se corrigió sin tocar la base documental ni reindexar:

- Separación de `recommend` y `develop`. Las opciones presentadas se recuerdan como IDs/zonas de registros públicos citados, separadas de las preferencias explícitas del usuario. Al retomarlas se validan contra el snapshot activo, nunca contra el texto previo de Gianna.
- Profundizar Varela conserva O03. Su contexto queda en O03, fundamento territorial y prueba comercial; no se agrega O09/O16 por compartir zona. Los cambios explícitos de sector descartan el foco anterior; tampoco heredan la prueba comercial de granos si pasan, por ejemplo, a energía en esa localidad.
- Políticas de lenguaje cotidiano, propuesta condicional, cliente, forma de cobro documentada y prueba comercial. Se eliminan inventarios de métricas, descargos repetidos y preguntas genéricas que solo ofrecen otra lista.
- «¿Cómo arranco?» se trata como acción del turno: comienza por a quién contactar y qué pedir, en vez de presentar otra vez el negocio. Tiene un presupuesto de extensión menor. Se comprueban orientación inicial, foco, extensión y próximo paso, también después de limpiar líneas sin cita.

La primera iteración aprobó los cinco checks originales, pero la lectura humana detectó que el último turno aún repetía la presentación: [intermedio](rag-migration/recommendations-intermediate.json). Se añadió entonces el control de acción inicial y respuesta corta; no se dio por suficiente el estado `answered`.

La corrida final cumplió **5/5** casos, incluyendo estos controles adicionales. Norte: **202 palabras**, dos rutas documentadas con criterios de encaje. Varela: **192 palabras**, una opción de servicio sobre granos, cliente, cobro y prueba. Primer paso: **134 palabras**, contacto con productores/operadores, datos de campaña y una prueba acotada. Las trazas confirman `recommend → develop → develop`, reducción Z5/Z6 → Z5, foco O03 en ambos seguimientos y `next_step:true` solo en el último. Hubo una reescritura por falta de cita inicial en la recomendación del norte; la respuesta final pasó la validación. [Después, respuestas completas, trazas y hashes](rag-migration/recommendations-after.json).

Tras añadir la protección contra pruebas comerciales de otro sector y reconstruir la imagen, se repitió la secuencia completa: **5/5**, con **194 / 190 / 136 palabras** en los tres turnos documentales. Se conserva también esta [segunda corrida final con sus hashes](rag-migration/recommendations-repeat.json), sin sustituir la primera. La respuesta de inicio volvió a pedir contacto y datos concretos, no otra selección de negocios. La variación de redacción y el uso residual de términos contractuales confirman que estos controles no equivalen a una garantía de naturalidad en todos los turnos.

Se mantuvieron **DeepSeek `deepseek-v4.1-flash:1017`, `think:low`, temperatura 0,1 y 4.096 tokens**, Bekko/Horizon/LanceDB y la versión pública `e03fdbd8a46a4c9aab37e2b44c77b463`. No se cambió de modelo para conseguir el resultado.

Regresión completa Python/Flask/LanceDB: **151 aprobadas y 3 omitidas** por el paquete documental privado no versionado. Incluye once pruebas específicas del nuevo flujo, memoria no atribuida como preferencia, snapshot público, cambio de sector, seguimiento después de cortesía y limpieza que pierde la recomendación. La secuencia previa de boliche → lugares → bailable/Minas/permisos pasó **3/3** por la API real, sin reiniciar el rubro ni perder fuentes territoriales, suelo o Bomberos: [regresión territorial](rag-migration/recommendations-locations-regression.json).

Son regresiones conocidas y señales estructurales/léxicas, con lectura humana de las respuestas, no evaluación independiente ni certificación de que cada cita implique cada afirmación. No prueban demanda, rentabilidad, disponibilidad de activos ni habilitación. La revisión editorial sigue pendiente. Se eliminó cada sesión de evaluación al finalizar; no hubo push ni despliegue público.

## Comparación pareada Beam / DeepSeek Flash 1017 · 19/10/2026

Se repitieron los mismos tres turnos por API pública, una sesión nueva por modelo, primero `beam` y después `deepseek-v4.1-flash:1017` (CLI: `deepseek-v4.1-flash:1017-cloud`). Ambos con **`think:low`, temperatura 0,1 y 4.096 tokens de generación**. `/api/tags` confirmó la revisión exacta y `/api/show` confirmó `low` en ambos. El perfil de la revisión 1017 se fijó explícitamente en `low` para esta comparación; el perfil de `deepseek-v4.1-flash` sin revisión sigue con `think:false` y no debe confundirse con este ensayo.

El corpus, versión, prompts, harness, Bekko, Horizon y LanceDB fueron comunes. Los IDs seleccionados y su orden coincidieron en los tres turnos, con la misma versión pública `e03fdbd8a46a4c9aab37e2b44c77b463`. No hubo reindexación ni cambio de política durante la corrida. Registro íntegro, respuestas, trazas acotadas y hashes: [beam-vs-deepseek-1017.json](rag-migration/beam-vs-deepseek-1017.json). El script `scripts.compare_generation_models` permite repetir el ensayo con autorización explícita de llamadas al proveedor.

| Métrica de esta corrida | Beam | DeepSeek Flash 1017 |
|---|---:|---:|
| Respuestas `answered`, con fuentes | 3/3 | 3/3 |
| Turnos que cumplen todos los checks conocidos | 2/3 | 3/3 |
| Tiempo HTTP medio | 15,23 s | 20,78 s |
| Tiempo HTTP mediano | 15,68 s | 22,44 s |
| Generación media, incluidas reescrituras | 5,42 s | 9,93 s |
| Recuperación media, incluido reranking | 9,17 s | 10,16 s |
| Respuestas con reescritura del modelo | 2 | 0 |
| Tokens de salida informados por el proveedor, agregados | 6.756 | 6.179 |

Por turno: Beam **19,11 / 15,68 / 10,91 s**; DeepSeek **24,67 / 15,25 / 22,44 s**. DeepSeek fue un **36,5 % más lento de extremo a extremo** en esta muestra; su generación media fue un 83,1 % mayor. La recuperación también fluctuó, especialmente en el tercer turno de DeepSeek (15,51 s), por lo que el tiempo HTTP no debe atribuirse íntegramente al LLM. La referencia anterior de Beam tenía media 12,79 s: la repetición muestra variabilidad de carga/cachés.

Revisión cualitativa: DeepSeek explicitó el encaje condicional del negocio en Minas, la zona serrana y Solís/Aguas Blancas desde el primer turno, y separó los atributos documentados de esas hipótesis. Beam volvió a entregar una primera orientación genérica después de la validación: se retiraron siete líneas sin cita tras una reescritura. En su segundo turno también hubo reescritura y retirada de un párrafo por atribución. Ambos preservaron el rubro y resolvieron la aclaración bailable/Minas. En DeepSeek no hubo reescritura generativa ni retirada por atribución; sí se retiró una línea sin cita en el segundo turno.

Esto favorece a DeepSeek en completitud/cumplimiento de estos casos, no certifica la veracidad de cada recomendación ni una superioridad general. Los checks incluyen coincidencias léxicas y cobertura estructural; la correspondencia factual requiere revisión humana. Es una única pasada de tres turnos por modelo, en orden fijo, sin control de caché del proveedor ni de toda la carga del host; no hay significación estadística ni cálculo de costo monetario. Los tokens agregados son los que registró el adaptador, no un contador de facturación.

Los once tests de contrato y agregación aprobaron; comprueban además que los fallos no se promedien como respuestas rápidas. El nuevo DeepSeek quedó seleccionado localmente con el perfil ensayado, sin push ni despliegue público. Ambas sesiones de evaluación se borraron al terminar.

## Beam seleccionado para prueba local · 19/10/2026

Por pedido del usuario se abandonó MiniMax y se seleccionó **`beam`** en el `.env` local y en los ajustes persistidos de Gianna; corresponde a `ollama run beam:cloud`. El catálogo real confirmó el modelo. `/api/show` informó niveles `low`, `medium`, `high`, `xhigh`, `max` (predeterminado `max`); la prueba usa explícitamente **`think: low`**. Se mantuvieron Bekko, Horizon, LanceDB y la misma versión pública; no hubo reindexación.

Una prueba inicial con 2.000 tokens respondió el primer turno en 21,1 s, pero el seguimiento falló durante generación (`ollama_unavailable`). Con el límite explícito de **4.096 tokens por llamada**, se repitió el diálogo completo por CAPTCHA/sesión/API/Ollama: **3/3 respuestas `answered`**, con fuentes, actividad conservada y cambio correcto a requisitos al aclarar bailable en Minas. Tiempos HTTP: **14,9 s / 11,4 s / 12,1 s**. Son observaciones con estas configuraciones y cargas, no un benchmark aislado de modelos ni garantía de latencia.

La batería de contenido fue **2/3**, no 3/3: la respuesta inicial describió tres territorios y condiciones, pero no explicitó el encaje del emprendimiento como hipótesis. El seguimiento sí lo hizo. Se conserva ese fallo en [beam-chat.json](rag-migration/beam-chat.json); no se relajó el criterio para presentarlo como aprobado. Las citas y estados correctos no certifican respaldo factual de cada frase. La revisión humana sigue pendiente.

Los nueve contratos del adaptador aprobaron, incluidos `think:low` para Beam, presupuesto acotado y ausencia de filtración de errores del proveedor. La suite completa anterior a este cambio de selección había dado 138 aprobadas y 3 omitidas; no se repitió la batería neuronal porque su motor y datos no cambiaron. Se mejoró el evaluador HTTP para conservar también fallos parciales en el informe sin imprimir cuerpos de error. Una comprobación HTTP adicional «Hola, ¿qué podés hacer?» respondió `conversation`, cero citas y orientación sobre el alcance del asistente. Ambas sesiones finales de evaluación fueron eliminadas al terminar.

## Prueba interrumpida de MiniMax M3.1 Flash · 19/10/2026

Se probó temporalmente el generador `minimax-m3.1-flash`, nombre confirmado en el catálogo real de Ollama Cloud; en terminal corresponde a `minimax-m3.1-flash:cloud`. El usuario pidió abortar esta prueba y sustituirlo por Beam. MiniMax ya no está seleccionado. Bekko, Horizon, LanceDB, el corpus y la versión activa no se modificaron ni reindexaron.

La prueba detectó una incompatibilidad de presupuesto: el límite anterior de 950 tokens no produjo una respuesta RAG utilizable. Una comprobación con 2.000 tokens, por el flujo normal y el snapshot público, obtuvo dos HTTP 200 con `done_reason: length`, 2.000 tokens evaluados, razonamiento separado y **cero caracteres de respuesta**, aun solicitando `think:false`. No se imprimió ni guardó el razonamiento. Metadatos: [minimax-budget-probe.json](rag-migration/minimax-budget-probe.json).

Se habilitó y configuró explícitamente un límite de **8.192 tokens de generación, incluido razonamiento**. Para MiniMax no se recorta ese límite a 400/500 en clasificación/conversación; tampoco se lo eleva silenciosamente en el transporte. Se mantiene el modo predeterminado de razonamiento porque la prueba mostró que apagarlo no eliminó su consumo. El panel identifica el presupuesto total; los demás modelos conservan sus presupuestos breves.

Regresión Python/HTTP: **138 aprobadas, 3 omitidas** por el corpus privado no versionado. Incluye el presupuesto configurable de MiniMax, conservación de límites más bajos, modelos anteriores y las pruebas del harness. Con 8.192 tokens, los dos primeros turnos documentales respondieron `answered` en 149 y 97 segundos; el tercero terminó en `ollama_unavailable`. La prueba completa no aprobó y no se presenta como un chat validado. La comprobación breve `OK` no acreditaba funcionamiento RAG ni calidad factual.

## Continuidad del proyecto y comparación territorial · 19/10/2026

Las capturas posteriores a la migración revelaron un problema no cubierto por su batería: el primer turno sobre un boliche recibía permisos genéricos, y «Ok, pero qué lugares me recomendás para ponerlo?» perdía el rubro y terminaba pidiéndolo nuevamente. Se reprodujo exactamente por API pública: 1/3 turnos cumplió los criterios del nuevo diálogo; el seguimiento devolvió `insufficient_evidence`. Los anteriores 8/8 de recuperación y 2/2 de chat no acreditaban este caso conversacional.

Se corrigieron los siguientes puntos sin cambiar pesos, vectores ni fuentes:

- Memoria cifrada y acotada del proyecto, separada de los últimos 12 mensajes. Conserva actividad, aclaración pendiente y scope aportados por el usuario; sobrevive a cortesías y abstenciones. El sobre acepta sesiones antiguas, se borra con la sesión y no se expone ni acepta como entrada pública. La salida del modelo no agrega localidades o fichas a las preferencias del usuario.
- Intención `locations` separada de `requirements`: primero comparar características territoriales y posibles formatos como hipótesis, después condiciones a verificar. Nombrar Minas para el mismo proyecto no borra la actividad; cambiar de emprendimiento descarta el resumen obsoleto. El router ambiguo recibe el estado estructurado del proyecto.
- Se recuperan y reservan fuentes de territorios distintos y sus condiciones específicas, además de los controles de local, seguridad y negocio. Una respuesta de ubicación no aprueba solo por tener citas: debe mencionar y citar dos territorios, o los solicitados explícitamente.
- Se eliminó el falso positivo que interpretaba «Villa Serrana» como una afirmación de protección territorial. Las afirmaciones reales de protección, SNAP o UNESCO siguen controladas. La revisión manual también detectó que faltaba asegurar el fragmento específico de suelo/paisaje en contexto y se añadió esa reserva.

Verificación lógica y HTTP Flask: **137 aprobadas, 3 omitidas** por la ubicación histórica del corpus privado no versionado. Incluye la secuencia exacta, seguimientos largos, aclaración de formato/localidad, cambio de proyecto, entrada acotada al router, rechazo de ilícitos, estado privado no manipulable, cifrado, recorte del historial y borrado. Estas pruebas con dobles no certifican calidad factual del modelo.

Diálogo real final por CAPTCHA/sesión/API/Ollama: **3/3 turnos**, frente a 1/3 antes de la corrección. Los primeros dos compararon Minas, Solís/Aguas Blancas y Villa Serrana/Penitente, distinguiendo atributos documentados e hipótesis de encaje; citaron también el fragmento específico de suelo/paisaje. El tercero conservó el proyecto, resolvió el formato bailable y pasó a verificaciones en Minas. Las trazas confirman `locations → locations → requirements`, con herencia del contexto en los dos seguimientos. Tiempos HTTP observados: **17,2 s / 14,1 s / 10,1 s**, no una garantía de latencia. Se borró la sesión final de evaluación al terminar. Evidencia: [antes](rag-migration/harness-before.json) y [después](rag-migration/harness-after.json). El portal respondió HTTP 200 y la pila Docker local quedó disponible.

Se repitió además la batería original sobre Bekko/Horizon/LanceDB reales y la misma versión activa: **8/8 consultas, 14/14 grupos de evidencia**, sin llamadas de generación. El caso boliche conserva fuentes de suelo y seguridad, añadiendo ahora tres territorios y la condición de suelo/paisaje. Informe: [recuperación final](rag-migration/harness-retrieval.json). Es cobertura de contexto en casos conocidos, no certificación factual ni evaluación independiente.

Las recomendaciones territoriales son hipótesis desde las características de la guía: no prueban demanda nocturna, rentabilidad, disponibilidad de locales ni habilitación. La continuidad es por sesión anónima, no memoria personal entre sesiones. No se ha desplegado públicamente ni modificado el repositorio remoto.

## Migración a Bekko, Horizon y LanceDB · 19/10/2026

El checkout partió de `30fb0b4`, con E5/FastEmbed, Qdrant y sin reranker. Se sustituyó el motor local por Bekko OpenVINO CPU (`hotchpotch/bekko-embedding-v1-a8m`, revisión `c721113d59a1d91b447450324f51c4b3332c924a`), Horizon ONNX cuantizado CPU (`Horizon-Labs/multilingual-reranker-small`, revisión `c2ec8fb3e499725b168bbed2164bfee095360f77`) y LanceDB 0.40.0 con cosine exacto, BM25 español y fusión RRF. Los modelos se prepararon explícitamente y se verificaron sus tamaños y SHA-256. La inferencia real produjo vectores de 384 dimensiones normalizados; Horizon ordenó correctamente la pareja relevante de la comprobación sintética (0,997 frente a 0,001; no son probabilidades de verdad).

Se creó una nueva versión pública técnica `e03fdbd8a46a4c9aab37e2b44c77b463`: **196 registros públicos / 196 chunks; 75 internos excluidos**. No se reutilizaron vectores E5. Se guardó un backup consistente de SQLite dentro del volumen local antes de migrar. Qdrant quedó detenido, conservando sus datos; la API continúa saludable usando LanceDB embebido. El servicio nuevo arranca con la telemetría de OpenVINO desactivada y sin errores en su log final. El consumo observado al cierre fue aproximadamente 908 MiB sobre el límite configurado de 2 GiB; no representa una medición del VPS.

La planificación conserva el rubro indicado, reconoce la ambigüedad de “boliche” y construye búsquedas para las necesidades de evidencia. Los candidatos del catálogo se someten a Horizon; no llenan el contexto por orden de llegada. Se verifican necesidades específicas de local/padrón, seguridad, alimentos, agua y costos, y se permite una única búsqueda de reparación. El valor inicial de 40 candidatos resultó lento: el valor operativo es 16, configurable y con presupuesto total de 30 segundos para reranking. El prompt permanente se redujo y las políticas de respuesta se eligen por intención. El historial de respuestas de la asistente no se reinyecta como evidencia ni conserva C-IDs de otro turno. Un control adicional identifica atribuciones improcedentes de conceptos concretos a fuentes que no los mencionan; considera texto y condiciones editoriales. Es un control acotado, no un verificador general de implicación semántica.

Se revisaron Patitas Lavalleja y el código de Harness² (`recursion.py`, `spec.py`, `prompts.py`). De este último se adaptaron comparación con la misma tarea, trazas por fase, presupuestos acotados y políticas específicas bajo demanda. No se instaló su framework de agentes de tareas. Investigación y arquitectura: [RAG_ENGINE.md](../docs/RAG_ENGINE.md).

### Evidencia de esta sesión

| Comprobación | Resultado |
|---|---|
| Batería fija de 8 consultas, motor anterior | 2/8 consultas; 6/14 grupos de evidencia (42,9 %) |
| Primera migración, antes de ajustar selección | 4/8 consultas; 10/14 grupos (71,4 %) |
| Pipeline corregido, modelos e índice reales | 8/8 consultas; 14/14 grupos (100 %) |
| Python: lógica, HTTP Flask, índices Lance reales y regresiones | 121 aprobadas, 3 omitidas por ubicación histórica del paquete privado |
| Chat público con CAPTCHA y sesión, consulta de boliche y seguimiento bailable en Minas | 2/2; `answered`, fuentes de suelo y Bomberos presentes, actividad conservada, sin estado privado en JSON |
| Navegador: 12 casos Gianna desktop/móvil | 11 aprobaron en lote; 1 agotó 30 s bajo carga. La repetición aislada aprobó en 9,9 s |
| Dependencias instaladas | `pip check`: sin requisitos rotos |
| Servicio local | `/api/config`: `available/enabled/test_mode=true`; `/gianna/`: HTTP 200; API `healthy` |

Las ocho consultas y sus grupos esperados se fijaron antes de modificar el motor. Cubren boliche, bar, discoteca, norte, cabañas, agua, terreno y permisos. Es una batería pequeña de regresión conocida; los resultados no aíslan el efecto de Bekko, Horizon o el harness ni certifican exactitud factual. Se conservaron los informes antes, intermedio y final en [rag-migration](rag-migration/), junto con el diálogo real y hashes de las fuentes de la corrida de recuperación. El ajuste posterior que confirma actividad/localidad en un encabezado se verificó además mediante la API real.

La base permanece en el entorno humano local de prueba; la revisión editorial y la verificación de vigencia de fuentes continúan pendientes. No se realizó push ni despliegue remoto.

## Corrección de recuperación territorial y respuestas RAG · 29/09/2026

Se preparó este checkout nuevo para pruebas locales: `backend/.env` fue generado con secretos aleatorios, `.env.local` del portal apunta a `http://127.0.0.1:8001`, y la pila aislada `gianna-invest-human-test` quedó levantada con API Flask y Qdrant. Ambos archivos de entorno están ignorados por Git.

Antes de modificar el código se reprodujo el defecto señalado por la auditoría con la consulta «Quiero invertir en el norte de Lavalleja. ¿Qué oportunidades concretas debería explorar?». La API respondía `answered`, pero negaba que hubiera oportunidades concretas y adjuntaba cinco registros generales no pertinentes. El corpus sí contenía perfiles Z5/Z6 y las fichas O03/O12. Este resultado de base quedó sustituido por una nueva versión indexada; no se alteró el texto de los registros fuente.

La corrección incorpora un catálogo determinista de zonas y fichas, contexto enriquecido antes de E5/BM25, filtros de metadatos en Qdrant, planificación acotada, hasta tres búsquedas más una reparación de cobertura, contexto final con registros completos y una guarda que exige oportunidad citada por cada zona solicitada. El router no puede ampliar zonas o fichas propuestas por el modelo, y un seguimiento solo hereda estado de una respuesta documental validada. La API entrega únicamente citas usadas; las trazas conservan IDs, rondas, cobertura y resultados estructurales del validador, sin texto de la pregunta o de la respuesta. Las líneas factuales sin cita que sobrevivan al único intento de reparación se eliminan de forma determinista antes de la validación final.

La interfaz React muestra títulos, párrafos y listas mediante componentes seguros, agrupa las fuentes efectivamente citadas y conserva foco/desplazamiento accesible. La evaluación por lote ahora mide grupos obligatorios sobre el **contexto final** y no solo la aparición de cualquier ID entre candidatos crudos. Cambiar la representación documental fuerza reindexado; una versión con perfil anterior falla cerrada. Gunicorn 26 dejó de intentar crear su socket de control en el `HOME` de solo lectura.

Comprobaciones de esta sesión:

- Docker Compose: configuración válida; API `healthy`, Qdrant activo. `/health/live` respondió `alive`, `/health/ready` respondió `ready`.
- API real con `Origin: http://127.0.0.1:4321`: `/api/config` respondió HTTP 200 y CORS reflejó el origen permitido. Tras activar la prueba humana, el chat informa `enabled: true`, `test_mode: true`, `available: true`.
- Portal: `npm run check` sin errores ni hints tras actualizar el tipo obsoleto del componente de integración; lint correcto; 5 tests unitarios pasaron; build correcto con 32 páginas.
- Playwright: 31 pruebas pasaron y una captura móvil se omitió intencionalmente; incluye los casos de Gianna desktop/móvil con la API interceptada por el test.
- Backend Python 3.12: `107 passed, 3 skipped`. Los tres casos omitidos buscan el paquete documental privado en la ubicación no versionada de la distribución original. El corpus aportado se validó además en la pila real.

El corpus local `backend/docs/Invest_Lavalleja_2026.gianna.json` se cargó primero como borrador sin aprobar. En la pila humana aislada, el activador documentado creó y activó la versión `a0c9653d5e6e4a7989a7008b55e01a35` con E5/BM25 en CPU y Qdrant: 196 registros públicos en 196 chunks; los 75 internos quedaron excluidos. La selección está marcada como prueba técnica, no como aprobación editorial, y no se publicó en producción.

La consulta real del norte, mediante CAPTCHA y sesión pública, terminó en `answered`; citó O03, O12, O02 y los perfiles Z5/Z6. El seguimiento «¿Y qué debería validar antes de avanzar?» heredó únicamente Z5/Z6, terminó en `answered`, tuvo cobertura completa y devolvió solo O03/O12/O02 porque fueron las fuentes usadas. En ambos turnos: cero citas desconocidas, cero líneas finales sin respaldo, cobertura de plan válida y ausencia de `_conversation_state` en la respuesta pública. Esta comprobación confirma el circuito técnico y las invariantes observables, no la exactitud factual exhaustiva de cada afirmación; la revisión humana editorial sigue pendiente. No se modificó Coolify ni se hizo push.

**Actualización local · 29/09/2026. No desplegada en producción.**

## DeepSeek, diálogo natural y evaluación adversarial · 29/09/2026

La captura mostraba falsos rechazos de consultas sobre una actividad sensible y la frase impersonal «fuera del alcance de Gianna». Se seleccionó `deepseek-v4.1-flash` del catálogo real de Ollama en la pila humana local; también se actualizó el selector de modelo de la pila operativa local, que **sigue sin base pública activa**. `.env.example` usa el mismo modelo para instalaciones nuevas. El código no se desplegó a Coolify ni a GitHub.

El harness mantiene barreras locales para acusaciones directas y pedidos inequívocos de daño o fraude. Las burlas, propuestas no coercitivas y preguntas generales ahora reciben respuesta conversacional generada, sin RAG ni plantilla de «fuera del alcance». La ruta documental permite investigar sectores sensibles sin clasificarlos automáticamente como ilegales; si falta evidencia, identifica datos o requisitos por verificar sin dar consejo jurídico. La conversación recuerda el último intercambio para admitir correcciones. Una guarda evita presentar como hecho una conclusión legal específica producida sin documentos. Las respuestas documentales usan citas y tienen un solo intento de reparación si faltan referencias válidas. Se comprobó que DeepSeek Cloud acepta `think: false`, que reduce salidas vacías por agotamiento del presupuesto; otros modelos mantienen `think: low`.

Verificación final: **106/106 pruebas Python**, **12/12 pruebas E2E de Gianna** en Chromium escritorio/móvil (incluyendo el caso sensible), `npm run check` sin errores, `npm run lint` y `npm run build` correctos. La pila Docker de prueba respondió por HTTP al ciclo CAPTCHA → sesión → chiste → borrado con `conversation` y cero citas. El script `scripts/evaluate_dialogue.py`, ejecutado contra **DeepSeek, E5 y Qdrant reales** en el entorno aislado, terminó **16/16** en su corrida final. Cubrió dos chistes, crítica, dos propuestas personales, conocimiento general, clima, dos preguntas de negocio sensible con corrección, explotación, falsificación, privacidad, turismo con seguimiento y una inyección para forzar exoneración sin fuentes. Fallos encontrados en corridas previas (salidas vacías, falso rechazo fiscal, clasificación errónea de propuesta y afirmación jurídica sin respaldo) se corrigieron y se añadieron regresiones.

Los 16/16 verifican rutas y reglas observables, **no** calidad semántica exhaustiva, verdad jurídica/financiera ni que cada cita respalde cada frase. El modelo puede variar entre ejecuciones y todavía debe pasar revisión humana de los 12 casos editoriales, vigencia de fuentes, evaluación de privacidad y costos. La base técnica de prueba sigue sin aprobación editorial; ninguna de estas pruebas autoriza publicación institucional.

## Harness de decisiones y respuestas seguras · 29/09/2026

La captura más reciente mostró otra falla: una acusación sobre una funcionaria recibió el texto genérico de “evidencia insuficiente”. Ahora `AgentHarness` controla el paso previo al RAG. Una barrera local intercepta acusaciones sobre personas, insultos directos y pedidos explícitos de ilícitos; para otros mensajes, `gpt-oss:20b` propone una ruta entre conversación, RAG, desescalada, acusación, rechazo y fuera de alcance. El servidor valida la decisión: solo `rag` abre Qdrant y las rutas sensibles usan respuestas controladas, sin citas ni repetición de acusaciones. Si la salida de clasificación no es JSON válido, no se consulta el índice.

Se detectó y reprodujo un segundo fallo: con `num_predict=160`, el modelo de razonamiento podía consumir todo el presupuesto en `thinking` y devolver `content` vacío. Una petición real mostró `done_reason=length` y 160 tokens evaluados sin respuesta. La petición de clasificación con `think: low` y presupuesto mayor respondió correctamente; se fijó `think: low` y `num_predict=320` para clasificar. La conversación simple también usa razonamiento bajo. No se envía un esquema `format` a Ollama Cloud porque su documentación indica que esa función no está disponible allí; la validación queda en el servidor.

Verificación: **84 pruebas Python** y **12/12 E2E de Gianna** en escritorio y móvil. En la API real, la frase de la captura produjo `allegation` sin citas ni llamada a búsqueda/modelo; un insulto produjo `deescalate`; un pedido de falsificar permisos produjo `refuse`. Una secuencia real de cuatro turnos clasificó clima como `out_of_scope` y conversación general como `conversation` (ambos sin citas), y respondió a un proyecto turístico en Minas más “¿Y los permisos?” como `answered` con cinco citas en cada caso. Chromium móvil mostró la respuesta segura ante la acusación y la desescalada posterior, sin desborde horizontal. La exactitud de las respuestas documentales y la cobertura de casos adversariales no están certificadas; requieren evaluación humana adicional antes de publicar.

## Habilitación para testing humano local · 29/09/2026

### Corrección del flujo conversacional

La primera versión aplicaba recuperación documental y exigencia de citas a **todos** los mensajes. Un simple “Hola, ¿cómo estás?” terminaba en `citation_guard_failed` con fragmentos ajenos a la intención: era un defecto funcional, no una falta de datos. Se separó la conversación social de las consultas a la guía. El modo social usa Ollama con instrucciones de no afirmar datos de inversión sin fuentes, devuelve `status: conversation`, cero citas y respuesta breve; las preguntas del dominio siguen el índice y la guarda de citas. Las preguntas externas sobre hechos no verificados reciben un límite explícito, sin documentos irrelevantes. El hilo cifrado ahora conserva hasta seis intercambios, con el modo de la respuesta para interpretar seguimientos breves.

Regresión anterior: 74 pruebas Python, 10/10 pruebas E2E de Gianna, `npm run check`, `npm run lint`, cinco pruebas unitarias y `npm run build` aprobaron. Chromium contra la API/Ollama reales recorrió en una sesión “Hola, ¿cómo estás?” y “¿Qué podés hacer?” (cero citas), “¿Qué oportunidades de inversión hay en Lavalleja?” y “¿Y qué debo verificar antes de avanzar?” (cinco citas cada una), borró la conversación y comprobó ausencia de desborde a 320, 390, 768 y 1366 px. El clasificador inicial se había eliminado por respuestas vacías; el nuevo harness lo reintroduce con presupuesto y razonamiento ajustados, más validación y barreras locales. La calidad factual de las respuestas RAG sigue pendiente de revisión humana.

La captura del usuario correspondía a `available: false`: la API operativa no tenía una versión activa, por lo que React deshabilitaba la consulta. Se levantó una segunda pila `gianna-invest-human-test` en `127.0.0.1:8001`, con volúmenes SQLite y Qdrant propios y bandera de prueba limitada a hosts/orígenes loopback. El corpus se cargó ahí: **196 registros públicos indexados en 196 chunks, 75 internos excluidos**. Se activó exclusivamente esa versión técnica, marcada como no aprobada editorialmente en la interfaz. La API operativa en `127.0.0.1:8000` continúa con `available: false`.

Verificación real: `/api/config` de prueba respondió `enabled: true`, `available: true`, `test_mode: true`; CAPTCHA → sesión anónima → consulta Ollama devolvió `answered` con cinco citas → borrado respondió `deleted: true`. Chromium recorrió el mismo flujo desde `http://localhost:4321/gianna/`, mostró cinco citas y permitió borrar y preparar una nueva pregunta. Sin desborde horizontal a 320, 390, 768 y 1366 px. La correspondencia factual de citas y la vigencia de la guía siguen requiriendo revisión humana; este resultado solo habilita esa revisión, no autoriza uso público o productivo.

| Misión | Etapa / verificación | Resultado |
| --- | --- | --- |
| Arquitectura y Coolify | Imagen construida; Compose local levantó API + Qdrant, `/health/live` y `/health/ready` sanos; reinicio conservó SQLite | Cumplido localmente; Coolify remoto pendiente |
| Seguridad | CAPTCHA de un uso y 10 min en login y sesiones públicas; CORS y rechazo sin base activa comprobados por HTTP; TOTP y correo soportados | Cumplido en pruebas; SMTP real pendiente |
| Base documental | JSON canónico importado: 271 registros, 50 fuentes, 196 públicos, 75 internos; 0 aprobados en la base operativa | Borrador cargado; revisión editorial pendiente |
| Vectorización y RAG | E5 multilingüe/CPU + BM25 + Qdrant reales: 196 chunks públicos en base técnica aislada; 75 internos excluidos; Ollama respondió con 5 citas | Circuito técnico cumplido; sin publicación |
| Evaluación | 62/62 preguntas de recuperación con al menos un ID esperado en top 8; 84 pruebas Python; Astro `verify` previo: 5 unitarias y 27 de navegador aprobadas, 1 captura omitida; Gianna actual 12/12 E2E | Cumplido para estos tests; revisión factual humana pendiente |
| Dependencias | `cryptography` actualizada a 50.0.1; `pip-audit -r requirements.txt` y `npm audit --omit=dev --audit-level=high` sin vulnerabilidades conocidas en la consulta local | Cumplido localmente; repetir en CI e imagen final |
| Frontend | Página Gianna, enlaces, isla React, CAPTCHA, citas, feedback, borrado y diseño adaptable | Habilitado en prueba humana local aislada; URL pública y aprobación editorial pendientes |

El 62/62 es una prueba de recuperación generada del propio corpus, no una medida independiente de calidad factual ni una certificación del modelo. Ollama respondió a una consulta de control con estado `answered` y cinco citas estructuralmente válidas; la correspondencia semántica de cada cita requiere revisión humana. Una pregunta adversarial sobre “5 puntos = 5 %” mostró que el modelo puede añadir recomendaciones sin cita; se endureció la guarda por párrafo y la repetición terminó en `citation_guard_failed`, mostrando fragmentos en lugar de esa respuesta. Esto reduce exposición a afirmaciones sin respaldo, pero no demuestra exactitud jurídica o financiera. La base del smoke técnico original no tiene puntero activo; la nueva pila aislada para testing humano sí lo tiene, sin alterar la base operativa, que conserva `active_knowledge=NULL` hasta aprobación y publicación explícitas.

Una auditoría local de `requirements.txt` detectó vulnerabilidades conocidas en `cryptography==46.0.4`. Se actualizó a `50.0.1` y una segunda ejecución de `pip-audit -r requirements.txt` informó **ninguna vulnerabilidad conocida** al momento de la consulta. Esto no sustituye un SBOM ni la auditoría de la imagen Linux/transitivas en CI.

Se instaló el backend en un entorno virtual Python 3.13, se fijó `tzdata` solo para Windows, se corrigió la lectura UTF-8 del corpus, y se probó la imagen Linux Python 3.12. El modelo E5 se resolvió en la revisión `614241f622f53c4eeff9890bdc4f31cfecc418b3`, con dimensión 384 y huella de perfil iniciada en `3a30c10f00af`; esa revisión quedó fijada en el `.env` local ignorado por Git. El token de Ollama permanece únicamente en ese archivo/entorno y debe rotarse antes de producción por haber sido compartido en la conversación.

Pendiente para apertura institucional: revisar/aprobar los 196 registros públicos y verificar vigencia de sus 50 fuentes; completar las 12 situaciones de revisión humana, pruebas SMTP reales, auditoría de dependencias en CI, evaluación de privacidad y costos, dominio HTTPS/orígenes de producción, configuración de `PUBLIC_GIANNA_API_BASE` al construir Astro y despliegue Coolify. No hubo push ni despliegue remoto.

Tras endurecer la guarda de citas y la validación de URL pública, se repitieron las 66 pruebas Python y las ocho pruebas de navegador específicas de Gianna; todas aprobaron. La página local `/gianna/` y ambos contenedores respondieron correctamente al cierre de la revisión.

## Historial de la entrega RC inicial (sustituido por la actualización anterior)

**Gianna Invest 1.0.0-rc1 · 28/09/2026. No desplegada.**

### Ejecutado en el entorno inicial

- 48 pruebas de lógica y componentes aprobadas, con resultado final `48 passed, 1 skipped in 1.41s`. La omisión corresponde al módulo HTTP Flask, no a un fallo que se haya ocultado como aprobación.
- Pruebas de MFA incluyen seis vectores RFC 6238, anti-reutilización, límite de intentos, expiración, códigos de recuperación de un uso, sesiones, desactivación y revocación. Los servicios de correo se sustituyen por dobles de prueba.
- Validación y conversión del DOCX real: 271 registros, 196 públicos, 75 internos, 50 fuentes, 16 oportunidades y todos los bloques contabilizados. No se verificó externamente la vigencia de sus afirmaciones.
- Pruebas de snapshots inmutables, revisión editorial, aislamiento público, invalidación de aprobación tras cambios, publicación, retorno y protección del borrado activo.
- Pruebas de contratos Qdrant/Ollama con HTTPX MockTransport. Pruebas de construcción, caché, reintento e interrupción con embeddings deterministas de prueba, NO con E5 real.
- 21 plantillas Jinja compiladas y 19 pantallas renderizadas con StrictUndefined y datos sintéticos. Las capturas no corresponden a un servidor desplegado ni a analítica real.
- Chromium/Playwright comprobó 11 pantallas en dos anchos (1440 y 390 píxeles): 22 verificaciones estáticas, sin desbordamiento horizontal del documento detectado. Se cargó HTML/CSS local con set_content, sin navegación HTTP ni ejecución del comportamiento JavaScript.
- Python compileall y sintaxis de ambos JavaScript correctos. La isla React pasó transpileModule de TypeScript sin diagnósticos de sintaxis; no es una compilación completa del portal ni un chequeo exhaustivo de tipos.
- Compose analizado como YAML y comprobado estáticamente: dos servicios, sin puertos de producción publicados, variables explícitas. No se ejecutó Docker Compose.

Los archivos unit-tests.txt/XML, templates.json, browser-layout.json, typescript-syntax.json y validation.json registran el alcance. Ninguno acredita seguridad absoluta o exactitud factual del RAG.

### No ejecutado en el entorno inicial

El entorno carece de Flask, FastEmbed y ONNX Runtime y no permite completar las descargas/instalaciones externas necesarias. Por eso no se ejecutaron las nueve pruebas HTTP Flask incluidas, el modelo E5 real, Qdrant Server, las respuestas de Ollama, el build Docker, el despliegue Coolify ni mediciones de memoria/velocidad en el VPS. Tampoco hubo auditoría independiente, pip-audit de la imagen final o build completo Astro/React. El workflow de GitHub está incluido pero no se ejecutó desde esta entrega.

Las dependencias directas están fijadas; la compatibilidad del árbol transitivo debe comprobarse en el destino. No hay embeddings precalculados en el ZIP. La guía se tokenizará e indexará allí y deberá evaluarse con las 62 preguntas y 12 situaciones de revisión humana suministradas.

### Hallazgos y límites conocidos de la entrega inicial

La comprobación de referencias es estructural, no un verificador de respaldo por afirmación. El límite de contexto del proveedor está expresado en caracteres y tokens de salida, no como un tokenizador exacto del LLM remoto. El presupuesto de solicitudes no mide costo monetario. La proyección PCA es exploratoria. La cola y SQLite están diseñadas para una sola instancia. El borrado de una base retirada debe realizarse sin consultas en vuelo: no se implementaron leases de lectura distribuidos. La personalización visual completa requiere editar CSS/plantillas.

Antes de uso institucional, seguir docs/PUESTA_EN_MARCHA.md, registrar resultados reales y resolver los problemas que aparezcan. La etiqueta RC es deliberada: el código está entregado, la puesta en producción no está certificada.
