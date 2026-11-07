# Seguridad y operación

## Controles implementados

Contraseñas Argon2id y segundo factor por correo obligatorio, como en Buzón Ciudadano. Los códigos de seis dígitos se almacenan mediante Argon2id, vencen en diez minutos, admiten como máximo seis intentos y se consumen transaccionalmente al verificarlos. Un nuevo inicio de sesión invalida el código anterior. Los fallos SMTP invalidan el desafío y no abren sesión. No se imprimen códigos en logs. El contexto de conversación se cifra con Fernet.

Las sesiones de administración son opacas, almacenadas en servidor, caducan y se revocan. El navegador recibe una cookie HttpOnly, Secure en producción, SameSite Strict y restringida al camino `/admin`. Cada solicitud comprueba que el usuario siga activo. No se permite dejar el sistema sin un propietario activo mediante la gestión ordinaria de cuentas.

Los formularios administrativos usan CSRF y las acciones tienen autorización por rol. Publicación, retirada, borrado y administración de usuarios necesitan verificación reciente. No se aceptan cambios de permisos por petición del chat. Las respuestas y documentos se muestran como texto escapado, sin ejecutar el HTML suministrado por usuarios o modelos.

El panel no carga scripts desde CDNs; CSP con recursos propios, no `unsafe-inline`. Hay limitación persistente de intentos y consultas, límites de tamaño, formatos de carga restringidos, detección de macros/DOCTYPE/expansión ZIP excesiva y guardado con nombres generados por el servidor. LanceDB está embebido y solo es accesible desde el volumen privado de la API.

La auditoría registra acciones, usuarios, objetos e identificadores; no imprime tokens ni contraseñas. No equivale a un registro inmutable frente a un administrador de MariaDB o del servidor.

## Límites que no deben ocultarse

Es una implementación nueva y necesita revisión independiente antes de exposición institucional. No se realizó pentest, auditoría de seguridad ni certificación. El segundo factor por correo depende de la seguridad de esa cuenta. WebAuthn/passkeys no está implementado.

Las preguntas públicas usan capacidades anónimas de sesión. El origen HTTP y CORS no autentican a una persona y un cliente no navegador puede imitar encabezados. Los límites y presupuestos reducen el abuso, no garantizan impedirlo. Para tráfico público relevante, aplicar también controles de proxy/WAF y revisar cuotas de Ollama. El presupuesto de solicitudes no es una factura en dinero ni garantiza un techo monetario contractual.

La validación de citas es estructural: comprueba que la referencia pertenece al contexto permitido y evita URLs inventadas por el modelo. No comprueba automáticamente el respaldo de cada afirmación. El prompt no es una barrera suficiente contra inyección por sí solo; el aislamiento de la colección y la resolución de evidencia en servidor sí limitan el acceso. No hay garantía absoluta de ausencia de alucinaciones.

Las tablas LanceDB guardan vectores, texto y metadatos de los registros públicos aprobados; MariaDB conserva el corpus editorial, sesiones cifradas, auditoría y snapshots. Los vectores no convierten en público un documento privado ni deben tratarse como una anonimización irreversible. Todas las exportaciones del admin pueden incluir material interno.

## Secretos y `.env`

El repositorio de referencia mostraba un `.env` versionado. No se leyeron ni copiaron sus valores. Si contiene credenciales reales, deben tratarse como potencialmente expuestas y rotarse; borrar el archivo de la última revisión no elimina su historia.

La nueva aplicación ignora `.env` en Git y Docker. `.env.example` solo contiene campos vacíos o ejemplos. Un usuario del panel no puede recuperar el token de Ollama. Tampoco debe introducirlo en la personalidad, en una fuente, una pregunta o un documento.

`SECRET_KEY` protege funciones de autenticación y firmas/HMAC; `ENCRYPTION_KEY` cifra el contexto de conversación. No sustituirlas en cada reinicio. Conservar una copia cifrada separada. Cambiar `SECRET_KEY` invalida material de autenticación; cambiar `ENCRYPTION_KEY` sin migración impide descifrar datos existentes. No se incluye una rotación automática con recifrado.

