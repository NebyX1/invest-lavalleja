"""Render a local, non-public delivery report from the measured artifacts."""
import hashlib
from html import escape
import json
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / 'consolidated'


def read(name):
    return json.loads((FOLDER / name).read_text(encoding='utf-8'))


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + escape(str(h)) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + escape(str(c)) + '</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def main():
    manifest = read('manifest.json')
    corpus = read(manifest['corpus']['filename'])
    report = corpus['conversion_report']
    basic = read('validacion-importador.json')
    native = read('validacion-nativa.json')
    live = read('comprobacion-base-activa.json')
    regression = read('regresiones-conversion.json')
    publication = read('publicacion.json') if (FOLDER / 'publicacion.json').exists() else None
    counts = report['counts']
    assert all(basic['checks'].values()) and all(native['checks'].values())
    assert regression['successful']
    assert live['before'] == live['after']
    assert hashlib.sha256((FOLDER / manifest['corpus']['filename']).read_bytes()).hexdigest() == manifest['corpus']['sha256']
    records = {r['id']: r for r in corpus['records']}
    summaries = [
        ('Energía y territorio', '34', 'Antes: eficiencia y cautelas generales. Ahora: eólica, solar, biomasa, biogás, hidrógeno, autoconsumo, conexión, almacenamiento, restricciones y antecedentes de centrales.'),
        ('Agroindustria, forestación y minerales', '35', 'Censo agropecuario, CONEAT, riego y secano, semillas, carne, leche y quesos, olivos, vid, miel, forestación, madera, minerales, alimentos y residuos.'),
        ('Turismo, servicios y capacidades', '34', 'Subzonas y parámetros de Villa Serrana, saneamiento, registros turísticos, georrutas, formación, infraestructura, cuidados y servicios sanitarios.'),
        ('Agua, industria y nuevas actividades', '25', 'Derechos de agua, vertidos y transición normativa, residuos, parques, software y datos, audiovisual, cáñamo/cannabis, acuicultura, drones, compras públicas y COMAP.'),
        ('Contexto territorial adicional', '9', 'Siete filas de síntesis territorial con sus encabezados; ámbitos geográficos específicos; datos para consultas por predio.'),
    ]
    body = '''<header><p class="eyebrow">INVEST LAVALLEJA · ENTREGA LOCAL</p><h1>Base de conocimiento consolidada</h1>
<p>Guía con corte 18/09/2026 + complemento sectorial con corte 19/10/2026.</p>
<p class="notice"><strong>Preparada y validada para importar como borrador. No publicada.</strong> La base activa del portal no cambió. Los registros públicos son candidatos a revisión; los internos no deben entrar al índice público.</p></header>'''
    if publication:
        state = publication['operation']
        body = body.replace('<p class="notice"><strong>Preparada y validada para importar como borrador. No publicada.</strong> La base activa del portal no cambió. Los registros públicos son candidatos a revisión; los internos no deben entrar al índice público.</p>',
                            '<p class="notice"><strong>Publicada en Gianna por solicitud explícita del usuario.</strong> '
                            '332 registros públicos activos; 75 internos excluidos del índice. La versión anterior y su colección se conservan para reversión.</p>')
        body += '<section><h2>Publicación efectiva</h2>' + table(['Dato', 'Estado'], [
            ('Versión activa', state['version_id']), ('Versión anterior conservada', state['previous_version']),
            ('Fecha de activación (UTC)', state['activated_at']), ('Índice público', str(state['validation']['chunks']) + ' fragmentos'),
            ('Modelo de respuesta, sin cambios', state['model']),
            ('Pruebas sobre el índice publicado', str(publication['retrieval']['passed']) + '/' + str(publication['retrieval']['total'])),
            ('Respaldo lógico MariaDB previo, dentro del volumen local', state['backup_path']),
        ]) + '<p><a href="publicacion.json">Registro de la operación y pruebas posteriores</a>. Las secciones de pruebas aisladas de abajo describen la etapa anterior a esta publicación.</p></section>'
    body += '<section><h2>Resultado</h2>' + table(['Registros totales', 'Públicos', 'Internos', 'Fuentes'], [[counts['total_records'], counts['public_records'], counts['internal_records'], counts['total_sources']]])
    body += '<p>Se conservaron exactamente los 271 registros y las 50 fuentes originales, incluidos IDs, textos, condiciones, audiencias y fechas. Las 128 fichas del Word aportan 127 fichas consolidadas: AG-032 y TS-022 describían el mismo evento de ecopuntos y se unieron preservando sus detalles. Se añadieron 9 registros de contexto territorial. Resultado: 136 registros adicionales, sin reinterpretar todo el contenido como hechos nuevos.</p>'
    body += '<p>Las 127 entradas bibliográficas del Word se consolidaron en 122 fuentes por URL idéntica, conservando todos los localizadores y los alias. Las 50 fuentes anteriores permanecen intactas, incluso si comparten URL con una referencia nueva de fecha o localizador diferente.</p>'
    body += '<p><a href="' + escape(manifest['corpus']['filename']) + '">Archivo para el importador (.gianna.json)</a> · <a href="comparacion-y-trazabilidad.json">Comparación y trazabilidad completas</a> · <a href="manifest.json">Manifiesto y SHA-256</a></p></section>'
    body += '<section><h2>Qué información se añadió</h2>' + table(['Familia', 'Fichas originales del complemento', 'Aporte'], summaries)
    body += '<p>La información exclusiva de la guía anterior también se conserva: casos empresariales, las 16 oportunidades, siete zonas, estructura empresarial, impuestos generales, incentivos, costos, ejemplo didáctico de alojamiento, riesgos, contactos y preguntas frecuentes. El anexo de diseño institucional y operación sigue clasificado como interno.</p></section>'
    body += '''<section><h2>Cómo quedó preparada para el RAG real</h2><ul>
<li><strong>Contrato nativo:</strong> gianna.corpus.v1, validado por backend/gianna/corpus.py; no es texto concatenado para un importador genérico de Word.</li>
<li><strong>Unidades autónomas:</strong> título, texto, ámbito, naturaleza de la evidencia, condiciones, período, corte, fuentes y localizadores por ficha.</li>
<li><strong>Condiciones recuperables:</strong> las condiciones nuevas aparecen también en text, porque el fragmentador vectoriza ese campo, además de conservar conditions para el contexto y la revisión.</li>
<li><strong>Audiencia:</strong> importación en borrador y aprobación explícita del contenido público; el backend excluye los registros internos antes de crear el snapshot y los vectores.</li>
<li><strong>Fechas:</strong> el corte global no recertifica los registros anteriores ni transforma estadísticas, estudios, noticias o llamados históricos en disponibilidad actual.</li>
<li><strong>Trazabilidad:</strong> huellas de ambos archivos, copia de los bloques extraídos y el informe original en conversion_report, mapa de cobertura, alias bibliográficos y decisiones de consolidación. Ese archivo de conversión es metadato administrativo, no texto para embeddings.</li>
<li><strong>Sin cambios del agente:</strong> no se modificaron routing, prompts, respuestas, modelos, filtros ni configuración persistida.</li></ul>
<p>La huella document.sha256 identifica el manifiesto de entradas. El SHA-256 del archivo final se guarda por separado para no crear una autorreferencia imposible.</p></section>'''
    body += '<section><h2>Solapamientos y cuestiones que requieren revisión</h2>'
    relations = [
        ('Complemento sectorial', 'La eficiencia no cubría por sí sola las tecnologías de generación. Se añaden sus fichas, no respuestas prefijadas.'),
        ('Alcance legal', 'Se amplía la información sobre planes y áreas protegidas sin extender los límites normativos a toda la zona comercial.'),
        ('Transición normativa de agua', 'Se conservan tanto las condiciones locales como el régimen nacional y su transición; no son permisos intercambiables.'),
        ('Fechas de COMAP', 'La guía ya contenía los decretos 329/025 y 152/026. El complemento precisa inversiones computables y no reabre la transición vencida.'),
        ('Histórico frente a operativo', 'El inventario y las limitaciones de 2025 no certifican disponibilidad ferroviaria comercial en 2026.'),
        ('Revisión de vigencia', 'Recomprobar estado del Plan de Minas, llamados, inscripciones y transición de rótulos antes de publicar; no eliminar las fechas del documento.'),
    ]
    body += table(['Relación', 'Registros previos', 'Ampliación', 'Decisión'], [(label, ', '.join(item.get('old', [])), ', '.join(item['new']), decision) for item, (label, decision) in zip(report['reconciliation'], relations, strict=True)])
    body += '''<p>No se eliminaron textos por semejanza temática. La comparación en ambas direcciones usa Jaccard léxico para localizar candidatos de revisión, no para declarar equivalencia semántica ni decidir si una pregunta tiene respuesta.</p>
<p>Ejemplos importantes: Arequita SNAP y las subzonas de Villa Serrana no equivalen a Z7 o Z3; un inventario ferroviario no certifica servicio comercial; una puesta de manifiesto no es aprobación de un plan; un régimen nacional nuevo de vertidos no elimina automáticamente las condiciones locales de saneamiento. El cuerpo del complemento explica esos límites. No se identificó una contradicción directa que justificara borrar un registro anterior.</p></section>'''
    body += '<section><h2>Validaciones ejecutadas</h2>'
    native_data = native['native']
    body += table(['Prueba', 'Resultado'], [
        ('Regresiones de conservación y estructura', f"{regression['tests_run']}/{regression['tests_run']} aprobadas (tools/test_consolidation.py)"),
        ('Importación/exportación y controles de aprobación en SQLite temporal', f"{basic['checks_passed']}/{basic['checks_total']} comprobaciones aprobadas"),
        ('Indexación con modelos reales', f"{native_data['index']['chunks']} fragmentos; máximo {native_data['index']['max_tokens']} tokens Bekko, límite 420"),
        ('Audiencias', '332 registros públicos fragmentados; 0 registros internos indexados'),
        ('Recuperación de documentos esperados en el contexto', f"{native_data['expected_in_context']}/{native_data['total_cases']} consultas"),
        ('Llamadas a Ollama u otro generador', '0; no se evaluaron respuestas generadas'),
        ('Etapa de prueba aislada: base activa antes / después', live['before'] + ' / ' + live['after']),
    ])
    body += table(['Consulta', 'Fichas esperadas (alguna)', 'Fichas seleccionadas', 'Encontrada'], [
        (case['question'], ', '.join(case['expected_any']), ', '.join(case['selected']), 'Sí' if case['expected_in_context'] else 'No') for case in native_data['cases']])
    body += '<p><a href="validacion-importador.json">Resultados del importador</a> · <a href="validacion-nativa.json">Resultados y perfil de los motores reales</a> · <a href="comprobacion-base-activa.json">Comprobación de la base activa</a></p>'
    body += '<p>Se utilizaron Bekko/OpenVINO, Horizon/ONNX y LanceDB del backend, con sus artefactos locales verificados, en almacenamiento temporal separado. No se activó la versión temporal ni se leyó el .env. Las pruebas verifican recuperación y contratos técnicos: no certifican la verdad, exhaustividad o calidad de una respuesta generada.</p></section>'
    body += '''<section><h2>Revisión de fuentes y límites</h2>
<p>La mayor parte del contenido procede de los documentos entregados. En las referencias nuevas, accessed_at es la consulta declarada por el autor del complemento; verification aclara que no se revalidó independientemente cada fuente. Se contrastaron puntualmente estos aspectos en fuentes primarias:</p><ul>
<li><a href="https://www.impo.com.uy/bases/decretos/306-2024">IMPO, Decreto 306/024</a>: delimitación de Arequita y prohibiciones del artículo 3, incluidas eólica y alta tensión.</li>
<li><a href="https://www.impo.com.uy/bases/decretos/179-2026">IMPO, Decreto 179/026</a>: derogación de 3/025 y modificación del régimen 405/021.</li>
<li><a href="https://www.impo.com.uy/bases/decretos/329-2025">IMPO, Decreto 329/025 actualizado</a>: artículo 4 y referencia a la modificación por 152/026.</li>
<li><a href="https://www.impo.com.uy/bases/decretos/226-2025/79">IMPO, Decreto 226/025, artículo 79</a> y <a href="https://www.impo.com.uy/bases/decretos/226-2025/83">artículo 83</a>: adecuación de instalaciones existentes y derogaciones con transición.</li>
<li><a href="https://www.gub.uy/tramites/registro-generacion-suscritor">MIEM/DNE, generación en suscriptor</a>: registro hasta 150 kW inclusive y autorización por encima, con alcance a centrales aisladas y conectadas.</li></ul>
<p>También se contrastaron las ventanas informadas por MIEM para <a href="https://www.gub.uy/ministerio-industria-energia-mineria/comunicacion/convocatorias/certificados-eficiencia-energetica-2026-para-medidas-eficiencia-0">CEE 2026 estandarizados</a> y <a href="https://www.gub.uy/ministerio-industria-energia-mineria/comunicacion/convocatorias/certificados-eficiencia-energetica-2026-para-medidas-eficiencia">no estandarizados</a>, sin trasladarlas a futuras convocatorias.</p>
<p>Las consultas automatizadas a UTE/Suscriptores y a la presentación ACAU no respondieron dentro del plazo; no se marcan verificadas. En particular, la fuente TR013 tiene un título referido a 2026, pero una URL terminada en presentacion-2025.html: es una discrepancia de metadatos pendiente de comprobar, no prueba suficiente por sí sola de un año incorrecto. El directorio paginado AG036 también requiere confirmar la entrada empresarial antes de publicarla como vigente. No se recertificaron todos los artículos, mapas, contactos, precios, contratos ni las 172 referencias. Los llamados, cronogramas, rótulos, permisos, planes y condiciones tributarias necesitan comprobación antes de publicación o aplicación a un caso.</p>
<p>El Word se revisó estructuralmente, conservando tablas, hipervínculos y orden de lectura. No contiene imágenes en línea, cambios controlados, cuadros de texto, notas al pie ni comentarios detectados. Su único pie es numeración de página. No se realizó revisión visual paginada: el runtime disponible no incluye el renderizador LibreOffice empaquetado. No se infirieron números de página a partir de esa estructura.</p></section>'''
    body += '''<section><h2>Cómo incorporarla después de la revisión</h2><ol>
<li>En la administración de Gianna, importar el archivo <strong>Invest_Lavalleja_2026_10_19_consolidado.gianna.json</strong> como una base nueva. No cargar este informe ni los JSON de validación como conocimiento.</li>
<li>Revisar los 332 candidatos públicos, sus fuentes, fechas, hipótesis y restricciones. Los 75 internos deben continuar internos. La importación por sí sola no aprueba contenido.</li>
<li>Tras aprobación editorial, construir una versión nueva con Bekko, Horizon y LanceDB. No reutilizar los vectores de la base anterior para los textos nuevos.</li>
<li>Probar consultas y respuestas con citas en la versión de prueba. Confirmar especialmente los datos temporales y casos prediales.</li>
<li>Publicar sólo cuando se autorice, conservando la versión anterior para reversión. Esta entrega no ejecuta ninguno de esos cambios en el portal.</li></ol>
<p>El paquete se mantiene fuera de Git y fuera de public/: incluye material interno. Los scripts se pueden versionar; los archivos de conocimiento y resultados locales están protegidos mediante better-rag/.gitignore.</p></section>'''
    if publication:
        body = body.replace('Cómo incorporarla después de la revisión', 'Procedimiento de incorporación y futuras actualizaciones')
        body = body.replace('Esta entrega no ejecuta ninguno de esos cambios en el portal.', 'La publicación de esta versión se realizó después de la solicitud explícita del usuario y está registrada al inicio del informe.')
    body += '<section><h2>Inventario de las incorporaciones</h2>'
    additions = corpus['records'][271:]
    body += table(['ID', 'Título', 'Evidencia', 'Fuentes'], [(r['id'], r['title'], r['evidence_type'], ', '.join(r['source_refs'])) for r in additions])
    body += '</section><footer>Documento local de revisión. No es publicación, dictamen legal ni certificación de oportunidades disponibles.</footer>'
    output = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Consolidación de conocimiento · Invest Lavalleja</title><style>
