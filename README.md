# Invest Lavalleja

Invest Lavalleja es un portal de información para inversores interesados en el departamento de Lavalleja (Uruguay). Reúne zonas, sectores, datos, casos, pasos y preguntas frecuentes, y tiene un asistente conversacional llamado **Gianna Invest** que responde preguntas usando solo la base de conocimiento del proyecto.

El repositorio tiene dos partes que trabajan juntas:

- **Portal web** (raíz del repositorio): el sitio que ve el inversor. Genera las páginas con Astro y usa React solo para las herramientas interactivas, como el buscador, el mapa, el dossier y el chat.
- **Backend de Gianna** (carpeta `backend/`): el servicio que recibe las preguntas, busca en la base de conocimiento y redacta las respuestas con sus fuentes.

## Qué es Gianna Invest

Gianna no es un buscador de palabras ni una lista de respuestas fijas. Es un agente de asesoría informativa: entiende lo que se le pregunta, recuerda lo que ya se conversó en el mismo hilo y responde con lo que encuentra en su base. Si la base no tiene información sobre algo, lo dice.

Cuando un inversor escribe una pregunta, ocurre lo siguiente:

1. **Recibe el mensaje junto con la memoria del hilo.** Gianna guarda, dentro de la sesión, lo que el inversor ya dijo: la zona que le interesa, el tipo de proyecto, lo que ya se respondió.
2. **Interpreta qué necesita.** Un modelo de lenguaje lee el mensaje y produce un plan: qué tipo de pedido es (dónde ubicarse, oportunidades, requisitos, comparar opciones, próximos pasos), qué necesita realmente la persona y qué buscar en la base. Por ejemplo, «quiero poner un boliche» se entiende como una pregunta sobre *dónde* y *qué ofrece cada zona*, no como una consulta de trámites.
3. **Busca en la base de conocimiento.** Combina dos tipos de búsqueda: por significado (embeddings) y por palabras clave (BM25), usando las consultas que armó el intérprete.
4. **Ordena los resultados.** Un reranker puntúa qué tan relacionado está cada fragmento con la necesidad de la persona, y ese orden se combina con el de las búsquedas. Se usan solo registros públicos y aprobados.
5. **Redacta la respuesta.** Un agente de respuesta arma el texto con la evidencia encontrada, trata al inversor como alguien que sabe lo que quiere y compara las opciones cuando hay varias. Si el pedido es puntual (un requisito, un dato), puede hacer una segunda lectura de la base.
6. **Verifica antes de mostrar.** La respuesta debe indicar si la base alcanza o no, y citar sus fuentes. El servidor descarta las fuentes que no tienen relación con el texto y nunca muestra una respuesta sin fuente.
7. **Muestra la respuesta, sus fuentes y la memoria actualizada.** Las fuentes aparecen aparte en la interfaz.

Gianna no inventa cifras, predios, beneficios fiscales, contactos ni disponibilidad, y no da asesoramiento legal, fiscal o financiero definitivo.

### Tecnologías

| Parte | Tecnología | Para qué sirve |
|---|---|---|
| Portal | Astro, React, TypeScript | Páginas estáticas con islas interactivas |
| Buscador y explorador | Fuse.js, SVG del mapa | Búsqueda global y mapa de localidades |
| Validación de datos | Zod | Comprueba el estado guardado en el navegador |
| Backend | Python 3, Flask, Gunicorn | API y panel de administración |
| Base de datos | MariaDB | Documentos, versiones, aprobaciones, sesiones y puntero activo |
| Búsqueda vectorial | LanceDB | Índice de fragmentos por significado |
| Embeddings | Bekko (`hotchpotch/bekko-embedding-v1-a8m`) en OpenVINO CPU | Convierte textos en vectores |
| Reranker | Horizon (`Horizon-Labs/multilingual-reranker-small`) en ONNX CPU | Ordena los fragmentos por relevancia |
| Agente | PydanticAI | Intérprete de turnos, agente de respuesta y memoria del hilo |
| Modelo generativo | DeepSeek vía Ollama Cloud (API compatible con OpenAI) | Interpreta, redacta y decide si hay respuesta |
| Pruebas | pytest, Vitest, ESLint, Playwright, axe | Backend, unidades, estilo y flujos de punta a punta |
| Despliegue local | Docker Compose | Levanta la API y conserva LanceDB; MariaDB se configura mediante su URL |

