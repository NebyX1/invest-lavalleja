# Despliegue del portal con Coolify

El portal Astro se publica como sitio estático servido por Nginx. El repositorio ya incluye el `Dockerfile` y la configuración de Nginx para construir la aplicación y servir las rutas estáticas.

## Crear el recurso

Crear una Application desde `IntendenciaDeLavalleja/invest-lavalleja-frontend`, seleccionar el build pack **Dockerfile**, dejar el directorio base en `/` y usar el `Dockerfile` de la raíz. Configurar el puerto interno `80`. El health check del contenedor responde en `/health`.

Definir estos argumentos de construcción en Coolify antes de desplegar:

| Argumento | Valor |
|---|---|
| `PUBLIC_SITE_URL` | Origen HTTPS público del portal, por ejemplo `https://invest.tu-dominio.uy` |
| `PUBLIC_INDEXING` | `true` para habilitar indexación cuando el sitio esté publicado; en otro caso `false` |
| `PUBLIC_GIANNA_API_BASE` | Origen HTTPS de la API, por ejemplo `https://gianna.tu-dominio.uy` |

Son valores públicos integrados en el HTML durante la compilación; no incluir claves ni credenciales. Cambiar un argumento requiere reconstruir la imagen.

En el backend, establecer `CORS_ORIGINS` con el origen HTTPS exacto del portal. El dominio público del backend debe apuntar al servicio `api` en el puerto interno `8000`; Coolify gestiona HTTPS y el proxy. Consultar `backend/docs/COOLIFY.md` en el repositorio backend para generar y configurar los secretos.
