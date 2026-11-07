# Invest Lavalleja

## Arquitectura

- Astro genera rutas, layouts, contenido editorial, SEO y assets.
- React se limita a islas interactivas hidratadas.
- `src/data/` contiene el catálogo versionado y el manifiesto editorial.
- `src/stores/` contiene estado compartido y persistencia validada.
- `public/media` y `public/documentos` contienen recursos locales extraídos de la referencia.

## Comandos

```powershell
npm run dev
npm run build
npm run preview
npm run check
npm run lint
npm run test
npm run test:e2e
npm run test:e2e:preview
npm run verify
.\run.ps1
.\run.ps1 -Mode Preview
```

## Reglas del proyecto

- El repositorio central es `NebyX1/invest-lavalleja`; la rama de publicación es `main` y el backend vive en `backend/`. Verificar el destino del remoto antes de publicar; los repositorios independientes de backend/frontend tienen su propio historial.
- No modificar ni sobrescribir los archivos de referencia.
- No inventar cifras, oportunidades, beneficios fiscales, contactos o disponibilidad.
- Mantener el contenido editorial accesible sin JavaScript.
- Usar enlaces Astro reales para navegación interna y reservar React para interacciones.
- Mantener `prefers-reduced-motion`, foco visible y alternativas de lista.
- No usar comandos destructivos ni agregar una SPA/router paralelo.
