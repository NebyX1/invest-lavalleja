# Informe de validación de la entrega

**Actualización local · 29/09/2026. No desplegada en producción.**

## DeepSeek, diálogo natural y evaluación adversarial · 29/09/2026

La captura mostraba falsos rechazos de consultas sobre una actividad sensible y la frase impersonal «fuera del alcance de Gianna». Se seleccionó `deepseek-v4.1-flash` del catálogo real de Ollama en la pila humana local; también se actualizó el selector de modelo de la pila operativa local, que **sigue sin base pública activa**. `.env.example` usa el mismo modelo para instalaciones nuevas. El código no se desplegó a Coolify ni a GitHub.

El harness mantiene barreras locales para acusaciones directas y pedidos inequívocos de daño o fraude. Las burlas, propuestas no coercitivas y preguntas generales ahora reciben respuesta conversacional generada, sin RAG ni plantilla de «fuera del alcance». La ruta documental permite investigar sectores sensibles sin clasificarlos automáticamente como ilegales; si falta evidencia, identifica datos o requisitos por verificar sin dar consejo jurídico. La conversación recuerda el último intercambio para admitir correcciones. Una guarda evita presentar como hecho una conclusión legal específica producida sin documentos. Las respuestas documentales usan citas y tienen un solo intento de reparación si faltan referencias válidas. Se comprobó que DeepSeek Cloud acepta `think: false`, que reduce salidas vacías por agotamiento del presupuesto; otros modelos mantienen `think: low`.

Verificación final: **106/106 pruebas Python**, **12/12 pruebas E2E de Gianna** en Chromium escritorio/móvil (incluyendo el caso sensible), `npm run check` sin errores, `npm run lint` y `npm run build` correctos. La pila Docker de prueba respondió por HTTP al ciclo CAPTCHA → sesión → chiste → borrado con `conversation` y cero citas. El script `scripts/evaluate_dialogue.py`, ejecutado contra **DeepSeek, E5 y Qdrant reales** en el entorno aislado, terminó **16/16** en su corrida final. Cubrió dos chistes, crítica, dos propuestas personales, conocimiento general, clima, dos preguntas de negocio sensible con corrección, explotación, falsificación, privacidad, turismo con seguimiento y una inyección para forzar exoneración sin fuentes. Fallos encontrados en corridas previas (salidas vacías, falso rechazo fiscal, clasificación errónea de propuesta y afirmación jurídica sin respaldo) se corrigieron y se añadieron regresiones.

Los 16/16 verifican rutas y reglas observables, **no** calidad semántica exhaustiva, verdad jurídica/financiera ni que cada cita respalde cada frase. El modelo puede variar entre ejecuciones y todavía debe pasar revisión humana de los 12 casos editoriales, vigencia de fuentes, evaluación de privacidad y costos. La base técnica de prueba sigue sin aprobación editorial; ninguna de estas pruebas autoriza publicación institucional.

## Harness de decisiones y respuestas seguras · 29/09/2026

La captura más reciente mostró otra falla: una acusación sobre una funcionaria recibió el texto genérico de “evidencia insuficiente”. Ahora `AgentHarness` controla el paso previo al RAG. Una barrera local intercepta acusaciones sobre personas, insultos directos y pedidos explícitos de ilícitos; para otros mensajes, `gpt-oss:20b` propone una ruta entre conversación, RAG, desescalada, acusación, rechazo y fuera de alcance. El servidor valida la decisión: solo `rag` abre Qdrant y las rutas sensibles usan respuestas controladas, sin citas ni repetición de acusaciones. Si la salida de clasificación no es JSON válido, no se consulta el índice.

Se detectó y reprodujo un segundo fallo: con `num_predict=160`, el modelo de razonamiento podía consumir todo el presupuesto en `thinking` y devolver `content` vacío. Una petición real mostró `done_reason=length` y 160 tokens evaluados sin respuesta. La petición de clasificación con `think: low` y presupuesto mayor respondió correctamente; se fijó `think: low` y `num_predict=320` para clasificar. La conversación simple también usa razonamiento bajo. No se envía un esquema `format` a Ollama Cloud porque su documentación indica que esa función no está disponible allí; la validación queda en el servidor.

Verificación: **84 pruebas Python** y **12/12 E2E de Gianna** en escritorio y móvil. En la API real, la frase de la captura produjo `allegation` sin citas ni llamada a búsqueda/modelo; un insulto produjo `deescalate`; un pedido de falsificar permisos produjo `refuse`. Una secuencia real de cuatro turnos clasificó clima como `out_of_scope` y conversación general como `conversation` (ambos sin citas), y respondió a un proyecto turístico en Minas más “¿Y los permisos?” como `answered` con cinco citas en cada caso. Chromium móvil mostró la respuesta segura ante la acusación y la desescalada posterior, sin desborde horizontal. La exactitud de las respuestas documentales y la cobertura de casos adversariales no están certificadas; requieren evaluación humana adicional antes de publicar.