## Copias

El volumen `gianna_data` conserva archivos de la API, modelos y tablas LanceDB. MariaDB se respalda por separado; la imagen Docker o el código Git no contienen datos de aplicación.

El script `scripts/backup.py` crea un dump lógico consistente de MariaDB con `mariadb-dump`. **No copia automáticamente LanceDB, `.env`, modelos o cargas pendientes.** Exportar también el corpus desde el panel y conservar las claves de cifrado en otro lugar seguro.

Para un respaldo completo coordinado, realizarlo en una ventana de mantenimiento con la API detenida y conservar el volumen de datos completo. Registrar versión de LanceDB, aplicación, paquetes y huellas de los modelos (Granite/mMARCO y, si hay versiones antiguas publicadas, Bekko/Horizon). Cifrar los respaldos y probar restauración en una instancia separada.

```bash
# Dentro del contenedor API, crea el dump SQL en su volumen de datos:
python scripts/backup.py --output /app/data/exports/respaldo-gianna.sql
```

Consultar la salida para su ubicación real; descargarla mediante un canal administrativo seguro. No publicar `/app/data` como carpeta web.

## Migración desde SQLite y recuperación

El importador `scripts/migrate_sqlite_to_mariadb.py` es de consola y solo se usa una vez durante el cambio de motor. Exige detener la API, usar `--confirm-api-stopped --confirm`, valida la integridad de SQLite y exige que el esquema MariaDB de destino esté vacío. Verifica los conteos después de importar y conserva intacto el origen. No mezclarlo con la base de datos del Buzón Ciudadano.

Los respaldos `.sql` se restauran en un esquema MariaDB de recuperación siguiendo el procedimiento operativo del servidor y con la API detenida. Mantener además una copia compatible de LanceDB y los modelos/huellas; restaurar solo SQL puede apuntar a una colección que no existe. Probar la instancia aislada antes del retorno. No borrar el SQLite legado hasta validar la migración y completar un respaldo MariaDB y LanceDB.

Las cuentas existentes se migran automáticamente a segundo factor por correo al desplegar esta versión. Se conservan sus contraseñas, roles y estado activo; se retiran las claves y códigos del autenticador anterior, se revocan sus sesiones y se invalidan los desafíos pendientes. La migración se ejecuta una sola vez. Si hay que restablecer una contraseña y se dispone de acceso autorizado a la consola:

```bash
flask --app wsgi reset-admin
```

El comando pide correo y contraseña oculta, solicita confirmación y revoca sesiones. El segundo factor sigue siendo el código enviado al correo de la cuenta. No da privilegios del sistema operativo a un usuario del chat.

## Mantenimiento

Revisar trabajos fallidos, consultas sin evidencia, fuentes pendientes, disco, memoria y errores del proveedor. Los trabajos de limpieza retiran sesiones y datos vencidos según la configuración; un trabajo bloqueado o un servidor apagado puede demorar esa limpieza. Las cargas fallidas pueden permanecer para reintento, por lo que conviene revisar periódicamente su almacenamiento.

Las consultas no se guardan en texto claro dentro de analítica. El contexto breve de chat se cifra antes de guardarse en MariaDB y tiene retención y eliminación explícita. La IP se transforma para los límites, no se presenta como una identidad. El servidor, proveedor y proxy pueden tener sus propios registros: configurar y documentar su retención por separado.

Mantener un único worker Gunicorn. La cola y los controles son para un despliegue pequeño, no HA. La activación de la versión es transaccional en MariaDB y el contenido de cada colección es inmutable una vez lista. No hay una transacción distribuida, consenso, réplica ni garantía de lectura durante el borrado inmediato de una versión retirada; usar una ventana sin peticiones en vuelo para eliminaciones.

Fuentes técnicas: OWASP MFA https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html ; Flask https://flask.palletsprojects.com/en/stable/web-security/ ; LanceDB https://docs.lancedb.com/ . Consultadas para el diseño, no como certificación de este código.
