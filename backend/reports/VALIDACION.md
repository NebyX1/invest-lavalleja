# Validación del agente RAG

**Fecha:** 29/10/2026. **Alcance:** cambios locales; sin push, despliegue ni cambios en producción. La base de prueba local no tiene revisión editorial final.

Este informe describe el código actual. El informe del diseño anterior (planificador determinista) está en [historico/VALIDACION_agente_anterior.md](historico/VALIDACION_agente_anterior.md) y no aplica.

## Diagnóstico de lo que fallaba

| Síntoma en el chat | Causa verificada | Corrección |
| --- | --- | --- |
| "El proveedor de respuestas no está disponible" | El cliente trataba igual cualquier error HTTP, timeout de 80 s, respuesta vacía o recorte de contexto; el cross-encoder sumaba ~5 s por búsqueda y había varias por consulta | Reintentos con espera, modelo alternativo, plazo total de 100 s, reranker fuera del camino, respuesta degradada con fichas en vez de error |
| "No tengo documentado un perfil de zona…" para cualquier rubro fuera del catálogo | Un planificador de palabras clave decidía abstenerse antes de que el modelo viera la evidencia | Agente con herramientas: el modelo ve la evidencia y el mapa completo de la guía y decide qué buscar |
| Respuestas pobres con evidencia fragmentada | Registros de 60–200 caracteres ("Ocupación supuesta", "2 · Contrastar mercado") recuperados sin su contexto | Fichas autosuficientes (332 → 257 registros públicos) con cabecera contextual |
| Evidencia recortada | Tope artificial de 8.000 tokens por petición | Sin tope de 8K: hasta 36.000 caracteres de evidencia por respuesta |

El modelo configurado (`deepseek-v4.1-flash:1017`) existe en el catálogo real de Ollama Cloud (`/api/tags`) y respondió en 1,4–2,7 s con y sin herramientas, con llamadas de herramientas nativas también en `glm-5.3` y `kimi-k3`.

## Qué se midió y resultados

### 1. Recuperación (51 preguntas, `evals/retrieval_gold.json`, sin llamar al modelo)

| Modo | hit@1 | hit@3 | hit@5 | hit@8 | MRR | ms por búsqueda |
| --- | --- | --- | --- | --- | --- | --- |
| **Híbrido (camino de la consulta)** | 0,745 | 0,902 | 0,922 | **0,961** | 0,830 | 60–150 |
| Híbrido + cross-encoder | 0,725 | 0,922 | 0,941 | 0,941 | 0,825 | ≈5.000 |
| Solo cross-encoder | 0,784 | 0,882 | 0,902 | 0,922 | 0,841 | ≈4.800 |

Fallos restantes del híbrido a k=8: contactos ("¿con quién hablo para permisos?"), "zona para un boliche" (no existe ficha) y riesgos. El agente los compensa reformulando.

### 2. Conversaciones contra el proveedor real (31 casos, `evals/dialogues.json`)

`python scripts/evaluate_answers.py` — tres corridas completas durante el desarrollo: **27/31, 29/31 y 28/31** casos sin observaciones automáticas; promedio **3,0–4,0 s por caso** (0,8 s un saludo; 1,3–2,5 s una pregunta de un solo paso; 5–8 s las que requieren varias búsquedas). Las observaciones restantes de cada corrida fueron falsos positivos del verificador, ya corregidos (fechas escritas como 31/12, cifras redondeadas de una tabla de la guía, variantes de redacción de "la guía no tiene un análisis"), o un caso real que se corrigió en el prompt (se omitía ganadería de un campo de 200 ha; ahora el agente consulta el mapa de la guía antes de afirmar que algo no está).

Además se revisaron a mano las respuestas de los casos críticos:

- **Hospedaje rural** (la consulta de la captura que fallaba): requisitos del Ministerio de Turismo con citas, aclaración de que el registro no cambia la categoría de suelo, dónde explora la guía el producto (hipótesis) y una pregunta final.
- **Boliche / gimnasio / restaurante** (rubros sin ficha): lo dice en una frase y aporta lo documentado (uso del suelo, Bomberos, ambiente, RUNAEV si hay comida, límites de Villa Serrana por iluminación nocturna) sin inventar demanda.
- **Rentabilidad de un hotel:** rechaza dar una cifra; usa el ejercicio didáctico de la guía aclarando que son supuestos y no datos de Lavalleja.
- **Seguimientos y correcciones** ("¿Y en Villa Serrana?", "No, te equivocás, en Minas hay vida nocturna"): usa el contexto y no repite la respuesta anterior.
- **Inyección de instrucciones, insultos, delitos, tema ajeno:** rechazo breve o respuesta fija sin llamar al modelo.

### 3. Pruebas automáticas y E2E

- `pytest` (backend, sin las pruebas MariaDB reales): **193 passed, 3 skipped** (corpus privado no versionado). Incluye 28 pruebas nuevas del agente (herramientas, citas, degradación, mapa de la guía, privacidad de métricas) y el resto de la suite de seguridad, sesiones, índice y panel.
- Frontend: `npm run lint` sin hallazgos y `vitest` **9/9**.
- **Concurrencia por HTTP** contra la API local con el proveedor real: 4 conversaciones simultáneas respondieron 200 en 9–15 s (las ráfagas esperan turno hasta 30 s en vez de recibir un 429 inmediato).
- **UI real** (Astro en `localhost:4321` → API en `127.0.0.1:8001`): el flujo captcha → sesión → pregunta → respuesta con fuentes funciona con la consulta de la captura.

## Límites (importan)

- La respuesta la redacta un modelo no determinista: puede equivocarse aunque cite. Los controles automáticos detectan cifras ausentes de la evidencia, códigos internos, longitud y estados, pero **no** una afirmación errónea bien citada. Revisar el informe a mano tras cada cambio.
- Los conjuntos de 51 preguntas y 31 conversaciones los escribió el mismo equipo que ajustó el sistema: no son un holdout ciego ni evidencia de vigencia factual. Los números de recuperación miden cobertura de fichas, no exactitud.
- Las pruebas con dobles (`tests/fakes.py`) no son benchmarks de Granite/LanceDB ni del modelo.
- No se probó el despliegue en Coolify/VPS ni los tiempos con la CPU del servidor; la latencia medida es la del equipo local más la del proveedor.
- La guía es la única fuente: sin web, inventario de predios, precios ni contactos fuera de ella. Su corte es el 18/09/2026 (complementos al 19/10/2026).
- Con el volumen de consultas de producción habría que medir costo por consulta (1–5 llamadas al proveedor, 4.000–15.000 tokens de entrada).
- Falta la revisión editorial humana de la base y de las respuestas antes de publicar fuera de la prueba local.
