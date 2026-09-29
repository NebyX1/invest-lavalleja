# Integración en el portal Astro existente

Este componente es independiente del panel Flask. No sustituye el sitio ni altera su buscador Fuse.js.

Copiar `GiannaChat.tsx` y `gianna-chat.css` juntos a `src/components/islands/` del portal. En la página o sección elegida:

```astro
---
import GiannaChat from '../components/islands/GiannaChat';
const apiBase = import.meta.env.PUBLIC_GIANNA_API_BASE;
---
{apiBase && <GiannaChat apiBase={apiBase} client:visible />}
```

En el entorno del frontend:

```dotenv
PUBLIC_GIANNA_API_BASE=https://DOMINIO-REAL-DEL-BACKEND
```

En el backend, añadir el origen exacto del portal a `PUBLIC_ORIGINS`. Si el portal utiliza una política CSP, su directiva `connect-src` debe permitir ese dominio. Nunca pasar `OLLAMA_API_KEY` al frontend ni usar un nombre `PUBLIC_` para ese secreto.

La instancia conserva la conversación visible solo en memoria mientras está montada. Astro puede desmontarla al navegar; esto es deliberado y evita persistir información del inversor en localStorage. El servidor conserva solo los últimos cuatro mensajes como contexto cifrado hasta la expiración configurada. Borrar conversación elimina ese contexto del servidor y rompe su vinculación con la analítica.

El componente usa React y TypeScript, que ya forman parte del portal. No añade dependencia de un SDK de IA ni renderiza HTML producido por el modelo. Las referencias se muestran mediante componentes de texto y enlaces HTTP/HTTPS validados.

La integración no fue aplicada al repositorio remoto ni se ejecutó su build de Astro en esta entrega. Verificar rutas de importación, CSP y comportamiento de navegación en el proyecto real.
