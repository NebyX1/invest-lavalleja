# Despliegue con Coolify

Esta configuración está preparada para un único VPS y una instancia de API. No fue desplegada desde esta entrega.

## Preparar el repositorio y los secretos

Extraer el proyecto y revisar los archivos antes de subir el código al repositorio elegido. No subir `.env`, `data/`, copias ni el corpus interno. No se creó ningún repositorio remoto automáticamente.

Ejecutar `python scripts/setup_env.py` en un equipo de administración. Genera claves distintas para sesión, cifrado y Qdrant, sin sobrescribir un `.env` existente. Completar el token de Ollama y los dominios. Transferir las variables a **Environment Variables** de Coolify mediante un canal administrativo seguro, nunca como archivos públicos o variables del frontend.

El Compose usa referencias `${VARIABLE}` explícitas para que Coolify las descubra. En Docker local, Compose las toma de `.env`; en Coolify las aporta la configuración del recurso. El contenedor recibe variables de entorno y no requiere copiar el archivo secreto a la imagen. No marcar credenciales como argumentos de build.

Variables mínimas:

```dotenv
APP_ENV=production
SECRET_KEY=<generada por setup_env.py>
ENCRYPTION_KEY=<generada por setup_env.py>
QDRANT_API_KEY=<generada por setup_env.py>
TRUSTED_HOSTS=gianna.tu-dominio.uy,127.0.0.1,localhost
PUBLIC_ORIGINS=https://invest.tu-dominio.uy,https://gianna.tu-dominio.uy
PROXY_HOPS=1
OLLAMA_API_KEY=<tu token>
OLLAMA_MODEL=
E5_REVISION=main
```

Los dominios son ejemplos, no direcciones ya creadas. Agregar el origen de la propia API permite utilizar `/chat`. `TRUSTED_HOSTS` usa nombres sin esquema ni puerto; `PUBLIC_ORIGINS` usa esquema y host exactos, con puerto solo cuando forma parte del origen. No utilizar `*`.

## Crear el recurso

Crear una Application desde el repositorio central de Invest Lavalleja, seleccionar **Docker Compose** como Build Pack, directorio base `/backend` y ubicación del archivo `compose.yaml` (relativa a ese directorio). Coolify buscará `backend/compose.yaml` en el repositorio; `build: .` usará `backend/` como contexto, donde están el Dockerfile y `requirements.txt`. Usar el modo normal, no Raw Compose. No hace falta publicar por `ports:` ningún servicio.

En el servicio **api**, establecer el dominio con el puerto interno:

```text
https://gianna.tu-dominio.uy:8000
```

El visitante utiliza HTTPS normal, sin añadir 8000 en la dirección pública. Ese sufijo indica al proxy de Coolify el puerto del contenedor. Qdrant no lleva dominio ni puerto publicado. Su nombre interno es `qdrant:6333`.

El Compose define `gianna_data:/app/data` y `qdrant_data:/qdrant/storage`. Conservar ambos entre redeploys. El health check interno de la API consulta `/health/live`, que no descarga modelos ni llama a un proveedor de pago. Revisar Qdrant desde Diagnóstico una vez iniciada la aplicación.

En el build del portal Astro, definir `PUBLIC_GIANNA_API_BASE=https://gianna.tu-dominio.uy` (sin ruta ni puerto interno). Añadir el origen HTTPS real del portal a `PUBLIC_ORIGINS` del backend. Esta variable pública contiene solo la URL de la API, nunca `OLLAMA_API_KEY`. Después de cambiarla, reconstruir el frontend estático. Hasta que haya una versión de conocimiento revisada y publicada, la página de Gianna informará que la base todavía no está disponible.

`PROXY_HOPS=1` solo es correcto cuando el acceso está exclusivamente detrás del proxy de confianza de Coolify. No añadir acceso directo a Internet ni confiar ciegamente en encabezados reenviados. Si existe otro proxy, revisar la cadena y los encabezados efectivos antes de cambiar este valor.

## Inicialización

Desplegar y abrir los logs. Si falta una clave, la aplicación rechaza el arranque en vez de generar un secreto efímero. En la terminal del contenedor **api**, ejecutar:

```bash
flask --app wsgi check-config
flask --app wsgi create-admin
```

Para reproducir el segundo factor por correo del sistema de referencia, configurar SMTP y usar `flask --app wsgi create-admin --mfa email`. El valor predeterminado es TOTP y no requiere SMTP. Entrar en `/admin/login`, resolver el CAPTCHA y completar el segundo factor elegido; con TOTP, guardar la recuperación. Desde ese momento, documentos, indexación, pruebas, usuarios y configuración operativa se manejan en el panel. No existe registro público de administradores ni credenciales iniciales impresas en logs.

En Ajustes, cargar el catálogo real de Ollama y elegir el modelo. Importar el JSON canónico, aprobar, indexar, evaluar y publicar según el manual. La API tiene acceso saliente a Hugging Face para la primera descarga y a Ollama para responder; Qdrant permanece en la red privada.

## Recursos y reproducibilidad

El archivo propone límites de 2 GiB / 2 CPU para API y 768 MiB / 1 CPU para Qdrant. **Son límites de arranque a comprobar, no consumos medidos ni mínimos garantizados.** Hay un proceso Gunicorn y un único modelo cargado, compartido por el chat y el trabajador de indexación. La indexación se intercala por lotes, pero puede aumentar la latencia del chat. Programar cargas importantes fuera de horas de atención.

Vigilar memoria al cargar ONNX y al calcular la proyección. Un cierre por OOM requiere aumentar el margen o revisar el perfil; no se soluciona multiplicando workers. El build de dependencias tiene un consumo diferente del servicio en reposo. Conservar espacio para la exportación original, cachés, SQLite, colecciones y copias; no se promete un tamaño final sin descargar el modelo.

Después de la primera indexación, copiar `revision_resolved` del perfil de la versión a `E5_REVISION`. Mantener versiones del modelo y paquetes coherentes. No cuantizar o cambiar pooling sin crear una nueva base vectorial y medir la pérdida de recuperación.

## Verificación de apertura

Probar desde una sesión sin autenticar que `/admin/bases` no revela información. Probar desde otro origen que la API pública lo rechaza. Confirmar que Qdrant no responde desde Internet. Reiniciar y comprobar persistencia, luego ejecutar las preguntas de evaluación y una conversación real de seguimiento.

Si aparece “No Available Server”, revisar health, logs, dominio con puerto interno, escucha `0.0.0.0:8000`, certificados y hosts permitidos. No desactivar autenticación, CSRF o validación de hosts para ocultar el problema.

Referencia oficial consultada el 28/09/2026: https://coolify.io/docs/applications/builds/docker-compose
