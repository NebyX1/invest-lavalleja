"""Query interpretation and evidence needs. These hints never become sources."""
import re
from .conversation import fold


FACETS={
    'premises':('Uso del suelo, local y padrón antes de comprar o alquilar',
        re.compile(r'uso y construccion|suelo y edificacion')),
    'safety':('Incendios, seguridad, proyecto y condiciones de Bomberos',
        re.compile(r'incendios y seguridad')),
    'food':('Alimentos, habilitación bromatológica, RUNAEV empresa y local',
        re.compile(r'permiso correcto.*alimentos|frente alimentos|runaev')),
    'water':('Agua y descarga, disponibilidad, calidad y tratamiento de efluentes',
        re.compile(r'agua y descarga|soluciones de agua y efluentes')),
    'business':('Comparación económica de alquiler, adecuación, costos y demanda',
        re.compile(r'comparacion economica correcta|probar demanda|punto de equilibrio|costos.*caja')),
    'permits':('Una habilitación no reemplaza otra; constituir sociedad no autoriza operar',
        re.compile(r'una habilitacion no reemplaza|constitucion de una sociedad no autoriza')),
}


def requests_next_step(text):
    return bool(re.search(r'\b(?:como (?:arranco|empiezo|empezar)|por donde (?:empiezo|empezar)|'
                         r'(?:primer|siguiente|proximo) paso|que hago ahora)\b',fold(text)))


def activity_plan(text):
    value=fold(text);activity='';clarification='';facets=[]
    if re.search(r'\bboliche\w*\b',value):
        # Boliche is a regional term for a bar, pub or dance venue; the answer
        # covers those formats instead of interrogating the person first.
        activity='local de ocio nocturno (bar, pub o local bailable)'
        facets=['premises','safety','business']
    elif re.search(r'\b(?:discoteca\w*|bailable\w*|pub|baile|nocturn\w*)\b',value):
        activity='local bailable o de ocio nocturno';facets=['premises','safety','business']
    elif re.search(r'\b(?:bar|bares|restaur\w*|gastronom\w*|cafeteria\w*|parador\w*)\b',value):
        activity='bar o establecimiento gastronómico';facets=['premises','food','safety']
    elif re.search(r'\b(?:hotel\w*|hostel\w*|caban\w*|alojamiento\w*|posada\w*)\b',value):
        activity='alojamiento u hospitalidad';facets=['premises','safety']
    elif re.search(r'\b(?:agua|efluentes|descarga)\b',value):facets=['water']
    elif re.search(r'\b(?:terreno|padron|comprar|alquilar|arrendar)\b',value):facets=['premises','business']
    if re.search(r'\b(?:sociedad|sociedades|registrar|habilitacion)\b',value) and re.search(r'\b(?:abrir|operar|habilit|permiso)\w*\b',value):
        facets.append('permits')
    return activity,tuple(dict.fromkeys(facets)),clarification


def matches_facet(record,facet):
    pattern=FACETS[facet][1]
    return bool(pattern.search(fold(record.get('title','')+' '+record.get('text',''))))


def policy_for(plan):
    """Task-specific guidance. It describes what a useful answer contains, not which topics are allowed."""
    if plan.intent=='locations':
        return ('TAREA: la persona busca dónde y qué ofrece cada lugar. Dale información, no un trámite: presentá las '
            'zonas o localidades de Lavalleja cuyo perfil documentado encaja y, para cada una, qué experiencia, público '
            'o ventaja ofrece para esa actividad según la base de conocimiento (vocación turística, gastronomía, '
            'movimiento comercial, paisaje, accesos, antecedentes). Si hay varias, decí que hay varias opciones y '
            'compará para que pueda elegir. Abrí con las zonas y lo que ofrecen, también cuando la base no trate la '
            'actividad exacta (en ese caso sumá al final, en una frase, que no trae datos específicos de esa actividad); '
            'nunca abras con una negación. Presentá las zonas cuyo perfil documentado encaja con la actividad y explicá '
            'por qué encajan; no uses una zona si la base no dice nada que la vincule. Los permisos y condiciones van al '
            'final, en una o dos frases, y solo si cambian dónde conviene; no le expliques qué debería definir antes ni '
            'le propongas pasos.')
    if plan.intent=='requirements':
        return ('TAREA: la persona quiere saber qué permisos, habilitaciones o comprobaciones corresponden. '
            'Explicalos en un orden lógico, separando lo general de lo específico de la actividad, y aclará '
            'qué organismo o instancia interviene cuando la base lo indica.')
    if plan.next_step:
        return ('TAREA: la persona pregunta cómo avanzar con la opción en foco. Ordená en pocos puntos claros '
            'los pasos que surgen de la base de conocimiento; si la base no describe un procedimiento, decilo '
            'y contá las comprobaciones previas que sí figuran.')
    if plan.intent=='develop':
        return ('TAREA: la persona quiere profundizar en algo que ya se le contó. Retomá esa opción o zona sin repetir '
            'lo ya presentado y sumá lo nuevo y útil: en qué consiste, qué experiencia o perfil ofrece, qué condiciones '
            'tiene y qué cambia según la base de conocimiento.')
    if plan.intent in {'recommend','explore'}:
        return ('TAREA: la persona explora oportunidades o pide una orientación. Presentá las opciones o zonas más '
            'pertinentes que surgen de la base de conocimiento, cada una con su ventaja principal, y ayudá a '
            'compararlas. Podés destacar cuál parece más afín a lo que la persona describió, explicando por qué '
            'con datos de la base.')
    return ('TAREA: respondé de forma directa y completa lo que se pregunta; sumá solo el contexto que ayuda a '
        'entender o usar la información.')


