# Despliegue con Coolify

El portal y la API se despliegan desde sus repositorios separados: `invest-lavalleja-frontend` e `invest-lavalleja-backend`. Esta configuración está preparada para un único VPS y una instancia de API; debe validarse en Coolify antes de abrir el servicio al público.

## Preparar el repositorio y los secretos

Extraer el proyecto y revisar los archivos antes de subir el código al repositorio elegido. No subir `.env`, `data/`, copias ni el corpus interno. No se creó ningún repositorio remoto automáticamente.

En un equipo de administración confiable, ejecutar `python scripts/setup_env.py` desde la raíz del repositorio backend. Genera claves distintas para sesión y cifrado en `.env`, sin sobrescribir uno existente y sin imprimir los secretos. Copiar los valores `SECRET_KEY` y `ENCRYPTION_KEY` a **Environment Variables** de Coolify por un canal seguro; no dejar los valores vacíos, de ejemplo o cortos. `SECRET_KEY` debe tener al menos 32 caracteres y `ENCRYPTION_KEY` debe ser una clave Fernet válida. No reutilizar la misma clave para ambas variables.

El log de arranque debe mostrar que `SECRET_KEY` tiene al menos 32 caracteres si el valor configurado no cumple ese mínimo. Reemplazarlo por el valor generado, guardar la variable y volver a desplegar. Mantener ambas claves estables entre despliegues: cambiar `ENCRYPTION_KEY` sin migración impide descifrar datos existentes.

El Compose usa referencias `${VARIABLE}` explícitas para que Coolify las descubra. En Docker local, Compose las toma de `.env`; en Coolify las aporta la configuración del recurso. El contenedor recibe variables de entorno y no requiere copiar el archivo secreto a la imagen. No marcar credenciales como argumentos de build.

Variables mínimas:

Cada instalación configura una única `DATABASE_URL` para su base MariaDB. La preparación del recurso de producción no requiere variables de base de datos para pruebas.

```dotenv
FLASK_ENV=production
SECRET_KEY=<generada por setup_env.py>
ENCRYPTION_KEY=<generada por setup_env.py>
CORS_ORIGINS=https://invest.tu-dominio.uy,https://gianna.tu-dominio.uy
OLLAMA_HOST=https://ollama.com
OLLAMA_API_KEY=<tu token>
OLLAMA_MODEL=deepseek-v4.1-flash
DATABASE_URL=mariadb+mariadbconnector://gianna_app:<password>@<host>:3306/gianna_invest
MAIL_SERVER=
MAIL_PORT=465
MAIL_USE_TLS=False
MAIL_USE_SSL=True
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=
```

Son 15 campos de configuración de producción. `DATABASE_URL` debe señalar a un esquema y una cuenta exclusivos de Gianna; no reutilizar la URL `buzon-ciudadano` de `sample-backend`. Los dominios son ejemplos, no direcciones ya creadas. `CORS_ORIGINS` incluye el portal y la propia API: de ellos se obtienen también los hosts permitidos. Usar esquema y host exactos, con puerto solo cuando forma parte del origen, sin rutas ni `*`. Los ajustes técnicos de Bekko/Horizon/LanceDB, CPU, límites y almacenamiento tienen valores predeterminados en el código; no se copian a Coolify.

Para ordenar un `.env` anterior, ejecutar primero `python -m scripts.simplify_env` y después `python -m scripts.simplify_env --apply`. Se conserva un respaldo y se verifica que las claves, URLs de base, el modelo, el correo y las demás opciones efectivas no cambien. No ejecutar el generador de claves para reemplazar una instalación existente. Antes del primer arranque, configurar el esquema MariaDB y sus credenciales en Coolify; la aplicación aplica las migraciones al iniciar.

## Crear el recurso backend

Crear una Application desde `IntendenciaDeLavalleja/invest-lavalleja-backend`. Seleccionar **Docker Compose**, directorio base `/` y archivo `compose.yaml` en la raíz; usar el modo normal, no Raw Compose. El contexto `build: .` incluye el Dockerfile y `requirements.txt`. No hace falta publicar servicios mediante `ports:`. Si se mantiene el build pack Dockerfile que ya usa la aplicación de Coolify, crear además un volumen persistente montado en `/app/data` para LanceDB, modelos y exports.

El Dockerfile incluye `curl` para que el chequeo HTTP de Coolify pueda consultar la salud de la API, además del health check definido en Compose.

En el servicio **api**, establecer el dominio con el puerto interno:

```text
https://gianna.tu-dominio.uy:8000
```

