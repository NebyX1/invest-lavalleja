# Validación del agente RAG

## Corrección del flujo de redacción · continuación 08/11/2026

La candidata local reemplaza la salida libre por interpretación previa del pedido, afirmaciones con respaldo literal y revisión obligatoria de cada afirmación. Las tandas fallidas de la investigación anterior se conservan debajo: no acreditan la calidad del flujo nuevo. No se realizó push, despliegue remoto, aprobación editorial ni activación automática de la base.

### Cambios comprobables

- `Agent.run` ya no puede entregar prosa temprana que evite la fase final. `information.py` fija el pedido antes de mostrar el corpus y conserva pregunta e historial en composición y revisión.
- `answer_contract.py` exige esquema estricto, fuente efectivamente expuesta y fragmento literal contiguo. La revisión distingue información, condición solicitada y ausencia puntual de reservas no pedidas, asesoría y temas ajenos. Rechaza el plan completo y solicita otro: no recorta frases ni selecciona respuestas por rubro o localidad.
- Hay una ronda adicional de investigación de solo lectura, con hasta seis llamadas; hasta tres planes revisados y 100 s en total. La compatibilidad del parámetro `think` comparte el timeout, en lugar de repetir un plazo completo.
- Se conservan las compuertas de seguridad antes del conocimiento, las versiones públicas, las fuentes y las citas. Las vistas originales de procedimientos se abren según el pedido previo. El reranker permanece en el flujo: Granite + BM25 + mMARCO, seis candidatos, 160 tokens, hasta 1.500 ms compartidos.
- El modelo seleccionado en `.env` local y `.env.example` es `mistral-large-4`. No se agregaron variables. Se retiró la alternativa implícita a DeepSeek; las alternativas configuradas explícitamente se conservan. Un modelo guardado en Personalización prevalece y no se sobrescribió en SQL. La conexión MariaDB configurada localmente devolvió `OperationalError` durante la inspección; no se afirma haber modificado esa instalación ni una publicación remota.

### Comparaciones conservadas

Artefactos privados, fuera de Git: `reports/writing-fix-20261108/`.

- `contract-01` y `contract-02`: afirmaciones demasiado grandes, reparaciones insuficientes, falsos rechazos de datos pertinentes y fallos de red. No aceptados.
- `contract-deepseek-03`: una respuesta aceptada de cuatro; persistieron adiciones o incumplimientos de alcance. `contract-oss-03`: cuatro fallos de esquema. No seleccionados.
- `contract-mistral-03`: cuatro respuestas aceptadas por máquina, con una interpretación geográfica errónea; se precisó el ámbito antes de continuar. `contract-mistral-04`: fallos de red y citas mal copiadas, conservados.
- `flow-mistral-05` y `flow-mistral-06`: flujo integrado inicial. Aparecieron reservas no solicitadas, exceso de investigación, fallos de proveedor y un error de clasificación de una central energética. No se aceptan como resultado final.
- `flow-mistral-07`: ocho de ocho respuestas completas, revisadas directamente para tono y alcance; incluye Varela, comparación solar, boliche en el norte, seguimiento sobre Solís, retiros de agua, precio ausente, paisaje rural y quesería. Entre 16,9 y 49,2 s por consulta en esa tanda. No es un test ciego ni una garantía para toda pregunta.
- `flow-gemma-07`: ocho respuestas aceptadas por su propio control, pero la revisión directa encontró la central homónima tratada como solar y omisión de excepciones normativas. No se seleccionó. Este resultado muestra por qué la aprobación del propio modelo no basta como métrica factual.

La interpretación y redacción no usan ejemplos de respuestas sobre esas localidades. Las preguntas de regresión viven en `evals/writing_regression.json`, separadas de la política. Los informes congelan código, corpus y preguntas mediante SHA-256 y preservan intentos, respuestas y fallos para revisión. Los logs productivos conservan solo códigos y métricas.

### Aceptación final de la candidata

`flow-final-08.json`: **12/12 respuestas completas**, 58 intentos HTTP reales, sobre la base R2 y el código congelado. Consultas entre 15,45 y 59,93 s, con seguridad semántica real, Granite/mMARCO y LanceDB. `evals/writing_regression.json` incluye conversaciones encadenadas, una corrección de alcance, comparaciones solares, viento, actividades rurales, servicios, pasos turísticos, excepciones de retiros, precio ausente y Centro Pyme.

La revisión directa de las respuestas completas aceptó las doce para tono, alcance y utilidad. El control rechazó un cierre eólico sobre falta de habilitación no preguntada, una regla de riego ajena a la consulta sobre retiros y datos ajenos a la pregunta por servicios. Se redactaron planes nuevos; no se recortaron las frases desde el servidor. También se repararon un esquema de intención y un intento de sustituir información territorial por una ausencia.

`flow-identity-09.json`: **2/2 controles factuales adicionales**, 8 intentos HTTP. Identificó la central de 10 MW como eólica, en Canelones; conservó ese referente cuando se preguntó si era solar y de la ciudad de Lavalleja.

`final-direct-review.json` registra los **14/14 casos** y hashes de cada respuesta, con notas de revisión. Es una revisión directa del agente de desarrollo, no una auditoría humana externa ni un test ciego. La aceptación se limita a estas consultas; no implica exactitud universal. Las métricas del modelo revisor por sí solas no se usaron para aceptar calidad.

### Conocimiento y recuperación

Entrega corregida: `better-rag/consolidated/Invest_Lavalleja_2026_informativa_ampliada_r2.gianna.json`.
SHA-256: `d6bd0ba74fd9fb223b2ff822b4dc10b4317dcb086d68c287382e9a8aa9979d91`.
576 registros: 244 públicos y 332 internos; 192 fuentes. Se preservan originales y archivo interno. La enmienda exige el hash del registro anterior y no puede cambiar audiencia ni identidad.

