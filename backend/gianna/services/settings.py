from pydantic import BaseModel, ConfigDict, Field
from ..db import dumps

LEGACY_PERSONA='Sos Gianna, la asistente de inversiones de Lavalleja. Usá español claro, trato cercano y profesional. Ayudá a identificar oportunidades y próximos pasos sin inventar certezas.'
PREVIOUS_INFORMATION_PERSONA='Sos Gianna, asistente de información sobre desarrollo económico de Lavalleja. Respondé únicamente la información solicitada, con tono institucional cordial y sencillo. No asesores inversiones, no agregues consejos o preguntas no pedidos y reconocé brevemente cuando no contás con el dato.'
INFORMATION_ONLY_PERSONA='Sos Gianna, asistente de información sobre inversiones en Lavalleja. Respondé únicamente la información solicitada, con tono institucional cordial y sencillo. No asesores inversiones, no agregues consejos o preguntas no pedidos y reconocé brevemente cuando no contás con el dato.'
DEFAULT_PERSONA='Sos Gianna, la asistente de Invest Lavalleja. Ayudás a inversores y emprendedores a entender qué oportunidades, zonas y condiciones existen en Lavalleja. Hablás en español rioplatense, con trato cercano y profesional, y respondés con claridad usando solo lo que figura en tu base de conocimiento.'
DEFAULT_GREETING='¿Qué información sobre inversiones en Lavalleja necesitás consultar?'
PREVIOUS_INFORMATION_GREETING='¿Qué información sobre Lavalleja necesitás consultar?'
LEGACY_GREETING='¿Qué proyecto tenés en mente? Te ayudo a explorar la guía y sus fuentes.'

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    brand_name: str=Field(default='Gianna · Invest Lavalleja',min_length=2,max_length=100)
    greeting: str=Field(default=DEFAULT_GREETING,max_length=500)
    persona: str=Field(default=DEFAULT_PERSONA,max_length=5000)
    model: str=Field(default='',max_length=160,pattern=r'^[a-zA-Z0-9_.:/-]*$')
    temperature: float=Field(default=0.1,ge=0,le=1)
    max_output_tokens: int=Field(default=950,ge=100,le=8192)
    retrieval_candidates: int=Field(default=20,ge=5,le=60)
    retrieval_limit: int=Field(default=8,ge=2,le=20)
    rerank_candidates: int=Field(default=16,ge=8,le=40)
    max_context_records: int=Field(default=8,ge=1,le=10)
    max_context_chars: int=Field(default=20000,ge=4000,le=40000)
    chunk_tokens: int=Field(default=420,ge=180,le=480)
    overlap_tokens: int=Field(default=40,ge=0,le=80)
    query_per_minute: int=Field(default=8,ge=1,le=30)
    global_queries_per_minute: int=Field(default=40,ge=1,le=240)
    daily_query_budget: int=Field(default=1000,ge=10,le=50000)
    chat_history_hours: int=Field(default=24,ge=1,le=168)
    analytics_days: int=Field(default=30,ge=1,le=180)
    chat_enabled: bool=True
    knowledge_notice: str=Field(default='Orientación basada en documentación. La elegibilidad, los permisos y las condiciones de cada proyecto deben confirmarse con los organismos competentes.',max_length=1000)


def get_settings(db,cfg):
    values=dict(db.setting('runtime',{'model':cfg.ollama_model}))
    # Upgrade only the exact former defaults; custom editorial settings survive.
    if values.get('persona') in {LEGACY_PERSONA,PREVIOUS_INFORMATION_PERSONA,INFORMATION_ONLY_PERSONA}:values['persona']=DEFAULT_PERSONA
    if values.get('greeting') in {LEGACY_GREETING,PREVIOUS_INFORMATION_GREETING}:values['greeting']=DEFAULT_GREETING
    return Settings.model_validate(values)


def save_settings(db,cfg,values,actor):
    settings=Settings.model_validate(values)
    db.execute('INSERT INTO settings(`key`,value) VALUES(?,?) ON CONFLICT(`key`) DO UPDATE SET value=excluded.value',('runtime',dumps(settings.model_dump())))
    db.audit(actor,'SETTINGS_CHANGED',details={'fields':sorted(values)})
    return settings
