# Invest Lavalleja — inventario y plan de implementación

## Inventario inicial (2026-09-20)

- `Invest_Lavalleja_Vista_Previa.html`: referencia navegable autocontenida. Incluye los bloques JSON `catalog-data`, `pages-data` y `asset-data`, además de contenido y estilos de la referencia.
- `Invest_Lavalleja_Diseno_y_Arquitectura.md`: especificación visual, editorial, técnica, de accesibilidad y estado de validación.
- `Invest_Lavalleja_Home_Completa.png`: captura desktop de la portada completa, 1440 px de ancho.
- `Invest_Lavalleja_Diseno_Movil.png`: captura móvil de la portada, 390 px de ancho.
- No se encontró `Invest_Lavalleja_Diseno_Desktop.png` ni `Invest_Lavalleja_Web_Astro_React.zip` en la raíz actual.
- No existía código fuente, `package.json`, `AGENTS.md` ni lockfile; se crea una implementación Astro nueva sin sobrescribir los materiales de referencia.

## Plan ejecutable

1. Extraer con `JSON.parse` los datos y recursos embebidos del HTML a `src/data/` y `public/media` / `public/documentos`, validando rutas de destino.
2. Crear la base Astro + React + TypeScript estricto + Tailwind, configuración de preproducción noindex, sitemap y scripts reproducibles.
3. Construir layout, navegación flotante, identidad visual, responsive y view transitions con contenido HTML generado por Astro.
4. Modelar rutas reales para portada, páginas editoriales, sectores, zonas, historias, recursos, fuentes, contacto, 404 y manifiesto de rutas.
5. Implementar islas React acotadas: búsqueda global, explorador territorial, dossier, asistente de proyecto y filtros de recursos.
6. Implementar stores compartidos con nanostores, persistencia validada y exportaciones locales.
7. Añadir accesibilidad, SEO, lifecycle de navegación, prefetch por intención y limpieza idempotente.
8. Añadir pruebas unitarias, integración/E2E con Playwright y axe; ejecutar check, lint, test, build, preview y verificación de navegación.
9. Revisar visualmente en 390 / 768 / 1440 px mediante navegador servido por HTTP, corregir regresiones y documentar resultados, capturas y limitaciones reales.

## Decisiones de alcance

- Se conserva el catálogo y el lenguaje de la referencia; no se inventan inmuebles, beneficios, contactos ni puntuaciones.
- El HTML editorial se renderiza en Astro. React se usa sólo en herramientas interactivas.
- El atlas usa un esquema territorial, no coordenadas geográficas inventadas.
- El dossier exporta Markdown y ofrece una vista de impresión del navegador; no se etiqueta HTML como PDF.
- El sitio queda en modo preproducción por defecto (`noindex` y robots restrictivo) hasta configurar un dominio real.

## Estado de cierre (2026-09-21)

- Implementación completa en Astro + React con 30 rutas, layout compartido, navegación cliente, prefetch por hover y responsive validado en 390 / 1440 px.
- Datos y cinco assets binarios extraídos de la referencia hacia `src/data/`, `public/media/` y `public/documentos/`.
- Islas terminadas: búsqueda global, explorador, guardado de zonas, dossier, wizard de proyecto y búsqueda de recursos.
- Verificación final: check, lint, unit tests, build y 12 pruebas E2E en verde. Las capturas están en `reports/captures/`; el detalle está en [TEST_REPORT.md](TEST_REPORT.md).