## Habilitación para testing humano local · 29/09/2026

### Corrección del flujo conversacional

La primera versión aplicaba recuperación documental y exigencia de citas a **todos** los mensajes. Un simple “Hola, ¿cómo estás?” terminaba en `citation_guard_failed` con fragmentos ajenos a la intención: era un defecto funcional, no una falta de datos. Se separó la conversación social de las consultas a la guía. El modo social usa Ollama con instrucciones de no afirmar datos de inversión sin fuentes, devuelve `status: conversation`, cero citas y respuesta breve; las preguntas del dominio siguen el índice y la guarda de citas. Las preguntas externas sobre hechos no verificados reciben un límite explícito, sin documentos irrelevantes. El hilo cifrado ahora conserva hasta seis intercambios, con el modo de la respuesta para interpretar seguimientos breves.

Regresión anterior: 74 pruebas Python, 10/10 pruebas E2E de Gianna, `npm run check`, `npm run lint`, cinco pruebas unitarias y `npm run build` aprobaron. Chromium contra la API/Ollama reales recorrió en una sesión “Hola, ¿cómo estás?” y “¿Qué podés hacer?” (cero citas), “¿Qué oportunidades de inversión hay en Lavalleja?” y “¿Y qué debo verificar antes de avanzar?” (cinco citas cada una), borró la conversación y comprobó ausencia de desborde a 320, 390, 768 y 1366 px. El clasificador inicial se había eliminado por respuestas vacías; el nuevo harness lo reintroduce con presupuesto y razonamiento ajustados, más validación y barreras locales. La calidad factual de las respuestas RAG sigue pendiente de revisión humana.

La captura del usuario correspondía a `available: false`: la API operativa no tenía una versión activa, por lo que React deshabilitaba la consulta. Se levantó una segunda pila `gianna-invest-human-test` en `127.0.0.1:8001`, con volúmenes SQLite y Qdrant propios y bandera de prueba limitada a hosts/orígenes loopback. El corpus se cargó ahí: **196 registros públicos indexados en 196 chunks, 75 internos excluidos**. Se activó exclusivamente esa versión técnica, marcada como no aprobada editorialmente en la interfaz. La API operativa en `127.0.0.1:8000` continúa con `available: false`.

Verificación real: `/api/config` de prueba respondió `enabled: true`, `available: true`, `test_mode: true`; CAPTCHA → sesión anónima → consulta Ollama devolvió `answered` con cinco citas → borrado respondió `deleted: true`. Chromium recorrió el mismo flujo desde `http://localhost:4321/gianna/`, mostró cinco citas y permitió borrar y preparar una nueva pregunta. Sin desborde horizontal a 320, 390, 768 y 1366 px. La correspondencia factual de citas y la vigencia de la guía siguen requiriendo revisión humana; este resultado solo habilita esa revisión, no autoriza uso público o productivo.

| Misión | Etapa / verificación | Resultado |
| --- | --- | --- |
| Arquitectura y Coolify | Imagen construida; Compose local levantó API + Qdrant, `/health/live` y `/health/ready` sanos; reinicio conservó SQLite | Cumplido localmente; Coolify remoto pendiente |
| Seguridad | CAPTCHA de un uso y 10 min en login y sesiones públicas; CORS y rechazo sin base activa comprobados por HTTP; TOTP y correo soportados | Cumplido en pruebas; SMTP real pendiente |
| Base documental | JSON canónico importado: 271 registros, 50 fuentes, 196 públicos, 75 internos; 0 aprobados en la base operativa | Borrador cargado; revisión editorial pendiente |
| Vectorización y RAG | E5 multilingüe/CPU + BM25 + Qdrant reales: 196 chunks públicos en base técnica aislada; 75 internos excluidos; Ollama respondió con 5 citas | Circuito técnico cumplido; sin publicación |
| Evaluación | 62/62 preguntas de recuperación con al menos un ID esperado en top 8; 84 pruebas Python; Astro `verify` previo: 5 unitarias y 27 de navegador aprobadas, 1 captura omitida; Gianna actual 12/12 E2E | Cumplido para estos tests; revisión factual humana pendiente |
| Dependencias | `cryptography` actualizada a 50.0.1; `pip-audit -r requirements.txt` y `npm audit --omit=dev --audit-level=high` sin vulnerabilidades conocidas en la consulta local | Cumplido localmente; repetir en CI e imagen final |
| Frontend | Página Gianna, enlaces, isla React, CAPTCHA, citas, feedback, borrado y diseño adaptable | Habilitado en prueba humana local aislada; URL pública y aprobación editorial pendientes |

