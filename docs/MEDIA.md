# Mantenimiento de imágenes

## Archivos activos

Los tres banners son WebP de **1600 × 900 px (16:9)**:

- `public/media/block-banners/agro-conceptual.webp`
- `public/media/block-banners/hospitalidad-conceptual.webp`
- `public/media/block-banners/serrano-conceptual.webp`

El mapa está en `public/media/map/Lavalleja-Map.svg`. Su contenido, puntos y `viewBox="0 0 713 779"` no cambiaron. No se adapta el mapa a 16:9.

Para cambiar un banner, reemplazá el archivo conservando nombre, formato y dimensiones. No hay que editar cada página. Los consumidores usan las nuevas rutas en `src/data/pages.json`, `src/layouts/SiteLayout.astro` (imagen social) y `src/components/islands/Explorer.tsx` (mapa). `object-fit: cover` mantiene el encuadre adaptable de los bloques sin deformar los archivos.

`scripts/extract-reference.mjs` transforma las rutas y las dimensiones al extraer páginas y preserva los banners editados. Si falta alguno, interrumpe antes de escribir datos, en lugar de restaurar una franja panorámica bajo un nombre 16:9. La extracción sigue siendo una operación de reconstrucción editorial: revisar sus cambios antes de incorporarlos.

## Procedencia y edición · 19/10/2026

Se usó la habilidad `imagegen` y la herramienta integrada de edición de imágenes, una llamada por banner. Se ampliaron cielo y primer plano de las imágenes existentes para mantener su escena conceptual sin estirar la franja original. Los PNG resultantes se exportaron a WebP de 1600 × 900, calidad 86. La normalización final ajusta menos de un píxel de proporción antes de reducir; no se amplió artificialmente la resolución.

Siguen siendo ilustraciones conceptuales: no documentan instalaciones reales, propiedades disponibles ni una localización comprobada. Se conservan los avisos editoriales y textos alternativos. El HTML de referencia no se modificó y conserva los originales incrustados; también están recuperables en Git. Las copias originales retiradas de `public/media/` se conservaron en `C:/Users/Nebyx/.codex/asset-backups/invest-lavalleja/2026-10-19-original-banners/`.

### Prompts usados

Prompt común de las tres ediciones (se reemplaza `{scene}` por la escena correspondiente):

```text
Use case: precise-object-edit. Asset type: conceptual website block banner, landscape 16:9, ideally 1920 x 1080.
Input image 1 is the EDIT TARGET. Reframe and naturally extend this extremely wide panorama into a full 16:9 landscape image. Preserve the original scene identity: {scene}. Keep its naturalistic conceptual illustration style, colors, lighting, principal subjects and geographical character. Expand sky and foreground with seamless coherent outpainting and only modest reframing; do not stretch or squash, and do not reduce it to a narrow strip inside a canvas. Compose a beautiful full-bleed 16:9 scene that works as a website banner. The place/buildings are conceptual, not a documentary photograph or an actual property for sale. Do not add landmarks, people, logos, labels, frames or text. Exactly one image; no collage.
```

- Agro: `agricultural countryside with grain silos, low agricultural buildings, cattle and fields, low rolling hills, soft golden daylight`
- Hospitalidad: `the same fictional rural stone-and-glass lodge at sunset, grassy rocky foreground and gently rolling Uruguayan hills`
- Serrano: `the same low rocky Uruguayan hill and winding rural road, warm setting sun and native grassland and trees`
