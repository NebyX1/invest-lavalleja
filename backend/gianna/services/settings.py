from pydantic import BaseModel, ConfigDict, Field
from ..db import dumps

DEFAULT_PERSONA='Sos Gianna, la asistente de inversiones de Lavalleja. Usá español claro, trato cercano y profesional. Ayudá a identificar oportunidades y próximos pasos sin inventar certezas.'

class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    brand_name: str=Field(default='Gianna · Invest Lavalleja',min_length=2,max_length=100)
    greeting: str=Field(default='¿Qué proyecto tenés en mente? Te ayudo a explorar la guía y sus fuentes.',max_length=500)
    persona: str=Field(default=DEFAULT_PERSONA,max_length=5000)
    model: str=Field(default='',max_length=160,pattern=r'^[a-zA-Z0-9_.:/-]*$')
    temperature: float=Field(default=0.1,ge=0,le=1)
    max_output_tokens: int=Field(default=750,ge=100,le=2000)
    retrieval_candidates: int=Field(default=20,ge=5,le=60)
    retrieval_limit: int=Field(default=8,ge=2,le=20)
    max_context_records: int=Field(default=5,ge=1,le=10)
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
    return Settings.model_validate(db.setting('runtime',{'model':cfg.ollama_model}))


def save_settings(db,cfg,values,actor):
    settings=Settings.model_validate(values)
    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('runtime',dumps(settings.model_dump())))
    db.audit(actor,'SETTINGS_CHANGED',details={'fields':sorted(values)})
    return settings