El 62/62 es una prueba de recuperación generada del propio corpus, no una medida independiente de calidad factual ni una certificación del modelo. Ollama respondió a una consulta de control con estado `answered` y cinco citas estructuralmente válidas; la correspondencia semántica de cada cita requiere revisión humana. Una pregunta adversarial sobre “5 puntos = 5 %” mostró que el modelo puede añadir recomendaciones sin cita; se endureció la guarda por párrafo y la repetición terminó en `citation_guard_failed`, mostrando fragmentos en lugar de esa respuesta. Esto reduce exposición a afirmaciones sin respaldo, pero no demuestra exactitud jurídica o financiera. La base del smoke técnico original no tiene puntero activo; la nueva pila aislada para testing humano sí lo tiene, sin alterar la base operativa, que conserva `active_knowledge=NULL` hasta aprobación y publicación explícitas.

Una auditoría local de `requirements.txt` detectó vulnerabilidades conocidas en `cryptography==46.0.4`. Se actualizó a `50.0.1` y una segunda ejecución de `pip-audit -r requirements.txt` informó **ninguna vulnerabilidad conocida** al momento de la consulta. Esto no sustituye un SBOM ni la auditoría de la imagen Linux/transitivas en CI.

Se instaló el backend en un entorno virtual Python 3.13, se fijó `tzdata` solo para Windows, se corrigió la lectura UTF-8 del corpus, y se probó la imagen Linux Python 3.12. El modelo E5 se resolvió en la revisión `614241f622f53c4eeff9890bdc4f31cfecc418b3`, con dimensión 384 y huella de perfil iniciada en `3a30c10f00af`; esa revisión quedó fijada en el `.env` local ignorado por Git. El token de Ollama permanece únicamente en ese archivo/entorno y debe rotarse antes de producción por haber sido compartido en la conversación.

Pendiente para apertura institucional: revisar/aprobar los 196 registros públicos y verificar vigencia de sus 50 fuentes; completar las 12 situaciones de revisión humana, pruebas SMTP reales, auditoría de dependencias en CI, evaluación de privacidad y costos, dominio HTTPS/orígenes de producción, configuración de `PUBLIC_GIANNA_API_BASE` al construir Astro y despliegue Coolify. No hubo push ni despliegue remoto.

Tras endurecer la guarda de citas y la validación de URL pública, se repitieron las 66 pruebas Python y las ocho pruebas de navegador específicas de Gianna; todas aprobaron. La página local `/gianna/` y ambos contenedores respondieron correctamente al cierre de la revisión.

## Historial de la entrega RC inicial (sustituido por la actualización anterior)

**Gianna Invest 1.0.0-rc1 · 28/09/2026. No desplegada.**

### Ejecutado en el entorno inicial

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

### No ejecutado en el entorno inicial

El entorno carece de Flask, FastEmbed y ONNX Runtime y no permite completar las descargas/instalaciones externas necesarias. Por eso no se ejecutaron las nueve pruebas HTTP Flask incluidas, el modelo E5 real, Qdrant Server, las respuestas de Ollama, el build Docker, el despliegue Coolify ni mediciones de memoria/velocidad en el VPS. Tampoco hubo auditoría independiente, pip-audit de la imagen final o build completo Astro/React. El workflow de GitHub está incluido pero no se ejecutó desde esta entrega.

Las dependencias directas están fijadas; la compatibilidad del árbol transitivo debe comprobarse en el destino. No hay embeddings precalculados en el ZIP. La guía se tokenizará e indexará allí y deberá evaluarse con las 62 preguntas y 12 situaciones de revisión humana suministradas.

### Hallazgos y límites conocidos de la entrega inicial

La comprobación de referencias es estructural, no un verificador de respaldo por afirmación. El límite de contexto del proveedor está expresado en caracteres y tokens de salida, no como un tokenizador exacto del LLM remoto. El presupuesto de solicitudes no mide costo monetario. La proyección PCA es exploratoria. La cola y SQLite están diseñadas para una sola instancia. El borrado de una base retirada debe realizarse sin consultas en vuelo: no se implementaron leases de lectura distribuidos. La personalización visual completa requiere editar CSS/plantillas.

Antes de uso institucional, seguir docs/PUESTA_EN_MARCHA.md, registrar resultados reales y resolver los problemas que aparezcan. La etiqueta RC es deliberada: el código está entregado, la puesta en producción no está certificada.
