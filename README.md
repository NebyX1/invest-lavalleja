# Invest Lavalleja

Portal editorial de preproducción para explorar oportunidades, territorio y fuentes de Lavalleja. Está construido con Astro, React y TypeScript estricto: Astro genera las páginas y React se reserva para las herramientas interactivas.

## Desarrollo

```powershell
npm install
npm run dev
```

También se puede usar `.\run.ps1` para iniciar el modo desarrollo o `.\run.ps1 -Mode Preview` para compilar y servir una previsualización local.

## Verificación

```powershell
npm run check
npm run lint
npm run test
npm run build
npm run test:e2e
npm run test:e2e:preview
```

`npm run test:e2e` prueba Chromium y un viewport móvil contra el servidor de desarrollo. `npm run test:e2e:preview` repite la suite contra el build servido por `astro preview`. Ambas cubren el manifiesto de 30 rutas, navegación Astro sin recarga, persistencia del dossier y del wizard, búsqueda con Ctrl+K, menú móvil, PDF local y axe. Las capturas de referencia quedan en `reports/captures/` y el reporte HTML de Playwright en `reports/playwright/`.

## Configuración de preproducción

Por defecto el sitio usa `noindex` y `robots.txt` restrictivo. Para publicar con indexación explícita:

```powershell
$env:PUBLIC_SITE_URL = 'https://ejemplo.uy'
$env:PUBLIC_INDEXING = 'true'
npm run build
```

`PUBLIC_SITE_URL` habilita canonical, Open Graph y sitemap. No hay formularios ni envíos externos: el dossier se guarda en `localStorage`, el resumen del proyecto en `sessionStorage` y las exportaciones son locales.

## Contenido y assets

- `src/data/catalog.json`: sectores, zonas, datos, casos, pasos, preguntas frecuentes y fuentes.
- `src/data/pages.json`: manifiesto editorial de las 30 rutas.
- `src/data/route-manifest.json`: contrato de rutas usado por Astro y Playwright.
- `public/media/`: imágenes conceptuales extraídas de la referencia.
- `public/documentos/`: PDFs editoriales locales.
- `scripts/extract-reference.mjs`: extracción reproducible con `JSON.parse`; valida que los destinos permanezcan dentro del proyecto.

Para actualizar la referencia, ejecutar el extractor y revisar el diff de los JSON y los assets antes de compilar.

## Interacciones

El buscador global usa Fuse.js. El explorador territorial muestra el mapa SVG con seis localidades seleccionables vinculadas a perfiles editoriales; los siete perfiles también se pueden elegir desde la lista. El mapa conserva su proporción y la vista se apila en pantallas estrechas. El dossier permite guardar hasta tres zonas, compararlas en tres perspectivas, imprimir y descargar Markdown. El wizard conserva sus respuestas durante la sesión y puede descargar un resumen Markdown. El estado almacenado se valida con Zod.

Las advertencias editoriales distinguen datos de fuente, interpretación comercial y preguntas aún no verificadas; no se inventan predios, beneficios fiscales, contactos ni disponibilidad.

## Documentación adicional

- [Plan e inventario](docs/IMPLEMENTATION_PLAN.md)
- [Reporte de pruebas y limitaciones](docs/TEST_REPORT.md)
- [Normas del proyecto](AGENTS.md)
