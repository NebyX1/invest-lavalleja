# Seguridad y operación

## Controles implementados

Contraseñas Argon2id; segundo factor obligatorio; TOTP con comprobación anti-reutilización; códigos de recuperación de un solo uso; OTP por correo de corta duración y con límite de intentos; secretos TOTP y contexto de conversación cifrados con Fernet. Los códigos de correo se almacenan mediante HMAC con clave y contexto, no como seis dígitos en texto plano.

Las sesiones de administración son opacas, almacenadas en servidor, caducan y se revocan. El navegador recibe una cookie HttpOnly, Secure en producción, SameSite Strict y restringida al camino `/admin`. Cada solicitud comprueba que el usuario siga activo. No se permite dejar el sistema sin un propietario activo mediante la gestión ordinaria de cuentas.

Los formularios administrativos usan CSRF y las acciones tienen autorización por rol. Publicación, retirada, borrado y administración de usuarios necesitan verificación reciente. No se aceptan cambios de permisos por petición del chat. Las respuestas y documentos se muestran como texto escapado, sin ejecutar el HTML suministrado por usuarios o modelos.

El panel no carga scripts desde CDNs; CSP con recursos propios, no `unsafe-inline`. Hay limitación persistente de intentos y consultas, límites de tamaño, formatos de carga restringidos, detección de macros/DOCTYPE/expansión ZIP excesiva y guardado con nombres generados por el servidor. Qdrant tiene clave y no expone un puerto público en el Compose de producción.

La auditoría registra acciones, usuarios, objetos e identificadores; no imprime tokens ni contraseñas. No equivale a un registro inmutable frente a un administrador del sistema operativo: SQLite y el volumen siguen bajo su control.

## Límites que no deben ocultarse

Es una implementación nueva y necesita revisión independiente antes de exposición institucional. No se realizó pentest, auditoría de seguridad ni certificación. TOTP no es resistente al phishing de la misma forma que una passkey; el método por correo depende además de la seguridad de esa cuenta. WebAuthn/passkeys no está implementado.

Las preguntas públicas usan capacidades anónimas de sesión. El origen HTTP y CORS no autentican a una persona y un cliente no navegador puede imitar encabezados. Los límites y presupuestos reducen el abuso, no garantizan impedirlo. Para tráfico público relevante, aplicar también controles de proxy/WAF y revisar cuotas de Ollama. El presupuesto de solicitudes no es una factura en dinero ni garantiza un techo monetario contractual.

La validación de citas es estructural: comprueba que la referencia pertenece al contexto permitido y evita URLs inventadas por el modelo. No comprueba automáticamente el respaldo de cada afirmación. El prompt no es una barrera suficiente contra inyección por sí solo; el aislamiento de la colección y la resolución de evidencia en servidor sí limitan el acceso. No hay garantía absoluta de ausencia de alucinaciones.

Las colecciones de Qdrant guardan vectores y metadatos, y SQLite guarda el texto completo. Los vectores no convierten en público un documento privado ni deben tratarse como una anonimización irreversible. Todas las exportaciones del admin pueden incluir material interno.

## Secretos y `.env`

El repositorio de referencia mostraba un `.env` versionado. No se leyeron ni copiaron sus valores. Si contiene credenciales reales, deben tratarse como potencialmente expuestas y rotarse; borrar el archivo de la última revisión no elimina su historia.

La nueva aplicación ignora `.env` en Git y Docker. `.env.example` solo contiene campos vacíos o ejemplos. Un usuario del panel no puede recuperar el token de Ollama. Tampoco debe introducirlo en la personalidad, en una fuente, una pregunta o un documento.

`SECRET_KEY` protege funciones de autenticación y firmas/HMAC; `ENCRYPTION_KEY` cifra TOTP y contexto. No sustituirlas en cada reinicio. Conservar una copia cifrada separada. Cambiar `SECRET_KEY` invalida material de autenticación; cambiar `ENCRYPTION_KEY` sin migración impide descifrar datos existentes. No se incluye una rotación automática con recifrado.

## Copias

Hay dos datos persistentes diferentes: SQLite y archivos de la API en `gianna_data`, y las colecciones de Qdrant en `qdrant_data`. La imagen Docker o el código Git no son un respaldo de estos volúmenes.

El script `scripts/backup.py` crea una copia consistente de SQLite mediante su API de backup. **No copia automáticamente Qdrant, `.env`, modelos o cargas pendientes.** Exportar también el corpus desde el panel y conservar las claves de cifrado en otro lugar seguro.

Para un respaldo completo coordinado, realizarlo en una ventana de mantenimiento con la API detenida y conservar los volúmenes de datos o utilizar snapshots de Qdrant según su documentación. Registrar versión de Qdrant, aplicación, paquetes y huella E5. Cifrar los respaldos y probar restauración en una instancia separada.

```bash
# Dentro del contenedor API, crea la copia en su volumen de datos:
python scripts/backup.py --output /app/data/exports/respaldo-gianna.sqlite3
```

Consultar la salida para su ubicación real; descargarla mediante un canal administrativo seguro. No publicar `/app/data` como carpeta web.

## Restauración y reindexación

El script `scripts/restore_sqlite.py` es deliberadamente de consola, no una carga pública del panel. Debe ejecutarse con la API detenida, `--confirm-api-stopped` y `--confirm`. Revisar su ayuda para indicar el archivo y directorio correctos.

La restauración valida SQLite, respalda la base existente, elimina WAL/SHM antiguos y revoca sesiones. Retira el puntero publicado porque no puede suponer que los datos externos de Qdrant coincidan con esa copia. Reindexar y probar antes de volver a publicar. No declara que restaurar un archivo SQLite por sí solo restaure el RAG completo.

Si se pierde el autenticador, utilizar primero un código de recuperación. Si se perdieron ambos y hay acceso autorizado a la consola:

```bash
flask --app wsgi reset-admin
```

El comando pide correo y contraseña oculta, solicita confirmación, revoca sesiones y exige configurar nuevamente TOTP. No da privilegios del sistema operativo a un usuario del chat.

## Mantenimiento

Revisar trabajos fallidos, consultas sin evidencia, fuentes pendientes, disco, memoria y errores del proveedor. Los trabajos de limpieza retiran sesiones y datos vencidos según la configuración; un trabajo bloqueado o un servidor apagado puede demorar esa limpieza. Las cargas fallidas pueden permanecer para reintento, por lo que conviene revisar periódicamente su almacenamiento.

Las consultas no se guardan en texto claro dentro de analítica. El contexto breve de chat sí se cifra en SQLite con retención y eliminación explícita. La IP se transforma para los límites, no se presenta como una identidad. El servidor, proveedor y proxy pueden tener sus propios registros: configurar y documentar su retención por separado.

Mantener un único worker Gunicorn. La cola y los controles son para un despliegue pequeño, no HA. La activación de la versión es transaccional en SQLite y el contenido de cada colección es inmutable una vez lista. No hay una transacción distribuida, consenso, réplica ni garantía de lectura durante el borrado inmediato de una versión retirada; usar una ventana sin peticiones en vuelo para eliminaciones.

Fuentes técnicas: OWASP MFA https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html ; Flask https://flask.palletsprojects.com/en/stable/web-security/ ; Qdrant snapshots https://qdrant.tech/documentation/operations/snapshots/ . Consultadas para el diseño, no como certificación de este código.