body{font:16px/1.6 system-ui,sans-serif;color:#173b32;background:#f5f8f6;max-width:1200px;margin:0 auto;padding:40px 24px}header,section{background:white;border:1px solid #d7e3dc;border-radius:12px;padding:28px;margin-bottom:24px}h1{font-size:2.5rem;line-height:1.15}h2{font-size:1.5rem;margin-top:0}a{color:#08634c}a:focus-visible{outline:3px solid #aa5b00;outline-offset:4px}.eyebrow{letter-spacing:.12em;font-size:.85rem}.notice{background:#fff2d6;padding:16px;border-left:4px solid #a56c00}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #dae4de}th{background:#eaf4ed}td:first-child{font-weight:600}li{margin:8px 0}footer{font-size:.9rem;padding-bottom:30px}@media print{body{padding:0;background:white;max-width:none}header,section{padding:12px;border:0;border-radius:0}.scroll{overflow:visible}tr{break-inside:avoid}h2{break-after:avoid}a{color:inherit}}
</style><main>''' + body + '</main></html>'
    (FOLDER / 'Informe_consolidacion.html').write_text(output, encoding='utf-8')
    manifest['status'] = 'validated_schema_import_roundtrip_native_index_and_retrieval; editorial approval required'
    manifest['validation'] = {'import_checks': basic['checks_passed'], 'conversion_regression_tests': regression['tests_run'],
                              'chunks': native_data['index']['chunks'], 'max_tokens': native_data['index']['max_tokens'],
                              'retrieval_expected_in_context': native_data['expected_in_context'],
                              'retrieval_cases': native_data['total_cases'], 'provider_calls': 0,
                              'live_version_before': live['before'], 'live_version_after': live['after']}
    manifest['artifacts'] = {name: {'sha256': hashlib.sha256((FOLDER / name).read_bytes()).hexdigest(), 'bytes': (FOLDER / name).stat().st_size}
                             for name in ('comparacion-y-trazabilidad.json', 'validacion-importador.json', 'validacion-nativa.json', 'regresiones-conversion.json', 'Informe_consolidacion.html', 'comprobacion-base-activa.json')}
    if publication:
        manifest['active_knowledge_changed'] = True
        manifest['status'] = 'published_at_explicit_user_request; previous_version_retained'
        manifest['publication'] = {'version_id': publication['operation']['version_id'],
                                   'previous_version': publication['operation']['previous_version'],
                                   'activated_at': publication['operation']['activated_at'],
                                   'retrieval_passed': publication['retrieval']['passed'],
                                   'retrieval_total': publication['retrieval']['total']}
        manifest['artifacts']['publicacion.json'] = {'sha256': hashlib.sha256((FOLDER / 'publicacion.json').read_bytes()).hexdigest(),
                                                     'bytes': (FOLDER / 'publicacion.json').stat().st_size}
    (FOLDER / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest['validation']))


if __name__ == '__main__':
    main()
