# Evaluación de seguridad antes de orientar · candidata 1.0.0-rc4

La consulta de la captura devolvía una aclaración fija porque `hard_gate`
detectaba menores y local/evento. Esa salida evitaba el modelo. Las pruebas
anteriores exigían esa conducta y cero solicitudes de modelo: validaban una
expectativa de producto incorrecta.

## Flujo corregido

1. Se conservan rechazos tempranos para pedidos explícitos de daño, acusaciones
   personales e insultos. Nunca habilitan orientación ni búsqueda.
2. Toda consulta restante pasa por `services/risk.py`, usando el modelo
   seleccionado, temperatura cero y la política `semantic-safety-v3`. No recibe
   el tono editable, la guía ni herramientas de negocio.
3. El evaluador recibe un expediente JSON con `history` y `current_message`
   como datos en un único mensaje de usuario, después de la política fija.
   Los roles del historial no se reproducen como una conversación abierta:
   una respuesta anterior del bot no cambia el rol del evaluador ni autoriza
   el proyecto. Debe producir cuatro etiquetas
   enumeradas: `decision`, `risk`, `minors`, `adult_access`. Se aceptan la llamada
   a `evaluar_seguridad` o el mismo objeto JSON válido. No se impone `format`
   de JSON Schema al proveedor: Ollama Cloud no lo soporta actualmente.
4. `allow` sólo habilita continuar si las etiquetas son coherentes y no señalan
   riesgo pendiente. `clarify` y `refuse` no consultan índices, no necesitan una
   publicación activa y no entregan ubicaciones, permisos, financiación ni fichas.
   La aclaración sobre menores se centra en finalidad y papel de los adultos.
5. Error, timeout, respuesta libre, campos ausentes o veredicto incoherente
   devuelven 503 identificado. No se sustituyen por recomendaciones automáticas.
6. Sólo después de autorizar se revisan publicación/índice y comienza el agente
   RAG. Su prompt mantiene la misma obligación de protección. El fallback de
   fichas sólo puede operar después de una evaluación válida que permitió
   orientar; nunca resuelve un fallo del evaluador.

La orientación sexual o identidad de género no determinan riesgo ni legalidad.
Se evalúan edades, roles, propósito, invitaciones y relación adulto–menor.
Un evento juvenil supervisado, un espacio LGBT adulto, educación, prevención y
denuncia legítimas deben distinguirse de captación o explotación. La evaluación
no certifica legalidad ni equivale a declarar un delito cometido.

## Contexto y auditoría

El contexto pendiente conserva cifradas la pregunta original y la última
aportación de riesgo (hasta 2.500 caracteres cada una), incluso si el historial
visible se recorta. Una cortesía no lo elimina. Una evaluación `allow` de una
consulta sustantiva permite resolverlo. Se conserva el borrado de conversación y
su caducidad normal. El contexto no se expone en el JSON público.

Los eventos `safety.assessment_*` se correlacionan por `request_id`, `query_id`,
política y fase. La métrica SQL registra fuente de decisión, modelo, etiquetas,
tiempo y cantidad de solicitudes lógicas; no guarda preguntas, historial,
explicaciones libres ni respuestas del evaluador en claro. El conteo total
incluye la evaluación de seguridad. Los reintentos HTTP del transporte son
eventos distintos. Un rechazo de protocolo incluye una causa enumerada, por
ejemplo `unexpected_prose`, `invalid_json`, `duplicate_fields`, `schema_mismatch`
o `unknown_label`. Nunca incluye la prosa o valores desconocidos del proveedor.

La evaluación tiene hasta 25 segundos y 400 tokens de salida; no utiliza la
aleatoriedad del tono empresarial ni cambia silenciosamente a otro modelo. El
presupuesto del agente de 100 segundos incluye esa fase. Hay una solicitud
lógica adicional en las consultas que antes pasaban directamente al RAG.

## Validación y liberación

Las pruebas con modelos guionados verifican orden, API, historial cifrado,
ausencia de búsquedas, cierre ante errores y trazas; no acreditan precisión
semántica. El corpus sintético contiene 20 casos, incluida la captura exacta,
variantes de orientación, eufemismos, seguimientos y actividades legítimas.

```bash
# Sin configuración, secretos ni red: valida únicamente el corpus.
python -m scripts.evaluate_safety --dry-run

# Evaluación real explícita: consume cuota del proveedor configurado.
python -m scripts.evaluate_safety --run-model --output /tmp/safety-evaluation.json

# Si sólo se dispone de la configuración del proveedor, sin conexión SQL:
# el archivo es explícito; sólo se leen URL, clave y modelo, sin modificarlo.
python -m scripts.evaluate_safety --run-model --provider-env /ruta/backend/.env --output /tmp/provider-safety.json

# Opcional, sólo un modelo LOCAL ya instalado; no sustituye validar producción.
python -m scripts.evaluate_safety --run-model --local-model phi4-mini:3.8b --output /tmp/local-safety.json
```

Un informe con `passed:false` se conserva como fallo. No se publica como
validación satisfactoria ni se relajan las expectativas para hacerlo verde.
El modo predeterminado con `--run-model` lee la selección del panel sin migrar
ni escribir SQL. `--provider-env` es una evaluación del componente con el modelo
de ese archivo; no acredita la selección actual del panel productivo. No hereda
otras variables ni activa modelos alternativos. Ambos requieren autorización
para consumir cuota. Los informes registran hashes de prompt, esquema y código,
fuente de selección y despachos HTTP, separados de las evaluaciones lógicas.

La política v3 aprobó **20/20** con `deepseek-v4.1-flash` en Ollama Cloud y la
configuración local existente: [informe](../reports/safety/configured-model-v3.json).
Las corridas previas v1/v2 y los modelos locales fallidos se conservan como
fallos; sus criterios no se relajaron. En v3, la captura y sus variantes requieren
aclaración de protección de menores, sin orientación empresarial; la explotación
explícita se rechaza y los controles legítimos del corpus se permiten.

El informe declara `production_runtime_unverified:true`: no se accedió a la
selección del panel ni se evaluó de extremo a extremo la instancia de la IDL.
Antes de declarar verificada esa instancia debe contrastarse su modelo efectivo
y su despliegue. Los modelos locales, la evidencia simulada y una CI estructural
verde no reemplazan esa comprobación. Este cambio no vuelve infalible al sistema.

Referencia técnica: [Structured Outputs de Ollama](https://docs.ollama.com/capabilities/structured-outputs).
