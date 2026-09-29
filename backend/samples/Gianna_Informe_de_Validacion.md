# Informe de validación de la entrega

**Gianna Invest 1.0.0-rc1 · 28/09/2026. No desplegada.**

## Ejecutado en este entorno

- 48 pruebas de lógica y componentes aprobadas, con resultado final `48 passed, 1 skipped in 1.41s`. La omisión corresponde al módulo HTTP Flask, no a un fallo que se haya ocultado como aprobación.
- Pruebas de MFA incluyen seis vectores RFC 6238, anti-reutilización, límite de intentos, expiración, códigos de recuperación de un uso, sesiones, desactivación y revocación. Los servicios de correo se sustituyen por dobles de prueba.
- Validación y conversión del DOCX real: 271 registros, 196 públicos, 75 internos, 50 fuentes, 16 oportunidades y todos los bloques contabilizados. No se verificó externamente la vigencia de sus afirmaciones.
- Pruebas de snapshots inmutables, revisión editorial, aislamiento público, invalidación de aprobación tras cambios, publicación, retorno y protección del borrado activo.
- Pruebas de contratos Qdrant/Ollama con HTTPX MockTransport. Pruebas de construcción, caché, reintento e interrupción con embeddings deterministas de prueba, NO con E5 real.
- 21 plantillas Jinja compiladas y 19 pantallas renderizadas con StrictUndefined y datos sintéticos. Las capturas no corresponden a un servidor desplegado ni a analítica real.
- Chromium/Playwright comprobó 11 pantallas en dos anchos (1440 y 390 píxeles): 22 verificaciones estáticas, sin desbordamiento horizontal del documento detectado. Se cargó HTML/CSS local con set_content, sin navegación HTTP ni ejecución del comportamiento JavaScript.
- Python compileall y sintaxis de ambos JavaScript correctos. La isla React pasó transpileModule de TypeScript sin diagnósticos de sintaxis; no es una compilación completa del portal ni un chequeo exhaustivo de tipos.
- Compose analizado como YAML y comprobado estáticamente: dos servicios, sin puertos de producción publicados, variables explícitas. No se ejecutó Docker Compose.

Los archivos unit-tests.txt/XML, templates.json, browser-layout.json, typescript-syntax.json y validation.json registran el alcance. Ninguno acredita seguridad absoluta o exactitud factual del RAG.

## No ejecutado

El entorno carece de Flask, FastEmbed y ONNX Runtime y no permite completar las descargas/instalaciones externas necesarias. Por eso no se ejecutaron las nueve pruebas HTTP Flask incluidas, el modelo E5 real, Qdrant Server, las respuestas de Ollama, el build Docker, el despliegue Coolify ni mediciones de memoria/velocidad en el VPS. Tampoco hubo auditoría independiente, pip-audit de la imagen final o build completo Astro/React. El workflow de GitHub está incluido pero no se ejecutó desde esta entrega.

Las dependencias directas están fijadas; la compatibilidad del árbol transitivo debe comprobarse en el destino. No hay embeddings precalculados en el ZIP. La guía se tokenizará e indexará allí y deberá evaluarse con las 62 preguntas y 12 situaciones de revisión humana suministradas.

## Hallazgos y límites conocidos

La comprobación de referencias es estructural, no un verificador de respaldo por afirmación. El límite de contexto del proveedor está expresado en caracteres y tokens de salida, no como un tokenizador exacto del LLM remoto. El presupuesto de solicitudes no mide costo monetario. La proyección PCA es exploratoria. La cola y SQLite están diseñadas para una sola instancia. El borrado de una base retirada debe realizarse sin consultas en vuelo: no se implementaron leases de lectura distribuidos. La personalización visual completa requiere editar CSS/plantillas.

Antes de uso institucional, seguir docs/PUESTA_EN_MARCHA.md, registrar resultados reales y resolver los problemas que aparezcan. La etiqueta RC es deliberada: el código está entregado, la puesta en producción no está certificada.