El visitante utiliza HTTPS normal, sin añadir 8000 en la dirección pública. Ese sufijo indica al proxy de Coolify el puerto del contenedor. LanceDB está embebido en la API y no necesita dominio ni puerto propios.

El Compose define `gianna_data:/app/data`. Conserva modelos, cargas, exports y tablas LanceDB entre redeploys. Configurar `DATABASE_URL` con una base MariaDB dedicada a Gianna, accesible desde el contenedor; no usar el esquema `buzon-ciudadano`, otra base compartida ni una cuenta `root`. MariaDB mantiene su propio almacenamiento persistente y respaldo. El health check interno de la API consulta `/health/live`, que no descarga modelos ni llama a un proveedor de pago. Revisar MariaDB y LanceDB desde Diagnóstico una vez iniciada la aplicación.

En el build del portal Astro, definir `PUBLIC_GIANNA_API_BASE=https://gianna.tu-dominio.uy` (sin ruta ni puerto interno). Añadir el origen HTTPS real del portal a `CORS_ORIGINS` del backend. Esta variable pública contiene solo la URL de la API, nunca `OLLAMA_API_KEY`. Después de cambiarla, reconstruir el frontend estático. La configuración de construcción del portal está en `docs/COOLIFY.md` del repositorio frontend. Hasta que haya una versión de conocimiento revisada y publicada, la página de Gianna informará que la base todavía no está disponible.

El perfil de producción ya configura un salto de proxy; no hace falta una variable `PROXY_HOPS` en el despliegue habitual. Esto exige acceso exclusivamente detrás del proxy de confianza de Coolify, que debe sobrescribir los encabezados reenviados. No añadir acceso directo a Internet. La IP pública del VPS no identifica necesariamente al proxy que conecta con el contenedor. Si hay otra topología, revisarla expresamente antes de usar el perfil. Desarrollo no confía en encabezados reenviados.

## Inicialización

Desplegar y abrir los logs. Si falta una clave, la aplicación rechaza el arranque en vez de generar un secreto efímero. En la terminal del contenedor **api**, ejecutar:

```bash
python -m flask check-config
python -m flask create-admin "Nombre completo" "superadmin@example.com" "contraseña-de-al-menos-12-caracteres" true
# Para un administrador sin gestión de cuentas/configuración ni publicación:
python -m flask create-admin "Nombre completo" "admin@example.com" "otra-contraseña-de-al-menos-12-caracteres" false
```

Reemplazar los nombres, correos y contraseñas de ejemplo. Se mantiene la sintaxis de Buzón Ciudadano: `true` crea un superadministrador (`owner`, Propietario en el panel) y `false` un administrador (`editor`, Editor en el panel). Omitir el booleano equivale a `false`. El comando sin argumentos conserva el alta interactiva de un superadministrador con contraseña oculta, sin incluirla en el historial de la terminal. No se agregan variables de entorno ni se cambian roles existentes.

El segundo factor de todas las cuentas es el código por correo, como en Buzón Ciudadano. Configurar `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD` y `MAIL_DEFAULT_SENDER`. No activar TLS y SSL a la vez: normalmente SSL utiliza 465 y STARTTLS, 587. En producción no se admite correo configurado sin cifrado. Entrar en `/admin/login`, resolver el CAPTCHA e ingresar el código de seis dígitos enviado al correo de la cuenta; vence en diez minutos y es de un solo uso. Un error de envío no permite acceder al panel. No existe registro público de administradores ni credenciales iniciales impresas en logs.

El arranque migra las cuentas existentes al método institucional por correo sin cambiar sus contraseñas ni permisos. Revoca las sesiones del autenticador anterior y los desafíos pendientes, y retira las claves y códigos de recuperación anteriores. No hay que recrear usuarios, restablecer contraseñas ni agregar variables al entorno. Desplegar la imagen nueva e iniciar sesión nuevamente para recibir el código por correo.

En Ajustes, cargar el catálogo real de Ollama y elegir el modelo. Importar el JSON canónico, aprobar, indexar, evaluar y publicar según el manual. En la terminal del contenedor **api**, ejecutar `python -m scripts.prepare_models --model-dir /app/data/models`. El comando verifica los artefactos y luego inicializa Bekko y Horizon y ejecuta una inferencia de prueba. Para revisar modelos ya descargados sin llamar a Hugging Face, ejecutar `python -m scripts.check_model_runtime`. No reintentar la vectorización si la comprobación no termina con `Verificación de inferencia Bekko/Horizon superada`.

