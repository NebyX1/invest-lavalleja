from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import os


@dataclass(frozen=True)
class Config:
    data_dir: Path
    secret_key: str
    encryption_key: str
    production: bool = True
    human_test_mode: bool = False
    qdrant_url: str = 'http://qdrant:6333'
    qdrant_api_key: str = ''
    ollama_url: str = 'https://ollama.com'
    ollama_api_key: str = ''
    ollama_model: str = ''
    public_origins: tuple[str, ...] = ()
    trusted_hosts: tuple[str, ...] = ()
    proxy_hops: int = 0
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    smtp_mode: str = 'starttls'
    e5_revision: str = 'main'
    e5_model_file: str = 'onnx/model.onnx'
    embedding_threads: int = 2
    embedding_batch_size: int = 8
    max_upload_mb: int = 12
    max_records: int = 10000
    max_concurrent_chat: int = 3
    worker_enabled: bool = True

    @property
    def db_path(self):
        return self.data_dir / 'gianna.sqlite3'

    @property
    def model_dir(self):
        return self.data_dir / 'models'

    @classmethod
    def from_env(cls, overrides=None):
        from dotenv import load_dotenv
        load_dotenv()
        env = os.environ
        def truth(key, default='true'):
            return env.get(key, default).lower() in {'1', 'true', 'yes'}
        data = dict(
            data_dir=Path(env.get('DATA_DIR', './data')).resolve(),
            secret_key=env.get('SECRET_KEY', ''),
            encryption_key=env.get('ENCRYPTION_KEY', ''),
            production=env.get('APP_ENV', 'production') == 'production',
            human_test_mode=truth('GIANNA_HUMAN_TEST_MODE', 'false'),
            qdrant_url=env.get('QDRANT_URL', 'http://qdrant:6333').rstrip('/'),
            qdrant_api_key=env.get('QDRANT_API_KEY', ''),
            ollama_url=env.get('OLLAMA_BASE_URL', 'https://ollama.com').rstrip('/'),
            ollama_api_key=env.get('OLLAMA_API_KEY', ''),
            ollama_model=env.get('OLLAMA_MODEL', ''),
            public_origins=tuple(x.strip().rstrip('/') for x in env.get('PUBLIC_ORIGINS','').split(',') if x.strip()),
            trusted_hosts=tuple(x.strip() for x in env.get('TRUSTED_HOSTS','').split(',') if x.strip()),
            proxy_hops=int(env.get('PROXY_HOPS', '0')),
            smtp_host=env.get('SMTP_HOST',''), smtp_port=int(env.get('SMTP_PORT','587')),
            smtp_username=env.get('SMTP_USERNAME',''), smtp_password=env.get('SMTP_PASSWORD',''),
            smtp_from=env.get('SMTP_FROM',''), smtp_mode=env.get('SMTP_MODE','starttls'),
            e5_revision=env.get('E5_REVISION','main'),
            e5_model_file=env.get('E5_MODEL_FILE','onnx/model.onnx'),
            embedding_threads=int(env.get('EMBEDDING_THREADS','2')),
            embedding_batch_size=int(env.get('EMBEDDING_BATCH_SIZE','8')),
            max_upload_mb=int(env.get('MAX_UPLOAD_MB','12')),
            max_records=int(env.get('MAX_RECORDS','10000')),
            max_concurrent_chat=int(env.get('MAX_CONCURRENT_CHAT','3')),
            worker_enabled=truth('WORKER_ENABLED'),
        )
        data.update(overrides or {})
        cfg = cls(**data)
        if len(cfg.secret_key) < 32:
            raise ValueError('SECRET_KEY debe tener al menos 32 caracteres. Ejecutá scripts/setup_env.py.')
        from cryptography.fernet import Fernet
        Fernet(cfg.encryption_key.encode())
        if cfg.production and not cfg.trusted_hosts:
            raise ValueError('Configurá TRUSTED_HOSTS con el dominio del backend.')
        if cfg.human_test_mode:
            loopback = {'localhost', '127.0.0.1'}
            if cfg.production or not cfg.trusted_hosts or not set(cfg.trusted_hosts) <= loopback:
                raise ValueError('La prueba humana solo admite desarrollo y hosts locales.')
            if not cfg.public_origins or any(
                urlparse(origin).scheme != 'http' or urlparse(origin).hostname not in loopback
                for origin in cfg.public_origins
            ):
                raise ValueError('La prueba humana solo admite orígenes HTTP locales.')
        if not (0 <= cfg.proxy_hops <= 2):
            raise ValueError('PROXY_HOPS fuera de rango.')
        for origin in cfg.public_origins:
            p=urlparse(origin)
            if p.scheme not in {'http','https'} or not p.netloc or p.path not in {'','/'} or p.query or p.fragment:
                raise ValueError('PUBLIC_ORIGINS acepta orígenes exactos, sin rutas ni comodines.')
            if '*' in origin or (cfg.production and p.scheme != 'https'):
                raise ValueError('Los orígenes públicos de producción deben usar HTTPS y no comodines.')
        if cfg.production and urlparse(cfg.ollama_url).scheme != 'https':
            raise ValueError('Ollama Cloud requiere HTTPS en producción.')
        if cfg.smtp_mode not in {'starttls','ssl'}:
            raise ValueError('SMTP_MODE debe ser starttls o ssl.')
        if not 1 <= cfg.embedding_threads <= 8 or not 1 <= cfg.embedding_batch_size <= 64:
            raise ValueError('Perfil de CPU fuera de rango.')
        if not 1 <= cfg.max_concurrent_chat <= 16:
            raise ValueError('MAX_CONCURRENT_CHAT fuera de rango.')
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        for sub in ('uploads','exports','models'):
            (cfg.data_dir/sub).mkdir(exist_ok=True)
        return cfg
