# Evaluación de seguridad antes de orientar · candidata 1.0.0-rc4

La consulta de la captura devolvía una aclaración fija porque `hard_gate`
detectaba menores y local/evento. Esa salida evitaba el modelo. Las pruebas
anteriores exigían esa conducta y cero solicitudes de modelo: validaban una
expectativa de producto incorrecta.

## Flujo corregido

1. Se conservan rechazos tempranos para pedidos explícitos de daño, acusaciones
   personales e insultos. Nunca habilitan orientación ni búsqueda.
2. Toda consulta restante pasa por `services/risk.py`, usando el modelo
   seleccionado, temperatura cero y la política `semantic-safety-v1`. No recibe
   el tono editable, la guía ni herramientas de negocio.
3. El evaluador recibe pregunta e historial y debe producir cuatro etiquetas
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
eventos distintos.

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

# Opcional, sólo un modelo LOCAL ya instalado; no sustituye validar producción.
python -m scripts.evaluate_safety --run-model --local-model phi4-mini:3.8b --output /tmp/local-safety.json
```

Un informe con `passed:false` se conserva como fallo. No se publica como
validación satisfactoria ni se relajan las expectativas para hacerlo verde.
Los modelos locales probados no cumplieron todos los casos y el protocolo;
el flujo cerró sin permitir RAG. La candidata debe evaluarse con el proveedor y
modelo efectivamente usados en producción antes de declararla apta para liberar.
Los modelos locales, la evidencia simulada y una CI estructural verde no
reemplazan esa comprobación. Este cambio no convierte el sistema en infalible.

Referencia técnica: [Structured Outputs de Ollama](https://docs.ollama.com/capabilities/structured-outputs).
