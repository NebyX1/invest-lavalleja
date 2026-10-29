# Invest Lavalleja

Invest Lavalleja es un portal de información para inversores interesados en el departamento de Lavalleja (Uruguay). Reúne zonas, sectores, datos, casos, pasos y preguntas frecuentes, y tiene un asistente conversacional llamado **Gianna Invest** que responde preguntas usando solo la base de conocimiento del proyecto.

El repositorio tiene dos partes que trabajan juntas:

- **Portal web** (raíz del repositorio): el sitio que ve el inversor. Genera las páginas con Astro y usa React solo para las herramientas interactivas, como el buscador, el mapa, el dossier y el chat.
- **Backend de Gianna** (carpeta `backend/`): el servicio que recibe las preguntas, busca en la base de conocimiento y redacta las respuestas con sus fuentes.

## Qué es Gianna Invest

Gianna no es un buscador de palabras ni una lista de respuestas fijas. Es un **agente con herramientas** que entiende lo que se le pregunta, recuerda lo conversado en el hilo y responde solo con lo que encuentra en la guía de conocimiento del portal. Si la guía no cubre algo, lo dice y aporta lo documentado que sí aplica (zonas, condiciones, trámites, qué validar).

Cuando un inversor escribe una pregunta, ocurre lo siguiente:

```text
pregunta ─► seguridad determinista ─► (acusaciones, insultos, delitos: respuesta fija, sin modelo)
   │
   ▼
búsqueda híbrida inicial: vectores (Granite) + palabras clave (BM25 español), fusión RRF, ≈60 ms
   │      un seguimiento corto ("¿y en Varela?") se busca junto con la pregunta anterior
   ▼
el modelo lee la evidencia numerada y, si hace falta, usa sus herramientas (hasta 4 pasos):
   ├─ buscar_en_la_guia(consulta, zonas?, tipo?)
   └─ ver_ficha(identificadores del mapa de la guía)
   ▼
respuesta breve con citas [n] ─► el servidor descarta citas inexistentes, renumera y adjunta fuentes
   │
   └─ si el proveedor falla: respuesta degradada con las fichas más relacionadas
```

1. **Recibe el mensaje junto con el historial cifrado de la sesión.**
2. **Pasa por la compuerta de seguridad**, que no depende del modelo.
3. **Busca en la guía.** Combina significado (embeddings) y palabras clave (BM25) y usa solo registros públicos y aprobados. La guía está organizada en fichas completas con una cabecera (título, tema, sección, zonas).
4. **Razona con herramientas.** El modelo ve un mapa de toda la guía, puede buscar de nuevo o leer fichas completas, y nunca afirma que algo no está sin haberlo mirado.
5. **Redacta con citas.** Respeta el nivel de evidencia de cada ficha (dato documentado, hipótesis, ejemplo didáctico), compara zonas u oportunidades con criterios documentados y no declara una opción como «la mejor».
6. **Valida antes de mostrar.** Las citas `[n]` se comprueban contra lo realmente recuperado y los códigos internos se traducen a nombres.

Gianna no inventa cifras, predios, beneficios fiscales, contactos ni disponibilidad, y no da asesoramiento legal, fiscal o financiero definitivo. Una cita válida no garantiza que la afirmación sea correcta: las respuestas deben contrastarse con sus fuentes.

### Tecnologías

| Parte | Tecnología | Para qué sirve |
|---|---|---|
| Portal | Astro, React, TypeScript | Páginas estáticas con islas interactivas |
| Buscador y explorador | Fuse.js, SVG del mapa | Búsqueda global y mapa de localidades |
| Validación de datos | Zod | Comprueba el estado guardado en el navegador |
| Backend | Python 3, Flask, Gunicorn | API y panel de administración |
| Base de datos | MariaDB | Documentos, versiones, aprobaciones, sesiones y puntero activo |
| Búsqueda | LanceDB (coseno exacto + BM25 español, fusión RRF) | Índice de fichas por significado y por palabras |
| Embeddings | Granite 97M multilingüe R2 (`ibm-granite/granite-embedding-97m-multilingual-r2`), ONNX cuantizado en CPU | Convierte textos en vectores de 384 dimensiones |
| Reranker | mMARCO MiniLM (ONNX CPU), solo laboratorio | No está en el camino de la consulta: no mejoró los aciertos y costaba ~5 s |
| Agente | Bucle propio con herramientas (`services/agent.py`) | Búsqueda, lectura de fichas, citas validadas y degradación sin proveedor |
| Modelo generativo | DeepSeek vía Ollama Cloud (API nativa con herramientas), con modelo alternativo | Redacta la respuesta |
| Pruebas | pytest, Vitest, ESLint, Playwright, axe | Backend, unidades, estilo y flujos de punta a punta |
| Despliegue local | Docker Compose o `scripts/run_local.py` | Levanta la API y conserva LanceDB; MariaDB se configura mediante su URL |

### Estructura

- `src/`: portal Astro, componentes React y estilos.
- `src/data/`: catálogo versionado y manifiesto editorial de las páginas.
- `backend/gianna/`: servicios de Gianna (agente, recuperación, prompts, seguridad, panel web).
- `backend/docs/RAG_ENGINE.md`: arquitectura de la base de conocimiento y del flujo; `backend/docs/AGENT_DESIGN.md`: política de respuesta.
- `backend/evals/` y `backend/scripts/evaluate_*.py`: conjuntos de evaluación de recuperación y de conversaciones.
- `better-rag/`: documento de conocimiento sectorial, su versión consolidada y `tools/restructure.py`, que arma las fichas.
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

Abrir `http://localhost:4321/gianna/`. Sin Docker (por ejemplo en Windows) se puede levantar la API con `python scripts/run_local.py --port 8001 --human-test` desde `backend/`, usando `PUBLIC_GIANNA_API_BASE=http://localhost:8001`. Para detener la API local, usar `docker compose -f compose.yaml -f compose.local.yaml stop` desde `backend/`. El despliegue de producción usa únicamente `compose.yaml`; más detalle en [backend/README.md](backend/README.md).

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

- [Motor RAG de Gianna](backend/docs/RAG_ENGINE.md): arquitectura, flujo de una consulta, base de conocimiento y mediciones.
- [Diseño del agente](backend/docs/AGENT_DESIGN.md): política de respuesta, herramientas y citas.
- [Validación del agente](backend/reports/VALIDACION.md): resultados reales y límites.
- [Backend de Gianna](backend/README.md): despliegue, panel, bases de conocimiento y pruebas.
- [Plan e inventario](docs/IMPLEMENTATION_PLAN.md)
- [Reporte de pruebas y limitaciones](docs/TEST_REPORT.md)
- [Normas del proyecto](AGENTS.md)
