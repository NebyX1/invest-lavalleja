# Persistencia de Gianna en MinIO · 1.0.0-rc3

El backend productivo utiliza MariaDB y MinIO. `DATA_DIR`, por defecto `/app/data`
en la imagen, es una caché y espacio de trabajo reconstruible. No requiere un
montaje persistente, ni un parámetro nuevo de selección de almacenamiento.

## Configuración de la IDL

Se mantienen los nombres indicados por el responsable:

```dotenv
MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_SECURE=True
MINIO_BUCKET_NAME=
MINIO_PUBLIC_URL=
```

`MINIO_ENDPOINT` es el host y puerto de la API S3, sin esquema ni ruta; TLS se
controla con `MINIO_SECURE`. `MINIO_BUCKET_NAME` identifica el bucket propio de
Gianna. `MINIO_PUBLIC_URL` se acepta como configuración institucional y no se usa
para publicar archivos privados, generar URLs públicas ni exponer credenciales.
Las claves permanecen exclusivamente en el entorno del backend.

MariaDB, cifrado, correo y Ollama conservan sus variables existentes. El script
de simplificación del entorno conserva también las seis variables de MinIO.
No se leen `.env` ni credenciales de otros proyectos.

## Autoridad de los datos

| Elemento | Persistencia y recuperación |
| --- | --- |
| Publicación, usuarios, permisos, borradores, fotografías y vectores | MariaDB conserva la autoridad y el puntero activo |
| Archivos de importación | MinIO antes de confirmar su recepción y encolar el trabajo; SHA-256 ligado al payload SQL |
| Respaldo de recuperación por versión | MinIO, validado contra fotografía, perfil, cobertura, hash y vectores SQL |
| Pesos y manifiestos de modelos fijados | MinIO, transferencias por streaming y SHA-256; recuperación del hub sólo si el artefacto fijado no estaba archivado |
| Colecciones y FTS de LanceDB | Caché local reconstruida desde los vectores verificados de SQL y MinIO |
| Exportaciones del panel | Se generan desde SQL y se entregan al usuario; no dependen de un archivo local permanente |

Los objetos viven bajo `gianna/v1/`. Un objeto existente con otro contenido no
se sobrescribe. El backend no elimina objetos ni cambia políticas de buckets.

## Arranque y redeploy

1. El diagnóstico inspecciona SQL, MinIO, privacidad, identidad y acceso a la
   caché. La inspección no crea buckets, carpetas ni objetos.
2. Tras un inventario válido, el worker crea el bucket si falta y las credenciales
   lo permiten; vincula su marcador con `minio_storage_identity` en SQL. Si el
   bucket ya existe, lo reutiliza. La inicialización interrumpida se retoma con
   la misma identidad.
3. Un namespace ocupado sin vínculo verificable, otra identidad o la pérdida de
   un bucket ya registrado bloquean con una causa específica. No se adopta una
   instalación ajena ni se crea un reemplazo vacío para ocultar una pérdida.
4. Una caché nueva recupera los modelos desde MinIO, verifica su huella y restaura
   LanceDB/FTS desde la fotografía publicada. Mantiene el puntero activo.
5. Las importaciones pendientes se recuperan de MinIO usando su hash SQL. Los
   archivos anteriores a esta integración se conservan en MinIO si siguen
   disponibles; si el contenedor anterior los perdió, se identifica esa falta.

`physical_storage_identity` y los archivos locales anteriores se conservan.
No se cambia el perfil de embeddings, normalización, dimensiones ni modelo.
La compatibilidad local permanece para pruebas y mantenimiento explícito;
`Config.from_env` selecciona MinIO para el perfil productivo.

## Diagnóstico y permisos

El panel identifica **MinIO** y la caché por separado. En este modo nunca consulta
`/proc/self/mountinfo` ni devuelve `storage_not_mounted`. Errores de configuración,
credenciales, red, identidad, hash o espacio siguen siendo errores reales y
accionables: no se ocultan ni se convierten en disponibilidad ficticia.

Las credenciales necesitan leer/escribir objetos en el bucket de Gianna,
inspeccionar su existencia/política y enumerar su namespace. Crear un bucket
nuevo requiere además ese permiso; no es necesario cuando ya está provisionado.
Se exige un bucket privado y no se modifica la política de otros proyectos.

Los logs JSON registran operación, duración, bytes, hash y contexto de
arranque/trabajo/solicitud. Omiten claves, URLs firmadas, contenido privado y
mensajes arbitrarios de excepciones. Las comprobaciones de salud se cachean
cinco segundos para evitar lecturas remotas repetidas en cada petición.

## Verificación

```bash
python -m pytest --mariadb-docker --minio-docker -q
python -m pytest tests/test_minio_redeploy_docker.py --recovery-docker -s
```

La segunda prueba usa MariaDB, MinIO, LanceDB y ONNX reales y reemplaza dos veces
el contenedor completo de la API, sin montar ningún volumen local. Los recursos
y credenciales son exclusivos de la prueba; no hay llamadas de generación.

Referencia institucional revisada: [almacenamiento de Sala de Medios](https://github.com/IntendenciaDeLavalleja/sala-de-medios-backend/blob/99723bd3d5bb466986557f9d74f0f5618d6cffff/app/storage.py).
La variable de bucket de Gianna es **MINIO_BUCKET_NAME**, conforme a la
instrucción expresa del responsable, y no la variante de ese otro proyecto.