El bloque EN-008 identificaba de forma ambigua a Solís de Mataojo. Se precisó la tecnología eólica y la localización en Canelones con [ADME](https://adme.com.uy/mme_admin/participantes/generadores_admin.php?remota=1) y [Resolución 935/015 de IMPO](https://www.impo.com.uy/bases/resoluciones/935-2015). La precisión se incorpora al texto y su lectura documental; no existe una respuesta especial para esta consulta.

`benchmark-r2b/retrieval.json`, índice nuevo con ONNX y LanceDB reales, fixture SQL aislado: 24/24 con fuente esperada entre las ocho primeras, 23/24 entre las tres primeras y 20/24 en primer lugar. Reranker aplicado en 24/24, p95 ~994 ms; caché 24/24, p95 ~200 ms. Se midió en Windows con dos hilos ONNX, sin límite de CPU impuesto por Docker. El gold fue revisado previamente y no es una evaluación independiente. La recuperación no equivale a corrección de todas las afirmaciones generadas.

### Verificación de código

- Suite completa: **821 aprobadas, 45 omitidas**, 193,42 s. Las omisiones corresponden a pruebas opt-in/artefactos privados; no se contabilizan como aprobadas.
- Revisión final de configuración, transporte, contratos y flujo después de retirar la alternativa implícita: **80 aprobadas**, 6,31 s.
- MariaDB y MinIO reales en contenedores aislados: **46 aprobadas**, 118,35 s. No se usó SQLite como base de aplicación.
- Primera ejecución completa conservada: 815 aprobadas y dos fallos de dobles HTTP que aún esperaban prosa libre. Se adaptaron al nuevo protocolo, manteniendo la comprobación de seguridad y memoria; no se desactivaron controles.
- Se sustituyeron pruebas del antiguo escape temprano y declaración de alcance posterior a las fuentes por pruebas de intención previa, contrato, rechazo y regeneración completos, citas literales, memoria, acceso documental, presupuesto compartido y no entrega de reservas rechazadas.

La base es una entrega nueva, no una publicación activada. Las pruebas de generación consultan el agente y proveedor reales sobre un índice aislado, no el sitio de producción ni sus credenciales administrativas.

---

## Base ampliada, recuperación y redacción · 08/11/2026

**Resultado:** se creó una base informativa nueva y mejoró la cobertura de
recuperación con los mismos modelos Granite/mMARCO. **La redacción libre no
superó la aceptación de tono y alcance.** No se considera resuelto el problema
completo ni se publicó esta base o el código en producción.

### Entrega y trazabilidad

Archivo de entrega: `better-rag/consolidated/Invest_Lavalleja_2026_informativa_ampliada.gianna.json`
(desde la raíz del repositorio). Formato `gianna.corpus.v1`, UTF-8, aproximadamente
2,36 MB. SHA-256:
`8d4c2a0e42baf180e2fbc93686ecbf39a4fb8b9a06304f1759889abebe3e456d`.

- 244 registros públicos: 213 vistas revisadas de la guía y 31 bloques nuevos.
- 332 internos: los 75 anteriores intactos y un archivo de los 257 originales
  públicos. Los 44 bloques de metodología pura sin datos descriptivos se
  conservan en ese archivo; no generan una copia indexable pública.
- 191 fuentes: las 172 existentes y 19 referencias del suplemento. De las nuevas,
  18 son páginas/PDF primarios consultados y uno es la referencia a la guía
  pública aportada por el responsable. La consulta de esas 18 fuentes no
  constituye una reverificación independiente de las 172 anteriores.
- Perfiles de localidades, norte, energía solar/eólica, logística, alimentos,
  turismo, infraestructura y apoyo empresarial. Nombres y alias en
  `catalog_entry`; originales públicos íntegros y condiciones en `documentary`.
- La clasificación de propuestas, antecedentes, fechas, ámbito y fuentes se
  conserva. No se agregaron precios, disponibilidad predial, demanda, retornos
  ni un ranking de rentabilidad que no estuvieran documentados.

El suplemento público versionable está en
`samples/invest_supplement_20261108.json`; el paquete completo contiene el anexo
interno y permanece fuera de Git y Docker. La compilación exige vistas ligadas
al SHA-256 de los originales. No sobrescribe entradas ni archivos de salida,
no aprueba registros y no activa publicaciones. El paquete requiere esta versión
del backend, que reconoce los nuevos campos opcionales; un backend anterior con
validación estricta puede rechazarlos.

Los originales de trabajo y las corridas están en la carpeta privada
`reports/invest-rebuild-20261108/`. El corpus evaluado v4 tenía SHA-256
`18fc4397dd759aba6bd15a8cafebef20a0c11d1cfc608408352f03c8684ca0d5`.
La entrega conserva exactamente sus textos indexados, cabeceras, vistas,
catálogo, audiencias y fuentes. Solo cambian la procedencia del suplemento al
normalizar LF y dos etiquetas de período de eólica para identificar correctamente
ADME/MTSS. `delivery-equivalence-r1.json` comprueba esa relación. Los índices y
respuestas se evaluaron sobre v4, no sobre una supuesta instalación productiva.

Se corrigió la mezcla de diseño y registro de Minas I: el suplemento utiliza
los 42 MW instalados/autorizados registrados por
[ADME](https://adme.com.uy/mme_admin/participantes/generadores_admin.php?remota=1),
consultada el 08/11/2026; el diseño preliminar de 66 MW no se presenta como la
capacidad instalada. El recurso eólico limítrofe se atribuye al
[estudio MTSS/MIEM de 2025](https://www.gub.uy/ministerio-trabajo-seguridad-social/sites/ministerio-trabajo-seguridad-social/files/documentos/publicaciones/Informe%20Prospectiva%20Empleo%20H2V%20Uruguay%20v.f.pdf).

### Recuperación real y corrección del conjunto de evaluación

24 preguntas declaradas en `evals/invest_rebuild.json`. La métrica es encontrar
**al menos una ficha esperada**, no recuperar todos los hechos necesarios ni
certificar una respuesta. No es un conjunto ciego ni externo. Se revisaron los
IDs esperados: algunas referencias iniciales confundían IDs de fuentes con IDs
de registros, especialmente en energía. Las cifras preliminares basadas en esos
IDs se descartan. `gold-before-review.json` conserva la versión anterior y
`retrieval-reviewed-gold.json` recalcula las listas inmutables, sin repetir
inferencia ni reutilizar los tiempos como una comparación simultánea.

| Configuración | Esperada en 1.º | En tres primeros | En ocho primeros | MRR |
|---|---:|---:|---:|---:|
| Original, presupuesto anterior de 400 ms | 10/24 | 15/24 | 19/24 | 0,546 |
| Base nueva, híbrido + catálogo | 21/24 | 23/24 | 24/24 | 0,918 |
| Base nueva, híbrido + catálogo + mMARCO/RRF | 21/24 | 24/24 | 24/24 | 0,931 |

Dos preguntas agregan conocimiento ausente del original: Hikari y unidades/
estacionalidad del mapa solar. No se contabilizan como errores del buscador al
comparar solo cobertura compartida: el original logra 19/22 en ocho y la nueva
base 22/22. El cambio combina contenido, representación y catálogo; no permite
atribuir toda la mejora al reranker. No se cambiaron los pesos ni el embedding.

El orden neural puro había empeorado el primer resultado en parte de los casos.
Se conserva la fusión RRF de igual peso con el orden híbrido, seis candidatos,
160 tokens por par, una sola oportunidad neural por respuesta y fallback íntegro.
La ventana anterior de 400 ms cancelaba todas las inferencias en este conjunto;
con 1.500 ms se aplicaron 24/24 en la medición secuencial local. Caché 24/24,
p50 de búsqueda aproximadamente 119 ms; sin caché, p50 801 ms. Son medidas locales.

### Docker con límites efectivos

`reranker-docker-2cpu.json`: Docker, red deshabilitada, dos CPU y 2 GiB, pesos
montados de solo lectura. Índice SQL/FTS/Lance aislado; SQLite es solo la fixture
de evaluación, no una reversión de MariaDB en la aplicación. No hay generación.

- Secuencial: mMARCO aplicado 24/24; p95 de búsqueda 1.110 ms. Caché 24/24,
  p95 265 ms.
- Doce paráfrasis adicionales declaradas antes de medirlas: primer resultado
  esperado 9/12 híbrido y 11/12 con reranker; ambas variantes 12/12 en tres.
  Tampoco son un holdout externo o independiente del equipo.
- Tres concurrentes, nueve consultas frías: una aplicación, seis fallbacks por
  ocupación y dos por timeout; p95 1.544 ms. Con caché previamente intentada:
  seis aciertos, dos aplicaciones y un fallback; p95 1.479 ms.
- **El informe global de aceptación devuelve `passed=false`:** no mejoró
  estrictamente hit@1 en el gold y la latencia de caché concurrente no quedó
  suficientemente cerca del híbrido. Esos criterios fallidos se conservan.
- `window-sweep-2cpu.json` comparó cuatro y seis candidatos sobre el mismo índice
  aislado y las 36 preguntas. Cuatro redujo el coste de inferencia y logró 36/36
  aplicaciones en esa corrida, pero bajó el gold de 24/24 a 23/24 en tres.
  Se mantuvo el máximo/predeterminado de seis. Hubo variación entre corridas,
  carga compartida del host y un arranque frío de búsqueda de 6,46 s: el presupuesto
  del reranker no es un SLA de toda la recuperación ni de la respuesta.

### Instrucciones y flujo: resultados negativos conservados

Se ejecutaron **347 intentos HTTP de evaluación**, sin reintentos automáticos de
los evaluadores ni publicación, autorizados por el responsable. No representan
327 preguntas independientes. Los resultados conservan modelo, parámetros,
fuentes, preguntas, respuestas, consumo y hashes; los secretos no se guardan.

Se probaron instrucciones extensas, breves, positivas, español/inglés, conversación
nativa con la pregunta al final, tres u ocho fichas, perfiles solamente, selección
semántica, edición adicional y ejemplos ficticios sin localidades de Lavalleja.
También se comparó `think=false` y modelos del catálogo: DeepSeek 1017, GLM 5.3
Flash, MiniMax M3.1 Flash y Mistral Large 4. Las configuraciones del proyecto y
el modelo elegido no se cambiaron. Ninguna variante certificó el tono requerido.
MiniMax además produjo una salida defectuosa con mezcla de idiomas/marcadores.

- `agent-01.json`: 24 conversaciones con seguridad, búsqueda, herramientas y
  seguimiento; 98 intentos HTTP. Todas devolvieron `answered`, pero varias
  resumían fichas no pertinentes o añadían límites no pedidos.
- `agent-02.json`: selección explícita y redacción obligatoria; 24 `answered`,
  112 intentos. Persistieron los desvíos y aumentó el coste. **Se descartó.**
- `agent-catalog-03.json`: catálogo inicial breve, ocho casos críticos,
  36 intentos. Persistieron límites no pedidos y comienzos negativos.
  **Se descartó.**
- Se restauraron agente, instrucciones y escritor de la variante medida en
  `agent-01`. Los prototipos y sus hashes permanecen archivados en
  `rejected-flow-decision.json` y las instantáneas de código. La conversión a LF
  posterior no altera las cadenas que interpreta Python.
- Se conservan las mejoras verificadas: catálogo como candidatos de recuperación,
  vistas descriptivas con detalle documental, naturaleza de fuente sin el mandato
  «a validar», posibilidad de comparar atributos y un contexto de escritura limpio
  en el último paso del presupuesto y en la reparación de citas.

Fallos que **siguen abiertos**: Varela puede cerrar con ausencia de activos o
rentabilidad sin que se haya preguntado; solar puede comenzar negando un ranking
en lugar de describir los contextos útiles; el caso del boliche en el norte puede
arrastrar otras actividades o límites del rubro. Hay hechos pertinentes recuperados,
pero el generador no respeta siempre el alcance. Una marca automática vacía y una
cita estructuralmente válida no significan aprobación editorial. Tampoco se
certificó exhaustividad o vigencia legal de todas las afirmaciones generadas.

La mejora de recuperación con modelos constantes descarta que todo el problema
sea incapacidad del embedding. La persistencia de desvíos con evidencia correcta
muestra un problema adicional de selección/síntesis y seguimiento de instrucciones.
La comparación realizada no identifica un modelo generativo ganador ni justifica
un reemplazo automático.

### Revisión semántica adicional: tampoco aprobada

Se ensayó un crítico de alcance con citas literales ancladas al borrador,
reescritura dirigida y una segunda evaluación, sin filtros por palabras ni
borrado de oraciones en el servidor. En ocho casos, DeepSeek consumió 12 intentos:
aceptó varios desvíos conocidos (Varela y la apertura sobre ranking solar) y
marcó para revisión parte del encuadre de un procedimiento. La corrección dirigida
mejoró un caso eólico, pero el crítico no resultó un control fiable.

Un revisor independiente `gpt-oss:120b` consumió ocho intentos adicionales:
seis resultados no cumplieron la validación del protocolo o de citas literales
ancladas. Los dos aceptados no bastan para acreditar calidad. No se infiere
exactitud semántica de los casos inválidos. Ambas corridas están conservadas en
`scope-review-01.json` y `scope-review-independent-02.json`; no se integró este
control en la aplicación ni se cambió el generador. Los 347 intentos anteriores
incluyen estas veinte llamadas adicionales.

### Qué se tomó de Gianna Turismo

Se leyó el remoto
[`b1ce4826d36dfed9ea48c961ce645b82ab4adcc4`](https://github.com/NebyX1/giana-turismo/tree/b1ce4826d36dfed9ea48c961ce645b82ab4adcc4):
catálogo de entidades, unidades recuperables con contexto, léxico+denso fusionados,
reranking de candidatos, anclas de catálogo y una redacción separada de la búsqueda.
La copia local tenía cambios adicionales; no se editó ni se trató como idéntica
al remoto. Invest adopta perfiles fuente y mejor fusión, manteniendo sus filtros,
versiones inmutables y control semántico de seguridad previo a recuperar. La
separación obligatoria completa se ensayó y no se incorporó por sus resultados.

### Verificación técnica y estado de publicación

- Suite final: **816 passed, 45 skipped**, en Windows/Python 3.12 con UTF-8
  explícito para subprocess. El primer intento detectó un conflicto de codificación
  del proceso hijo; no se añadió ninguna variable al `.env` de la aplicación.
- Integraciones opt-in de MariaDB y MinIO: **42 passed**. Dos pruebas adicionales
  verificaron catálogo, vista y documento íntegro al importar, exportar y congelar
  snapshots públicos en MariaDB nueva y actualizada: **2 passed**.
- Reemplazo completo de contenedor sin volumen local, con MariaDB, MinIO,
  LanceDB y ONNX reales: **1 passed**, seis escenarios (persistencia privada,
  caché nueva, salud, segunda sustitución, modelos restaurados y logs sin secretos).
  Evidencia controlada en `reports/minio/redeploy.json` y `redeploy-events.jsonl`.
- No se ejecutó el escenario de reconexión del volumen local anterior ni la prueba
  de navegador de monitoreo. El frontend no cambió. Los tests con dobles verifican
  contratos; la calidad generativa se juzga en las corridas reales anteriores.
- No hubo push, despliegue, cambio de `.env`, importación a la base de aplicación
  ni activación de conocimiento público. La base de entrega sigue siendo borrador.
  **El proyecto no se declara listo para producción por esta evaluación.**

## Personalidad informativa · segunda tanda real · 08/11/2026

Se autorizaron y ejecutaron **10 intentos HTTP adicionales**, sin reintentos ni
modelo alternativo, conservando las cinco llamadas de la tanda anterior. El
modelo y selección local siguen siendo `deepseek-v4.1-flash:1017`, temperatura
0,1 y 4.096 tokens de salida. La prueba usa fuentes públicas preseleccionadas y
el formato real de citas: no prueba recuperación, el control de seguridad de
extremo a extremo ni el runtime de producción. Los archivos de resultados
guardan las respuestas y hashes; no se descartaron los intentos deficientes.

Los primeros tres casos conservaron preguntas comerciales o advertencias
editoriales como supuesta información del lugar. Se añadió un contrato de
redacción del servidor después de la evidencia y el historial. Los dos casos
siguientes seguían incluyendo condiciones no solicitadas. Se incorporaron
ejemplos genéricos con marcadores, sin respuestas precargadas por localidad, y se
reiteró la pregunta literal en su propio rol de usuario después del contrato;
no se inserta contenido del usuario en instrucciones de sistema. Esto se aplica
a cada generación y reparación de citas sin agregar una llamada al modelo.

Los cinco casos de esa última configuración produjeron respuestas finales:

- El reensayo de Varela pasó de 436 a 266 palabras y dejó de agregar pregunta
  comercial de cierre o checklist de verificación; queda una expresión editorial
  sobre «investigar negocios» dentro de una propuesta.
- La corrección del usuario recibió información factual de Varela (212 palabras)
  en vez de discusión, tareas o preguntas comerciales.
- El dato ausente no produjo un precio inventado ni una tarea de investigación.
- Se conservaron los pasos de un procedimiento expresamente solicitado; no se
  certifica por ello su exactitud legal o factual.
- **Incidencia pendiente:** la consulta sobre una hostería en Villa Serrana aún
  incluyó una instrucción normativa no solicitada y demasiado detalle del plan.

No se considera una validación 10/10 ni una liberación sin observaciones. La
configuración final mejora el caso original, pero **no se da por resuelto el
alcance en todas las variantes**. Los casos iniciales no acreditan la última
configuración, ni viceversa. Se sustituyó una comparación inicialmente prevista
por un reensayo de la pregunta original, con la modificación de protocolo
registrada: es una exploración iterativa, no un benchmark ciego.

Validación de código tras el ajuste: regresión focalizada **114 passed**; suite
completa **616 passed, 43 skipped** en 167,58 s. Las integraciones Docker,
MariaDB, MinIO, ONNX, navegador y el paquete documental privado mantienen sus
requisitos propios y no se ejecutaron en esta corrida. Estos tests no miden
calidad semántica del modelo.

Informe compacto: [segunda tanda](rag-migration/information-style-round2-20261108.json).
Evidencia completa local: `reports/personality-20261108/round2-results.json`,
con diez respuestas y fuentes de prompt archivadas por hash. No se modificaron
`.env`, modelos, corpus, índices, punteros publicados ni datos de producción.
No se hizo push ni despliegue. El cupo autorizado está agotado; nuevas llamadas
de pago requieren autorización.

## Personalidad informativa · 08/11/2026 · cambio local

La consulta «Qué podés decirme de Varela?» expuso un problema de instrucciones:
el prompt pedía qué faltaba validar y una pregunta de cierre para orientar un
proyecto, aunque no se hubiera solicitado asesoría. Se sustituyó ese mandato por
un rol informativo de igual a igual, sin recomendaciones, tareas ni preguntas
comerciales no solicitadas. La extensión depende del pedido y la evidencia, no
de un límite fijo de palabras. Las fechas, hipótesis, condiciones sustantivas,
citas, herramientas, memoria y evaluación previa de seguridad se conservan.

El contrato se aplica después del tono adicional editable y también al reparar
citas. Los antiguos predeterminados exactos se traducen en memoria al tono nuevo,
sin escribir SQL ni perder personalizaciones. El fallback por caída del modelo
mantiene sus fuentes y deja de indicar al usuario que investigue o reintente.
No se añadieron filtros de salida, rutas por localidad ni respuestas precargadas.

Validación del primer ajuste, antes de la prueba real:

- Regresión focalizada de personalidad, agente, seguridad y ajustes: **111 passed**.
- Suite completa de backend: **613 passed, 43 skipped** en 167,78 s. Las
  integraciones Docker/MariaDB/MinIO/ONNX, navegador y corpus privado conservan
  sus requisitos opt-in; no se ejecutaron en esta corrida.
- Se agregaron inicialmente **14 pruebas de contrato y orquestación**; no miden la obediencia
  real del modelo. Cubren configuraciones antiguas/personalizadas, consultas
  abiertas y seguimientos, reparación de citas y ausencia de borrado de frases.

### Prueba real autorizada y refinamiento posterior

Tras autorización expresa se consumieron **exactamente 5 intentos HTTP de
generación**, sin reintentos ni modelo alternativo, con la selección local leída
sin escrituras: `deepseek-v4.1-flash:1017`, temperatura 0,1 y 4.096 tokens de
salida. Se enviaron solo preguntas de prueba y evidencia pública habilitada del
corpus consolidado. Es una prueba del componente de redacción con fuentes
preseleccionadas, **no** del flujo RAG completo ni de la instancia productiva.

El prompt anterior reprodujo las tareas comerciales y la pregunta final no
solicitadas. El primer intento del prompt nuevo pidió más fichas sin dar una
respuesta final en este arnés sin ejecución de herramientas; se conserva como
incompleto. Las tres llamadas restantes emplearon el nudge real de redacción
final y no agregaron una pregunta comercial de cierre. Sin embargo, la respuesta
sobre Varela todavía copió metodología de inversión atribuida a «la guía
propone…» y resultó demasiado larga. El seguimiento sobre un boliche en el norte
no sustituyó el negocio pero conservó condiciones comerciales no pedidas. El
pedido de pasos recibió un procedimiento, con referencias territoriales
innecesarias. No se considera una validación 5/5 ni una certificación factual.

Se afinó después la distinción entre datos territoriales y metodología de
asesoría: compartir localidad no hace pertinente una prueba comercial, modelo
de entrada o checklist, ni atribuirlo a la guía autoriza un consejo indirecto.
La precisión sustantiva permanece y no se filtra la prosa generada. Esta revisión
posterior **no se volvió a probar con el proveedor**, porque se agotó el cupo
autorizado. La regresión focalizada del refinamiento dio **112 passed** en
16,81 s e incluye una prueba nueva contra los consejos indirectos atribuidos a
la guía; no se volvió a ejecutar la suite completa ni representa una nueva
evaluación del modelo. La evaluación detallada y los hashes de las fuentes ensayadas están
en [el informe de revisión](rag-migration/information-style-real-20261108.json).
Los textos completos y las fuentes de prompt anteriores al refinamiento se
conservan localmente en `reports/personality-20261108/`.

No se modificaron `.env`, corpus, índices, perfiles, punteros publicados o datos
de la instalación. No se hizo push ni despliegue de este cambio de personalidad.

## Reranking acotado · 08/11/2026 · 1.0.0-rc5

**Validación local aprobada antes de publicar.** Destino: `NebyX1/invest-lavalleja`,
`main`, `backend/`. El agente, laboratorio y evaluación de recuperación comparten
el contrato de servicio de [Reranking acotado](../docs/RERANKING_ACOTADO.md).
No se desplegó ni se evaluó la instalación productiva de la IDL.

El modo predeterminado `bounded` reordena hasta seis candidatos con 160 tokens
por pareja y un presupuesto de hasta 400 ms por respuesta. El deadline empieza
antes del encoder y se comparte con las búsquedas posteriores; no se permite
más de un intento neural. La caché TTL 300 s/LRU 256 conserva sólo scores,
ligados por HMAC a versión, perfil, consulta, IDs y hashes de pasajes. Ante
ocupación, error o timeout se mantiene exactamente el híbrido. El modo `hybrid`
permite desactivarlo desde Personalización; no hay nuevas variables de entorno.

Los tokenizadores se reutilizan bajo el lock de CPU y su configuración se
restaura incluso al fallar, sin duplicar vocabularios. Los pesos, revisiones,
fingerprints y vectores publicados no cambian. La preparación del perfil
completo en el worker conserva su contrato anterior; el fallback de esta
entrega cubre el serving, no la ausencia de artefactos durante el arranque.

| Comprobación final | Resultado y evidencia |
| --- | --- |
| Suite completa con MariaDB y MinIO reales | **634 passed, 8 skipped**, 95,60 s; `rerank/full-suite-final.xml` y `.log` |
| Recuperación neural real | 51 preguntas, 332 fichas públicas de la colección local de prueba; `rerank/integrated.json`, `.log` y `.events.jsonl` |
| Preguntas adicionales predeclaradas | 12 paráfrasis/contextos, todas con ficha esperada primera tanto en híbrido como en bounded; mismo informe, bloque `holdout` |
| Concurrencia real | Tres simultáneas, **51 consultas por fase**, CPU limitada a 2 y memoria a 2 GB; gates fijados antes de medir, todos correctos |
| Cancelación ONNX real | Tres inferencias iniciadas y canceladas con plazo 5 ms; retorno en 5,68–6,52 ms, lock liberado, configuración restaurada e inferencias siguientes válidas; `rerank/onnx-cancellation.json` |
| Compatibilidad e imagen | Usuario 10001, 1.0.0-rc5, sin red y sólo lectura; fingerprints preservados y SHA-256 del código igual al evaluado; `rerank/image-validation.json` y `image-build.log` |
| Panel HTTP | La suite verifica aplicación real del camino con un doble, caché en la segunda consulta, ausencia de llamadas generativas y exclusión de fichas internas. No es un benchmark neural |

Calidad medida del gold, **sin llamadas al modelo generativo**:

| Métrica | Híbrido | Reranking acotado |
| --- | ---: | ---: |
| Ficha esperada primera | 31/51 | **33/51** |
| Entre las tres primeras | 42/51 | **44/51** |
| Entre las cinco primeras | 44/51 | **45/51** |
| Entre las ocho primeras | 47/51 | 47/51 |
| MRR | 0,71944 | **0,74820** |

Ocho preguntas mejoraron su posición y siete la empeoraron. No se afirma una
mejora individual universal. El conjunto adicional no se utilizó para ajustar
la longitud del gold, pero es una selección local de paráfrasis, sin curación
externa independiente. No se midió la exactitud factual de respuestas generadas.

Latencia de **recuperación** en la carga de tres concurrentes, no latencia total
del chat con seguridad y generación remotas:

| Modo | p50 | p95 | Máximo |
| --- | ---: | ---: | ---: |
| Híbrido | 87,03 ms | 115,09 ms | 135,47 ms |
| Bounded con caché fría | 157,25 ms | 362,58 ms | 394,22 ms |
| Bounded con caché caliente | 89,88 ms | 126,56 ms | 159,48 ms |

En frío se aplicaron 17 reordenamientos y hubo 34 fallbacks por ocupación, sin
esperar admisión neural. En caliente hubo **51/51 cache hits**. El overhead p95
frío fue 247,49 ms, dentro del límite de 400 ms; el caliente fue 11,47 ms, dentro
del umbral predeclarado de `baseline + max(20 ms, 25 %)`. El pico de RSS fue
**1.392,40 MiB** en el ensayo final. Las cifras dependen de este entorno y no
prometen coste cero ni un corte de reloj instantáneo: ONNX cancela cooperativamente.

Se conservan los ensayos previos y sus fuentes exactas: `integrated-v1` falló
calidad/cache por tres expiraciones con 192 tokens; `integrated-v2` pasó con
160 tokens, pero conservaba clones de tokenizadores y alcanzó 1.890 MiB de RSS.
Se eliminaron esos clones. `integrated-v3`, con 12 consultas por fase, excedió el
umbral de caché caliente en unos 3 ms. Se amplió la muestra a 51 por fase, sin
relajar ningún criterio, y se obtuvo el resultado final correcto. Los snapshots
`v1-source`, `v2-source` y `v3-source` conservan los bytes medidos, no plantillas
para regenerar el backend.

Las ocho omisiones de la suite corresponden a cinco pruebas con documentación
privada ausente y tres opt-in de navegador/recuperación de contenedores. Sus
ensayos históricos no se atribuyen a esta ejecución. No se usaron credenciales,
se alteraron datos productivos ni se consumió cuota de generación. La medición
real utiliza SQLite temporal y LanceDB/ONNX reales; la suite separada incluye
MariaDB y MinIO reales. Los corpus privados de entrada no se versionan.

## Correo de acceso · 08/11/2026

El correo de verificación ahora se compone como `multipart/alternative`, con
texto plano UTF-8 y una versión HTML de Gianna. La plantilla usa la identidad
verde oscuro/lima de la consola, código seleccionable, vencimiento visible y
aviso de seguridad. No necesita imágenes, fuentes remotas, JavaScript ni enlaces
para acceder. El tiempo mostrado se obtiene de `EMAIL_OTP_TTL_SECONDS`.
Remitente, destinatario, SMTP y condiciones de acceso se conservan.

| Verificación | Resultado y evidencia |
| --- | --- |
| Acceso, SMTP, MFA, CAPTCHA y rutas Flask | **121 passed**, 16,62 s; `email/auth.xml` y `.log`. SMTP simulado, sin envíos reales |
| Vista HTML en Chromium y WebKit | **18 escenarios aprobados**: 320/390/768/1280 px, claro/oscuro, más estilos sólo inline a 320 px; `email/preview/visual-validation.json` y PNG |
| Accesibilidad automatizada de las vistas con CSS completo | Cero hallazgos en las reglas WCAG 2 A/AA y 2.1 A/AA seleccionadas. No acredita una auditoría manual completa |
| Imagen Docker final | Construida; plantillas presentes y con SHA-256 coincidente, HTML + texto plano, código válido y rechazo de reutilización; `/admin/login` y `/health/live` 200. Sin red, sólo lectura y SMTP simulado; `email/image-validation.json` y `image-build.log` |

Las vistas previas contienen únicamente el **código ficticio 012345** y direcciones
`example.test`. No se leyeron credenciales, se enviaron correos reales ni se llamó
al proveedor de IA. Los navegadores no sustituyen pruebas en Outlook/Gmail reales;
las tablas de presentación, estilos inline y alternativa de texto ofrecen una
base que no depende de las mejoras del bloque CSS.

Para regenerar las vistas desde `backend/`, sin `.env`, SMTP ni servidor:

```bash
python -m scripts.preview_access_email
node scripts/check_email_preview.mjs
```

El segundo comando usa las dependencias Playwright/axe del repositorio y requiere
Chromium y WebKit instalados. El HTML, texto y `.eml` de ejemplo se generan desde
el mismo compositor que utiliza el envío real. No es un despliegue comprobado en
el servidor de la IDL.

## Seguridad semántica · 07/11/2026 · 1.0.0-rc4

**Componente validado con el proveedor y modelo de la configuración local:**
Ollama Cloud, `deepseek-v4.1-flash`, política `semantic-safety-v3`, **20/20 casos**.
Destino de publicación: `NebyX1/invest-lavalleja`, rama `main`, `backend/`.
La instancia productiva de la IDL y su selección actual del panel no se presentan
como verificadas: la configuración local disponible no tiene `DATABASE_URL`.
No se modificaron secretos, configuración, datos ni contenido productivo.

La captura reproducía una salida `clarify` determinista sin modelo. Se eliminó
esa ruta y su plantilla empresarial. El control semántico corre antes de revisar
publicación/índice, mapa de guía, búsqueda, herramientas y fallback. Pregunta e
historial se revisan como un expediente JSON, sin reproducir los roles como una
conversación abierta. El resultado debe ser completo, coherente y tipado;
errores, claves duplicadas y prosa junto a herramientas no autorizan orientación.
Las anclas de riesgo pendientes permanecen cifradas, incluso si falla el
proveedor o se recorta el historial. Los rechazos técnicos registran causa
controlada, sin preguntas, historial ni prosa del proveedor.

| Comprobación final | Resultado y evidencia |
| --- | --- |
| Suite completa con MariaDB y MinIO reales | **571 passed, 8 skipped**, 88,22 s; `safety/full-suite-final.xml` y `.log` |
| Evaluador offline, incluido provider-env, límites, procedencia y cierre | **68 passed**, incluidos en la suite completa |
| Evaluación semántica real autorizada | **20/20**, 20 despachos HTTP; `safety/configured-model-v3.json` y `.log` |
| Frontend | `npm run check`: 42 archivos, cero errores, avisos e indicios; `safety/frontend-final.log`. ESLint del componente aprobado antes de esta evaluación; el componente no cambió desde entonces |
| Runtime | Imagen final construida como usuario 10001; prompt/código coinciden por SHA-256 con el modelo evaluado; contrato de esquema correcto sin red y en modo sólo lectura; `safety/image-validation-final.json` y `image-build-final.log` |

En la política final las tres variantes de la captura producen `clarify` con
`minor_safeguarding`: bloquean orientación empresarial y preguntan por la
protección de menores. No solicitan horarios ni alcohol ni ofrecen ubicaciones.
Los casos explícitos de explotación y sus seguimientos se rechazan; los ocho
controles legítimos se permiten. La coacción laboral se rechaza como `other_harm`
sin inventar una dimensión sexual ni menores. Los criterios originales del
corpus no se modificaron. La mediana fue 734,5 ms y el máximo 890 ms en esta
corrida; no son garantías de latencia del servicio.

Se conservan **todos los informes fallidos**. La primera corrida cloud v1 logró
19/20: un historial largo produjo herramienta más prosa; su único reintento
acotado también falló y el flujo quedó cerrado (`configured-model.json`,
`configured-model-retry.json` y su `.provenance.json`). V2 cambió la entrada a un
expediente y logró 19/20, con rechazo correcto pero etiquetas erróneas de coacción
laboral (`configured-model-v2.json`). V3 precisó categorías generales y separó
las dimensiones de menores/acceso adulto; aprobó los mismos 20 criterios sin
relajar el parser. La autorización cubrió esos **20 casos distintos con
reintentos acotados: 61 despachos HTTP en total**, incluidas tres corridas y el
reintento de diagnóstico. No se harán nuevas llamadas de pago para esta entrega.

Los ensayos anteriores con Qwen3:4b y Phi4-mini locales también quedan como
fallidos. Phi4-mini alcanzó 3/20 en `safety/local-phi4-corpus-final.json`; sus
resultados no acreditan producción. Los primeros informes locales contaban
sólo solicitudes completadas; el evaluador actual cuenta también las fallidas
y separa invocaciones de evaluación de despachos HTTP, sin afirmar facturación.

**Límites:** es un corpus sintético acotado del componente semántico, con el
modelo del entorno existente; no es un ensayo completo del chat productivo ni
una garantía de ausencia de errores. El informe declara
`production_runtime_unverified:true` y conserva hashes de prompt, esquema,
`risk.py`, `runtime.py` y corpus. No se accedió al panel ni al servidor de la IDL.
Las ocho omisiones de la suite corresponden a cinco casos de documentación
privada ausente y tres opt-in de navegador/recuperación de contenedores. Las
pruebas reales de recuperación y navegador de rc3 siguen en `minio/` y no se
atribuyen a una nueva ejecución. No se modificó persistencia en esta entrega.

Procedimiento: [Seguridad de consultas](../docs/SEGURIDAD_CONSULTAS.md).

## Persistencia MinIO · 07/11/2026 · 1.0.0-rc3

Destino: **`NebyX1/invest-lavalleja`, rama `main`, `backend/`**. Producción usa
MinIO de forma predeterminada con `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`,
`MINIO_SECRET_KEY`, `MINIO_SECURE`, `MINIO_BUCKET_NAME` y `MINIO_PUBLIC_URL`.
No se solicita otra variable para elegir el motor. MariaDB conserva contenido,
permisos, fotografías y puntero; MinIO conserva importaciones, respaldo técnico
y modelos verificados. `/app/data` es caché reconstruible y su montaje local no
es un requisito del arranque productivo.

La integración incluye inspección de bucket privado, creación por el worker si
falta, vínculo de identidad SQL/MinIO reanudable, namespace propio, transferencias
con SHA-256 y streaming de ONNX, recuperación de importaciones pendientes y
rechazo de buckets/objetos ajenos. Un alias distinto del endpoint se acepta si
el marcador verifica la misma identidad. No se modifica una política ajena,
publicación, perfil de modelos ni el almacenamiento local anterior.

Procedimiento vigente: [MinIO y redeploy](../docs/MINIO_PERSISTENCIA.md).

| Verificación final | Resultado y evidencia |
| --- | --- |
| Suite completa, MariaDB y MinIO reales | **464 passed, 8 skipped**, 107,30 s; `minio/full-suite.xml` y `.log` |
| Almacenamiento/configuración/fuentes/artefactos focalizados | **88 passed**; `minio/storage.xml` y `.log`, incluidos 20 casos MinIO/configuración |
| Panel y observabilidad, Chromium/WebKit | **22 passed**, 45,43 s; `minio/browser.xml` y `.log` |
| MinIO + MariaDB + LanceDB + ONNX reales | **1 passed, 6 escenarios**, 90,14 s; `minio/redeploy.xml`, `.log`, `redeploy.json` y `redeploy-events.jsonl` |
| Compatibilidad local anterior explícita | **1 passed, 11 escenarios**, 240,46 s; `minio/legacy-recovery.xml` y `.log`; inventario/eventos en `persistence/` |
| Imagen productiva | Docker multietapa, UID/GID 10001, versión 1.0.0-rc3; `minio/image-build.log` |
| Dependencias | Gate correcto con RAW preservado y una clasificación medida del Connector/C; `minio/security/20261108T002452Z-86d2b7ee/decision.json` |

La prueba MinIO creó exclusivamente dos fichas públicas y una interna. Se
eliminó el contenedor de la API y se levantaron **dos contenedores nuevos, con
cero montajes**, recuperando modelos desde MinIO e índices desde la fotografía
verificada. `/health/installation` y `/health/knowledge` devolvieron 200. La
misma publicación, vectores y digest editorial se conservaron; no hubo
`storage_not_mounted` ni claves/sesiones en sus registros. No se llamó al
generador. Se registraron eventos JSON correlacionados entre arranques.

Las ocho omisiones generales son cinco casos de corpus privado y tres opt-in;
los tres opt-in se ejecutaron aparte y pasaron. El corpus privado y la
instalación productiva de la IDL no se presentan como comprobados. No se leyeron
credenciales de MinIO de otros proyectos ni se intervino el servidor productivo.

La auditoría conserva el aviso RAW de MariaDB `PYSEC-2026-217` y verifica por
separado el Connector/C 3.4.9 de la imagen Linux. No hay hallazgos sin resolver
según ese gate; no se afirma que el RAW esté vacío ni que sea una auditoría de
todo el sistema operativo. La auditoría local corre en Windows y registra esa
plataforma; la clasificación corresponde únicamente al cliente de la imagen.

La CI del repositorio central ejecuta las regresiones reales de MinIO y ambos
caminos de recuperación de contenedores, además de sus comprobaciones anteriores.
Las secciones siguientes conservan el historial de las entregas previas y sus
límites; los requisitos de volumen local de rc2 quedan sustituidos en producción.

## Integración en el repositorio central · 07/11/2026

Destino de esta entrega: **`NebyX1/invest-lavalleja`, rama `main`, directorio
`backend/`**. La implementación procede del commit validado `5576b6a` del backend
independiente. Se comprobó que la base de `backend/` en `e408c1b` coincidía
exactamente con la base `13fbfcb` usada durante la reestructura.

Se trasladan implementación, migraciones, pruebas y evidencia, y se adapta
`.github/workflows/backend.yml` de la raíz para ejecutar los seis jobs desde
`backend/`, recoger sus artefactos y aislar las dependencias de Playwright.
El Dockerfile y los requisitos de la API conservan el contenido validado.
Las secciones siguientes documentan las pruebas de esa implementación; los
resultados de integración en este directorio se guardan en `integration-main/`.
La publicación del código no acredita un despliegue ni una intervención en la
base productiva.

Verificación ejecutada desde `backend/` en esta integración:

- **444 passed, 7 skipped**, 92,66 s, suite completa con MariaDB real;
  `integration-main/full-suite.xml` y `.log`.
- **22 passed**, 38,58 s, panel/logs con Chromium y WebKit reales;
  `integration-main/browser.xml` y `.log`. Las seis capturas de `monitoring/`
  se regeneraron en esta ejecución.
- Imagen `gianna-invest-main:validation` construida con `backend/` como contexto;
  `integration-main/image-build.log`. Contrato de esquema comprobado dentro de
  esa imagen sin red ni conexión a la base.
- **137 archivos de implementación y pruebas idénticos** al commit validado,
  comprobados normalizando únicamente los finales de línea; destinos y rutas de
  artefactos de los seis jobs verificados en `integration-main/transfer.json`.

Las siete omisiones son cinco casos de corpus privado y los dos opt-in. El
opt-in de navegadores se ejecutó aquí; los once escenarios de contenedores de la
implementación idéntica conservan su evidencia en `persistence/`.

## Reestructura de instalación, cola y logs · 07/11/2026 · 1.0.0-rc2

Entrega sobre `origin/main` **13fbfcb**, en la rama local
`codex/reconciliacion-arranque`. Las secciones siguientes conservan resultados
anteriores; esta sección describe la revisión operativa actual. No se intervino
Coolify, la base productiva ni sus volúmenes, y no se llamó a generación pagada.

### Causas verificadas y cambios

- El guard anterior exigía un mountpoint exactamente igual a DATA_DIR. Ahora
  inspecciona el montaje que realmente cubre la ruta, incluidos ancestros y
  montajes anidados, y distingue ausencia, sólo lectura, permisos, espacio e identidad.
- Configurar HTTP creaba directorios antes de inspeccionar persistencia. El
  arranque administrativo ahora llega al diagnóstico incluso sin el volumen;
  la inicialización física y la cola esperan un inventario válido.
- Warmup reintentaba cualquier fallo y mantenía el error/fecha del intento
  anterior en un trabajo reencolado. Hay clasificación de causas, esperas visibles,
  límite de intentos, limpieza de estado actual e historial separado.
- JSON corrupto se decodificaba fuera del bloque de ejecución y podía dejar
  trabajos running hasta vencer el lease. La validación, fencing y terminación
  identificada forman parte de cada intento.
- `schema_versions` no acreditaba que columnas/defaults siguieran presentes.
  Ahora se revisa el namespace, historial y contrato completo de columnas antes
  de migrar instalaciones existentes. Sólo se reparan DDL conocidos idempotentes;
  la pérdida editorial, un historial no verificable o una base ajena bloquean sin
  fabricar datos ni resetear versiones.
- Un respaldo vectorial corrupto podía bloquear vectores SQL válidos. SQL,
  respaldo y caché se validan independientemente; dos fuentes válidas distintas
  siguen bloqueando con una razón concreta.
- El panel abandonaba polling ante un error de red y no seguía una recuperación
  de failed después de redeploy. Ahora se reanuda con backoff, muestra datos
  desactualizados y cambia acciones, resultado e historial sin recargar.

La estructura, estados, decisiones y procedimiento se documentan en
[arranque y diagnóstico](../docs/INSTALACION_Y_DIAGNOSTICO.md).

### Verificación final

| Comprobación | Resultado y evidencia |
| --- | --- |
| Python 3.12.13, pytest 9.0.3, suite completa con `--mariadb-docker` | **442 passed, 7 skipped**, 75,62 s; `persistence/full-suite.xml` y `.log` |
| Panel SSR/API, logs y navegador con opt-in | **22 passed**, 39,17 s; `monitoring/final-browser.xml` y `.log` |
| Navegadores | Chromium y WebKit reales, Flask/SQL aislados; 503 transitorio, failed→running sin recarga, acciones, bfcache/pagehide, XSS como texto, 390/1280 px; seis PNG y `monitoring/browser-validation.json` |
| MariaDB: esquema real fresh y upgrade-v2 | Defaults ausentes/apóstrofos, columna técnica/journal ausentes, migración parcial e irreparable editorial; `persistence/schema-reconciliation-mariadb.xml` |
| Namespace SQL ajeno/sin historia | Dos casos sin crear tablas o historia; `persistence/database-namespace.xml` |
| Docker/MariaDB/LanceDB/ONNX reales | **1 passed, 11 escenarios**, 483,86 s; `persistence/container-recovery.xml`, `.log`, `recovery-docker.json` y `recovery-docker-events.jsonl` |
| Integridad de contrato y sintaxis | `python -m scripts.schema_contract`, compilación Python y `git diff --check` correctos |
| Imagen | Dockerfile multietapa, UID/GID 10001 y versión 1.0.0-rc2; `persistence/production-image-build.log` |

Las siete omisiones generales son cinco casos de corpus privado no incluido y
dos opt-in. Los opt-in de navegadores y contenedores se ejecutaron aparte y
pasaron; no se presenta el corpus privado como validado.

La prueba de contenedores creó **dos fichas públicas y una interna**, con
MariaDB exclusiva temporal, volumen y red propios. Montó `/app/data` y utilizó
`DATA_DIR=/app/data/runtime`, demostrando el montaje ancestro real. Sin volumen,
la API administrativa siguió accesible: mostró `storage_not_mounted`, dejó el
trabajo con cero intentos y no descargó modelos.

Al reconectar el volumen original, recuperó automáticamente el **mismo trabajo**
`4546526dd37841b59287dbaddbcaf3f4`, conservando la publicación
`dd5dcf26f0c8492398793396583c81c4` y el digest editorial. También pasaron reinicio,
reemplazo de contenedor, colección ausente/incompleta y retirada/restauración de
modelos. Se registraron **457 eventos JSON** con correlación entre arranques y
comprobaciones contra filtración de claves, contraseñas y sesión. Las búsquedas
de evidencia recuperaron contenido real del índice, sin llamar al generador.

La muestra final fue **1,232 GiB sobre 2 GiB**, con dos CPU. Es una muestra de la
base sintética, no el pico de consumo ni garantía para una base de producción.
Todos los contenedores, red, volumen y etiqueta de imagen aleatoria creados por
la prueba se retiraron; se conserva la imagen de validación nombrada explícitamente.

### Logs y diagnóstico

JSON UTC en stderr, con boot/request/job, intento, etapa, tiempos, código,
ubicación módulo/función/línea y cadena de tipos/causas. Las descargas registran
perfil, revisión, archivo y bytes reales. `operational_events` y `job_events`
conservan historia SQL después de un reemplazo; el diagnóstico presenta el
inventario y el plan sin alterar el contenido.

Los tests comprueban redacción de secretos, URLs con credenciales, parámetros
SQL, cuerpos, prompts y excepciones. No se registra `str(exc)` arbitrario ni se
copian documentos o respuestas del proveedor al registro técnico.

### Dependencias y criterio del aviso MariaDB

pytest se actualizó de 9.0.2 a **9.0.3**. La auditoría inicial se conserva como
evidencia histórica, no como resultado de la candidata final.

El gate de dependencias conserva el JSON original de pip-audit y su SHA-256.
`PYSEC-2026-217` sigue visible: se clasifica por separado como
`runtime_not_affected` sólo al verificar **el mismo driver** y Connector/C
**3.4.9** en la imagen Linux inmutable. Otros hallazgos, versión desconocida,
evidencia ausente o un cliente vulnerable hacen fallar el gate. Las 28 pruebas
de esta política forman parte de la suite general. No se usa `--ignore-vuln`.

La ejecución final está en `security/20261107T214209Z-eaa6437e/`: un hallazgo RAW
preservado, uno clasificado con evidencia y cero sin resolver. El auditor local
corrió en Windows, hecho registrado en el informe; **el cliente Windows 3.4.7 no
recibe esa clasificación**. En CI la auditoría corre en Linux y construye la
imagen del mismo commit. Esto no es un escáner completo del sistema Debian ni una
certificación de toda la infraestructura.

Criterio contrastado con el [aviso oficial de MariaDB](https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm)
y la [incidencia de clasificación PyPI](https://github.com/pypa/advisory-database/issues/400).

### Límites y siguiente despliegue

Esta revisión prueba la mecánica de reconciliación y la integridad sobre datos
sintéticos reales, no la fotografía privada del servidor ni la calidad factual
de sus respuestas. No modifica modelos, espacios vectoriales, contenido,
publicación, dominios ni claves productivas. Un montaje que no exista en el VPS
debe corregirse en Docker/Coolify: el programa lo detecta y explica, no puede
crearlo desde el contenedor. Antes de liberar, conservar respaldo e inspeccionar
la instalación real con la misma imagen y el procedimiento documentado.

La rama local queda preparada para revisión. No se realizó push ni despliegue
remoto como parte de esta reestructura.

## Persistencia y recuperación automática · 07/11/2026

Implementación sobre el backend institucional `a4f996b`, rama local
`codex/persistencia-recuperacion`. No se modificó producción ni se llamó a Ollama.
Diagnóstico: [auditoría](PERSISTENCIA_AUDITORIA.md). Operación, migración y rollback:
[procedimiento](../docs/RECUPERACION.md).

| Comprobación ejecutada | Resultado real |
| --- | --- |
| Suite completa en Docker, Python 3.12 y dependencias fijadas | **273 passed, 16 skipped**, 42,77 s |
| MariaDB 11.4 real, esquemas temporales nuevos y actualización desde v2, SQL estricto | **10 passed, 2 skipped**, 10,81 s |
| Docker + MariaDB + LanceDB 0.40 + ONNX Runtime 1.31 + pesos reales fijados | **1 passed**, 236,32 s; ocho comprobaciones registradas en [JSON](persistence/recovery-docker.json) |
| Frontend (mismos archivos y dependencias del repositorio institucional) | Astro check: 0 errores/advertencias; ESLint sin hallazgos; Vitest **9/9**; build estática correcta |
| Playwright del chat en escritorio y móvil | **16 passed**, 58,8 s; incluye estados de restauración, 503 y vuelta a disponibilidad sin recarga |

Al integrar la corrección en el repositorio central, se repitieron las pruebas sobre
un árbol aislado sin `.env` ni corpus privado: **274 passed, 16 skipped** tanto en
Python 3.12 como en 3.13, y **10 passed, 2 skipped** con MariaDB real. La verificación completa del portal
incluyó **37 pruebas Playwright aprobadas y una omitida**, además de tipos, lint,
unidades y build. La simulación de `simplify_env` se corrigió para no crear directorios
de almacenamiento y tiene una prueba de regresión específica.

La auditoría `pip-audit -r requirements.txt` señaló **PYSEC-2026-217** en el
paquete Python preexistente `mariadb==1.1.14`, sin proponer una actualización de
ese paquete que resuelva el aviso. El [aviso original de MariaDB](https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm)
se refiere a versiones de Connector/C y está corregido en la 3.4.9; una [incidencia
abierta en PyPA](https://github.com/pypa/advisory-database/issues/400) cuestiona
la aplicación de ese rango de versiones al paquete Python. En la imagen local se
comprobó Connector/C **3.4.9**. La versión de la biblioteca utilizada por producción
no se inspeccionó y debe verificarse; la auditoría sigue activa y puede señalar este
aviso hasta que se resuelva su clasificación.

Las 16 omisiones de la suite general son tres pruebas del corpus privado, doce
pruebas MariaDB optativas y una prueba Docker optativa. Las suites optativas se
ejecutaron aparte: en MariaDB solo quedaron omitidos dos casos que necesitan la
guía privada. No se sustituyó esa guía por contenido inventado para declararla validada.

### Evidencia de recreación real

El test Docker generó una base sintética de **dos fichas públicas y una interna**;
aprobó e indexó únicamente las públicas con Granite/mMARCO reales y la publicó
exclusivamente en la MariaDB temporal del test. El laboratorio HTTP autenticado
recuperó el texto `PINO-314` después de:

- Arranque automático con una instancia nueva del motor.
- Reinicio del proceso/contenedor y posterior reemplazo completo del contenedor
  API usando el mismo volumen.
- Pérdida de la colección canónica, conservando versión/vectores en MariaDB.
- Colección incompleta, preservada antes de restaurar.
- Retirada de todos los modelos locales y recuperación automática por revisión fijada.

Durante las dos averías de índice se comprobó `available:false` y POST `/api/chat`
**503**, sin HTTP 500 y sin generación. En cada recuperación se comparó un digest
de bases, borradores, fuentes, versiones, fotografías, chunks y puntero activo:
permanecieron idénticos. Huella real del perfil utilizado:
`2eea22e49a8edf18fa68961adc43568bfab570af7f4efe68fb9b6c45875061ab`.

La muestra final de uso del contenedor fue **1,228 GiB sobre un límite de 2 GiB**,
con límite de 2 CPU. Es una muestra de este test pequeño, no el pico de memoria,
una prueba de concurrencia ni una garantía de capacidad para una base mayor.
La configuración conserva un worker Gunicorn; las pruebas de idempotencia comprueban
que un perfil ya cargado no vuelve a cargar sus pesos.

### Matriz de regresión solicitada

| Escenario | Cobertura |
| --- | --- |
| Reinicio normal y evidencia recuperada | Docker/MariaDB/LanceDB/ONNX reales y consulta al laboratorio HTTP |
| Reemplazo de contenedor | Mismo volumen, misma publicación/digest, nueva instancia de motor, consulta real |
| Modelos ausentes/incompletos/manifiesto inválido | Ausencia real en Docker; transporte determinista para interrupción, hashes y manifiestos |
| Colección ausente | Incidente reproducido con modelo cargado, config no disponible, chat 503 y restauración exacta |
| Índice incompleto/FTS ausente o incompatible | Conteo incompleto real en Docker; LanceDB real para FTS/esquema y contenido alterado |
| Perfil incompatible | Rechazo de huella distinta, sin reinterpretar vectores ni cambiar versión |
| Interrupción de recuperación | Staging parcial y directorio sin manifiesto en LanceDB real; reanudación sin duplicados; descarga interrumpida con transporte doble |
| Protección editorial | Digest SQL completo antes/después, borrador interno excluido, ninguna publicación automática |
| Perfil histórico | Fotografía representativa v2, texto lexical propio y doble de motor distinto; no carga el perfil nuevo |
| Recursos/reintentos | Límites Docker, reutilización por perfil, deduplicación, leases vencidos/nulos, backoff y tres intentos máximos |

También se verificaron: cambio de volumen y adopción explícita; rechazo de montaje
efímero; exclusión de dos escritores; caché por huella/hash; respaldo técnico
independiente; CLI sin escrituras; parada ordenada reencolada; SQL indisponible con
503 mientras `/health/live` sigue respondiendo. Los dobles de modelo/transporte se
identifican como tales: no son un benchmark semántico.

### Archivos y límites de entrega

| Grupo | Cambios |
| --- | --- |
| Motor de recuperación | `services/recovery.py`, `artifacts.py`, `storage.py`, `vector_store.py` |
| Integración y disponibilidad | `services/jobs.py`, `rag.py`, `retrieval.py`, `routes/public.py`, `routes/admin.py`, `web.py` |
| Persistencia/arranque | `db.py`, migraciones SQLite 006/MariaDB 004, `config.py`, `Dockerfile`, `compose.persistent.yaml`, `wsgi.py`, `gunicorn.conf.py` |
| CLI existente y nueva | `recover_knowledge.py`, `prepare_models.py`, `chat_cli.py`, `evaluate_retrieval.py`, `evaluate_answers.py` |
| Regresiones | `test_knowledge_recovery.py`, `test_artifact_recovery.py`, `test_recovery_docker.py`, helper y adaptación de fixtures/migraciones anteriores |
| Operación | `AGENTS.md`, `COOLIFY.md`, `RECUPERACION.md`, `PUESTA_EN_MARCHA.md`, `RAG_ENGINE.md`, esta validación y auditoría |
| Frontend separado | `GiannaChat.tsx`, tipo `Config`, dos casos E2E y documentación del contrato de disponibilidad |

Pendiente en producción: inspeccionar los montajes y runtime reales de Coolify 4.6.0,
respaldar/restaurar una copia verificable de la instalación, contrastar la fotografía
real `02816091…` y aplicar el plan con autorización. No se afirma haber restaurado sus
262 chunks. No se ejecutó generación pagada ni se evaluó otra vez la calidad factual.
La compatibilidad histórica no se probó con los pesos reales Bekko/Horizon ni una
publicación histórica de producción; se conservan sus revisiones y se bloquea cualquier
huella incompatible. Las pruebas se realizaron sin desplegar ni modificar la instalación productiva.

**Fecha:** 29/10/2026. **Revisión de documentación y recuperación:** 06/11/2026. **Alcance:** cambios locales; sin despliegue ni cambios en producción. La base de prueba local no tiene revisión editorial final.

Este informe describe el código actual. El informe del diseño anterior (planificador determinista) está en [historico/VALIDACION_agente_anterior.md](historico/VALIDACION_agente_anterior.md) y no aplica.

## Barreras para consultas sobre menores · 03/11/2026

El backend institucional incorporó rutas previas a la búsqueda para rechazar explotación explícita y continuaciones vinculadas, y pedir una aclaración neutral sobre eventos juveniles ambiguos. La orientación sexual no es una señal de riesgo. Se aprobaron **70 pruebas focalizadas** del agente y la API con dobles; también se verificaron por HTTP una aclaración y un rechazo en una instalación Docker local aislada. Estas pruebas no garantizan cobertura semántica completa ni sustituyen la revisión antes del despliegue. El detalle está en el [informe del backend institucional](https://github.com/IntendenciaDeLavalleja/invest-lavalleja-backend/blob/main/reports/VALIDACION.md).

## Reverificación del 06/11/2026

Se auditó la documentación contra el código y la base activa (`ca5f61b7…`, motor `granite-mmarco-lance-v3`, representación `cards-context-v5`). Se corrigieron referencias obsoletas a E5/Qdrant/FastEmbed, al prefijo `passage:` y a un reranker que se describía como parte del laboratorio cuando solo se usa en la verificación de modelos y en la evaluación comparativa.

Se volvieron a ejecutar los tres modos sobre las 51 preguntas: **híbrido** hit@1 0,745, hit@8 0,961, MRR 0,830, **144,9 ms**; **fusión con cross-encoder** hit@8 0,941, MRR 0,825, **6.023 ms**; **solo cross-encoder** hit@8 0,922, MRR 0,841, **6.571 ms**. Los controles de seguridad incorporados del backend institucional son posteriores a la implementación evaluada; estas mediciones corresponden a la recuperación del 29/10/2026. No se volvieron a ejecutar las 31 conversaciones contra el proveedor en esta fecha; los resultados de esa sección corresponden a la corrida original.

## Diagnóstico de lo que fallaba

| Síntoma en el chat | Causa verificada | Corrección |
| --- | --- | --- |
| "El proveedor de respuestas no está disponible" | El cliente trataba igual cualquier error HTTP, timeout de 80 s, respuesta vacía o recorte de contexto; el cross-encoder sumaba ~6 s por búsqueda y había varias por consulta | Reintentos con espera, modelo alternativo, plazo total de 100 s, reranker fuera del camino, respuesta degradada con fichas en vez de error |
| "No tengo documentado un perfil de zona…" para cualquier rubro fuera del catálogo | Un planificador de palabras clave decidía abstenerse antes de que el modelo viera la evidencia | Agente con herramientas: el modelo ve la evidencia y el mapa completo de la guía y decide qué buscar |
| Respuestas pobres con evidencia fragmentada | Registros de 60–200 caracteres ("Ocupación supuesta", "2 · Contrastar mercado") recuperados sin su contexto | Fichas autosuficientes (332 fichas: 257 públicas y 75 internas; se indexan las públicas) con cabecera contextual |
| Evidencia recortada | Tope artificial de 8.000 tokens por petición | Sin tope de 8K: hasta 36.000 caracteres de evidencia por respuesta |

El modelo configurado (`deepseek-v4.1-flash:1017`) existe en el catálogo real de Ollama Cloud (`/api/tags`) y respondió en 1,4–2,7 s con y sin herramientas, con llamadas de herramientas nativas también en `glm-5.3` y `kimi-k3`.

## Qué se midió y resultados

### 1. Recuperación (51 preguntas, `evals/retrieval_gold.json`, sin llamar al modelo)

| Modo | hit@1 | hit@3 | hit@5 | hit@8 | MRR | ms por búsqueda |
| --- | --- | --- | --- | --- | --- | --- |
| **Híbrido (camino de la consulta)** | 0,745 | 0,902 | 0,922 | **0,961** | 0,830 | 145 (promedio) |
| Híbrido + cross-encoder | 0,725 | 0,922 | 0,941 | 0,941 | 0,825 | 6.023 |
| Solo cross-encoder | 0,784 | 0,882 | 0,902 | 0,922 | 0,841 | 6.571 |

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

- `pytest` (backend): **193 passed, 15 skipped** (12 pruebas MariaDB opcionales que requieren `--mariadb-docker` y 3 del corpus privado no versionado). Incluye 28 pruebas nuevas del agente (herramientas, citas, degradación, mapa de la guía, privacidad de métricas) y el resto de la suite de seguridad, sesiones, índice y panel.
- Frontend: `npm run lint` sin hallazgos y `vitest` **9/9**.
- **Concurrencia por HTTP** contra la API local con el proveedor real: 4 conversaciones simultáneas respondieron 200 en 9–15 s (las ráfagas esperan turno hasta 30 s en vez de recibir un 429 inmediato).
- **UI real** (Astro en `localhost:4321` → API en `127.0.0.1:8001`): el flujo captcha → sesión → pregunta → respuesta con fuentes funciona con la consulta de la captura.

## Límites (importan)

- La respuesta la redacta un modelo no determinista: puede equivocarse aunque cite. Los controles automáticos detectan cifras ausentes de la evidencia, códigos internos, longitud y estados, pero **no** una afirmación errónea bien citada. Revisar el informe a mano tras cada cambio.
- Los conjuntos de 51 preguntas y 31 conversaciones los escribió el mismo equipo que ajustó el sistema: no son un holdout ciego ni evidencia de vigencia factual. Los números de recuperación miden cobertura de fichas, no exactitud.
- Las pruebas con dobles (`tests/fakes.py`) no son benchmarks de Granite/LanceDB ni del modelo.
- No se probó el despliegue en Coolify/VPS ni los tiempos con la CPU del servidor; la latencia medida es la del equipo local más la del proveedor.
- La guía es la única fuente: sin web, inventario de predios, precios ni contactos fuera de ella. Su corte es el 18/09/2026 (complementos al 19/10/2026).
- Con el volumen de consultas de producción habría que medir costo por consulta: 1-5 llamadas al proveedor y, en las 379 consultas registradas, 475-45.581 tokens de entrada (promedio ~6.900).
- Falta la revisión editorial humana de la base y de las respuestas antes de publicar fuera de la prueba local.
