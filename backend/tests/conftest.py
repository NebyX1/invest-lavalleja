from pathlib import Path
from types import SimpleNamespace
import secrets
import pytest
from cryptography.fernet import Fernet
from gianna.config import Config
from gianna.db import Database
from gianna.security import Security
from gianna.corpus import Corpus,DocumentInfo,Record,Source
from gianna.services.knowledge import Knowledge

@pytest.fixture
def cfg(tmp_path):
    return Config.from_env(dict(data_dir=tmp_path,secret_key=secrets.token_urlsafe(48),encryption_key=Fernet.generate_key().decode(),
        production=False,trusted_hosts=('localhost','127.0.0.1'),proxy_hops=0,worker_enabled=False,smtp_host='smtp.example.test',smtp_from='test@example.test',
        public_origins=('http://localhost',),ollama_api_key='test-not-a-real-token'))

@pytest.fixture
def db(cfg):
    result=Database(cfg.db_path);result.migrate();return result

@pytest.fixture
def security(db,cfg):return Security(db,cfg,lambda address,code:None)

@pytest.fixture
def knowledge(db,cfg):return Knowledge(db,cfg)

@pytest.fixture
def corpus():
    return Corpus(document=DocumentInfo(id='example',title='Guía de prueba',cutoff_date='2026-09-18'),
        sources=[Source(id='S01',title='Fuente de prueba',url='https://example.test/fuente')],records=[
            Record(id='public-1',title='Oportunidad de prueba',topic='Turismo',audience='public',evidence_type='hypothesis',
                text='La oportunidad es una hipótesis. Requiere permiso por padrón. '+('Una frase sobre los requisitos y la evidencia. '*80),conditions=['No garantiza permisos ni retorno.'],source_refs=['S01'],cutoff_date='2026-09-18'),
            Record(id='internal-1',title='Diseño interno',topic='Administración',audience='internal',text='Este contenido no debe publicarse.',evidence_type='institutional_proposal')])