Durante la carga, los logs del backend informan la etapa actual: verificación de manifiestos, tokenizadores, sesión ONNX de Horizon o compilación OpenVINO de Bekko. Si Gunicorn reinicia un worker con `SIGSEGV`, revisar la última etapa registrada; no tratarlo como demora de vectorización ni repetir el trabajo a ciegas. La comprobación independiente de modelos ejecuta los mismos artefactos y motores en el contenedor sin iniciar trabajos ni modificar la base.

## Recursos y reproducibilidad

El archivo propone límites de 2 GiB / 2 CPU para API. **Son límites de arranque a comprobar, no consumos medidos ni mínimos garantizados.** Hay un proceso Gunicorn y Bekko y Horizon cargados, compartido por el chat y el trabajador de indexación. La indexación se intercala por lotes, pero puede aumentar la latencia del chat. Programar cargas importantes fuera de horas de atención.

Vigilar memoria al cargar ONNX y al calcular la proyección. Un cierre por OOM requiere aumentar el margen o revisar el perfil; no se soluciona multiplicando workers. El build de dependencias tiene un consumo diferente del servicio en reposo. Conservar espacio para la exportación original, cachés, colecciones y copias; no se promete un tamaño final sin descargar el modelo.

Las revisiones de Bekko y Horizon están fijadas en `gianna/services/neural.py` y los artefactos se verifican con SHA-256. Mantener versiones del modelo y paquetes coherentes. No cuantizar o cambiar pooling sin crear una nueva base vectorial y medir la pérdida de recuperación.

## Importación que falla con IntegrityError al terminar la conversión

La migración MariaDB `003.sql` restaura nueve valores por defecto que el código ya esperaba: descripción y JSON de bases, versiones, auditoría y consultas. La omisión de `bases.description` en el esquema anterior impedía importar una guía válida con SQL estricto; también faltaba el valor inicial de `versions.report_json` al preparar una indexación. La corrección se aplica automáticamente al arrancar el backend actualizado, tanto en instalaciones nuevas como existentes. No requiere nuevas variables, vaciar tablas, recrear cuentas ni desactivar el modo SQL estricto.

Antes del redeploy, conservar un respaldo MariaDB y el volumen `/app/data`. Tras desplegar, verificar `/health/ready` y que `SELECT MAX(version) FROM schema_versions` devuelva al menos `3`. En el trabajo de importación fallido, usar **Reintentar de forma segura**: el archivo se conserva cuando falla la transacción y el trabajo recupera la misma base sin duplicarla. Si la carga original ya no existe en el volumen persistente, volver a subir el archivo. La importación continúa siendo un borrador: no aprueba registros ni publica conocimiento automáticamente.

Regresión reproducible desde la raíz del backend: `python -m pytest tests/test_mariadb_import.py --mariadb-docker -q`. Requiere Docker y `mariadb:11.4`; crea un servidor efímero en loopback con SQL estricto, claves aleatorias y esquemas exclusivos, y los elimina al terminar. No usa `.env` ni bases existentes. Sin la opción, estas pruebas se omiten explícitamente. El caso con la guía privada se omite cuando el documento no está disponible; los demás casos usan un corpus de prueba autocontenido.

## Verificación de apertura

Probar desde una sesión sin autenticar que `/admin/bases` no revela información. Probar desde otro origen que la API pública lo rechaza. Confirmar que el volumen LanceDB no se publica como archivos estáticos. Reiniciar y comprobar persistencia, luego ejecutar las preguntas de evaluación y una conversación real de seguimiento.

Si aparece “No Available Server”, revisar health, logs, dominio con puerto interno, escucha `0.0.0.0:8000`, certificados y hosts permitidos. No desactivar autenticación, CSRF o validación de hosts para ocultar el problema.

El panel público de la instalación IDL está en `https://mapi.invest.lavalleja.uy/admin/login`. Si un formulario devuelve 403 con “Origen del formulario no permitido”, revisar el `Origin` de ese POST y la cabecera `Referrer-Policy` del documento que lo envió. La aplicación utiliza `same-origin`: conserva el origen en los formularios propios y no envía referencias a otros sitios. No sustituirla por `no-referrer` en Coolify o en otro proxy: los formularios HTML pueden pasar a enviar `Origin: null`, que el backend rechaza deliberadamente. La corrección requiere reconstruir y desplegar el backend actualizado, no agregar variables al `.env` ni permitir `null` como origen. Referencia: [efecto de Referrer-Policy sobre Origin](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header).

Referencia oficial consultada el 28/09/2026: https://coolify.io/docs/applications/builds/docker-compose
