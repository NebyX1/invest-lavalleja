# Conversión documental y alcance editorial

## Archivo realmente procesado

Se procesó `Invest_Lavalleja_Guia_de_Inversiones_2026(1).docx`, la guía adjunta del usuario. La edición indica corte documental del 18 de septiembre de 2026. No se descargaron ni se incorporaron silenciosamente nuevas normas, estadísticas o contactos para modificar su contenido.

La conversión recorrió el cuerpo DOCX en orden, conservando párrafos, saltos internos, tablas y vínculos. No tomó la lista de párrafos por separado de las tablas. El documento es texto digital; no se usó OCR, visión generativa ni un LLM para resumir o completar las afirmaciones.

## Inventario comprobado

| Elemento | Cantidad |
|---|---:|
| Bloques no vacíos del cuerpo | 769 |
| Párrafos con texto | 733 |
| Tablas | 36 |
| Registros de conocimiento | 271 |
| Registros públicos | 196 |
| Registros internos | 75 |
| Fuentes del registro original | 50 |
| Fichas de oportunidad O01–O16 | 16 |
| Preguntas de evaluación de recuperación | 62 |
| Escenarios de revisión humana de respuestas | 12 |
| Bloques sin contabilizar en el informe de conversión | 0 |

**Registros no significa chunks.** El registro es la unidad editorial reutilizable; el chunk es un fragmento indexable calculado posteriormente con el tokenizador real. No hay embeddings ya producidos en este paquete, ni se indica un conteo ficticio de tokens como si se hubiera ejecutado E5.

## Formatos entregados

`invest_lavalleja_2026.gianna.json` es el archivo recomendado para el panel. Usa el esquema `gianna.corpus.v1` e incluye documento, fuentes y registros. Es portátil y no depende de una base vectorial particular.

`invest_lavalleja_2026.jsonl` es la alternativa autocontenida por líneas, con entradas de documento, fuentes y registros. `public.jsonl` e `internal.jsonl` separan la audiencia para inspección y procesamiento. No publicar el paquete completo ni su variante interna como un recurso estático del sitio.

`guia_completa_preservada.md` y `bloques_originales.json` preservan el contenido y el orden para auditar la conversión. Los títulos, navegación y registro de fuentes no se convierten todos en fragmentos duplicados: se conservan en la representación completa, en metadatos o en la tabla de fuentes. `informe_conversion.json` identifica el destino o motivo de exclusión de cada bloque. Que todo esté contabilizado no demuestra por sí solo una segmentación semántica óptima; se entrega para que esa revisión sea verificable.

`fuentes.json` conserva S01–S50 y sus enlaces originales. La marca de acceso/verificación pertenece a lo que afirma la guía; no acredita que se haya vuelto a visitar cada enlace en esta conversión. Las referencias por rango se expanden, por ejemplo S29–S31. Si un documento genérico menciona una fuente inexistente, el informe registra la referencia no resuelta: no se inventa su URL.

`corpus.schema.json` documenta la estructura aceptada. Se acompaña con preguntas de evaluación, no con resultados de recuperación real.

## Preservación de significado

Se conservan términos de la guía, fechas, cifras, unidades, condicionantes, zonas y tipos de evidencia. Las filas de las tablas se serializan con sus encabezados para evitar valores aislados. Los ejemplos financieros mantienen explícitamente su carácter hipotético. Las fichas de oportunidad mantienen cliente, negocio, prueba, condiciones y condición de descarte, en vez de reducirse a un eslogan.

Los datos compuestos o tablas pueden necesitar varios fragmentos. La recuperación reconstruye el registro padre cuando cabe dentro del presupuesto; en registros largos añade las condiciones a los fragmentos seleccionados. No se atribuye a un padrón la regulación de una agrupación comercial completa.

El anexo interno se mantiene interno. Clasificar como público no equivale a afirmar “comprobado”, y aprobar para indexar no transforma hipótesis comerciales en rentabilidad demostrada. El sistema no publica automáticamente servicios propuestos como si ya estuvieran operativos.

## Localizadores, no paginación inventada

El cuerpo del Word utiliza identificadores de bloques y referencias de sección. No se atribuyen páginas estables a esos fragmentos: el índice y la paginación renderizada del material no coinciden necesariamente y Word puede repaginar por tipografía o dispositivo. Las citas se resuelven mediante título, sección, localizador y fuentes registradas.

No se corrige el índice original ni se reescribe el documento fuente. Las normalizaciones técnicas se limitan a espacios/formato de transporte, encabezados de tablas y metadatos; el archivo original permanece intacto.

## Reproducir la conversión

Con las dependencias instaladas:

```bash
python scripts/convert_guide.py /ruta/a/Invest_Lavalleja_Guia_de_Inversiones_2026.docx --output knowledge
```

Comprobar la ayuda del script si se cambia de versión. El panel usa las mismas funciones de conversión del backend, no un conversor diferente con reglas incompatibles.

## Pendiente antes de atención pública

Revisión humana de la asignación temática y de audiencia; vigencia de normativa y canales; aprobación institucional del contenido; resultados de recuperación E5; calidad de las respuestas generadas; protección de datos y reglas de retención aplicables al servicio. No se certifica jurídicamente la guía ni se la reemplaza por conocimientos externos.