### Estructura

- `src/`: portal Astro, componentes React y estilos.
- `src/data/`: catálogo versionado y manifiesto editorial de las páginas.
- `backend/gianna/`: servicios de Gianna (búsqueda, agentes, memoria, validación, panel web).
- `backend/docs/RAG_ENGINE.md`: arquitectura detallada del motor de búsqueda y del agente.
- `better-rag/`: documento de conocimiento sectorial y su versión consolidada para alimentar el RAG.
- `public/`: recursos estáticos (imágenes, mapa, PDFs editoriales).

## Despliegue con Coolify

El portal y la API son recursos separados en Coolify. El portal se construye desde este repositorio con el `Dockerfile` de la raíz y escucha en el puerto interno `80`; configurar los argumentos de construcción indicados en [docs/COOLIFY.md](docs/COOLIFY.md). La API se despliega desde el repositorio independiente `invest-lavalleja-backend`; seguir allí las instrucciones de [despliegue de Coolify](https://github.com/IntendenciaDeLavalleja/invest-lavalleja-backend/blob/main/docs/COOLIFY.md).

## Puesta en marcha de Gianna

Gianna necesita el backend en Docker, una base MariaDB dedicada y una clave de Ollama Cloud. Cada instalación utiliza una sola `DATABASE_URL`. Para desarrollo local, desde `backend/`:

```powershell
python scripts/setup_env.py --local
# Editar .env: completar DATABASE_URL y OLLAMA_API_KEY.
docker compose -f compose.yaml -f compose.local.yaml up -d --build
docker compose -f compose.yaml -f compose.local.yaml run --rm api python -m scripts.prepare_models
docker compose -f compose.yaml -f compose.local.yaml exec api flask --app wsgi create-admin
```

Abrir `http://localhost:8000/admin/login` para cargar, revisar, indexar y publicar la base de conocimiento desde el panel.

Esperar a que `http://127.0.0.1:8000/api/config` responda `available: true`. Para que el portal se conecte, `.env.local` en la raíz debe contener `PUBLIC_GIANNA_API_BASE=http://localhost:8000`. Luego:

```powershell
npm install
npm run dev
```

Abrir `http://localhost:4321/gianna/`. Para detener la API local, usar `docker compose -f compose.yaml -f compose.local.yaml stop` desde `backend/`. El despliegue de producción usa únicamente `compose.yaml`; más detalle en [backend/README.md](backend/README.md).

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
- `public/media/block-banners/`: banners conceptuales WebP en 16:9 (1600 × 900), ampliados a partir de la referencia.
- `public/media/map/`: mapa SVG del departamento y sus localidades.
- `public/documentos/`: PDFs editoriales locales.
- `scripts/extract-reference.mjs`: extracción reproducible con `JSON.parse`; valida que los destinos permanezcan dentro del proyecto.

Para actualizar la referencia, ejecutar el extractor y revisar el diff de los JSON y los assets antes de compilar.

Los banners se reemplazan conservando sus nombres y proporción; el extractor preserva estas versiones en 16:9. Las imágenes son conceptuales, no fotografías documentales. Ubicaciones, proceso y prompts: [Mantenimiento de imágenes](docs/MEDIA.md).

## Interacciones

El buscador global usa Fuse.js. El explorador territorial muestra el mapa SVG con seis localidades seleccionables vinculadas a perfiles editoriales; los siete perfiles también se pueden elegir desde la lista. El mapa conserva su proporción y la vista se apila en pantallas estrechas. El dossier permite guardar hasta tres zonas, compararlas en tres perspectivas, imprimir y descargar Markdown. El wizard conserva sus respuestas durante la sesión y puede descargar un resumen Markdown. El estado almacenado se valida con Zod.

Las advertencias editoriales distinguen datos de fuente, interpretación comercial y preguntas aún no verificadas; no se inventan predios, beneficios fiscales, contactos ni disponibilidad.

## Documentación adicional

- [Motor RAG y agente de Gianna](backend/docs/RAG_ENGINE.md): arquitectura, modelos y contrato de respuesta.
- [Backend de Gianna](backend/README.md): despliegue, panel, bases de conocimiento y pruebas.
- [Plan e inventario](docs/IMPLEMENTATION_PLAN.md)
- [Reporte de pruebas y limitaciones](docs/TEST_REPORT.md)
- [Normas del proyecto](AGENTS.md)
