from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import os
from .config_profiles import PROFILES

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def env_value(env, name, legacy=None, default=''):
    """Canonical names win; old installations can migrate without a flag day."""
    if name in env:
        return env[name]
    return env.get(legacy, default) if legacy else default


def boolean(value, name):
    normalized = str(value).strip().lower()
    if normalized not in {'true', 'false', '1', '0', 'yes', 'no', 't', 'f'}:
        raise ValueError(f'{name} debe ser True o False.')
    return normalized in {'true', '1', 'yes', 't'}


def mail_mode(env):
    if 'MAIL_USE_TLS' not in env and 'MAIL_USE_SSL' not in env and 'SMTP_MODE' in env:
        return env['SMTP_MODE']
    use_ssl = boolean(env.get('MAIL_USE_SSL', 'False'), 'MAIL_USE_SSL')
    use_tls = boolean(env.get('MAIL_USE_TLS', str(not use_ssl)), 'MAIL_USE_TLS')
    if use_ssl and use_tls:
        raise ValueError('MAIL_USE_TLS y MAIL_USE_SSL no pueden estar habilitados a la vez.')
    return 'ssl' if use_ssl else 'starttls' if use_tls else 'plain'


@dataclass(frozen=True)
class Config:
    data_dir: Path
    secret_key: str = field(repr=False)
    encryption_key: str = field(repr=False)
    database_url: str = field(default='', repr=False)
    production: bool = True
    human_test_mode: bool = False
    ollama_url: str = 'https://ollama.com'
    ollama_api_key: str = field(default='', repr=False)
    ollama_model: str = ''
    public_origins: tuple[str, ...] = ()
    trusted_hosts: tuple[str, ...] = ()
    proxy_hops: int = 0
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = field(default='', repr=False)
    smtp_from: str = ''
    smtp_mode: str = 'starttls'
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
    def database_target(self):
        # SQLite remains a test/one-time-import adapter; deployed profiles require MariaDB.
        return self.database_url or self.db_path

    @property
    def model_dir(self):
        return self.data_dir / 'models'

    @property
    def lance_dir(self):
        return self.data_dir / 'lance'

    @classmethod
    def from_env(cls, overrides=None, *, environ=None):
        from dotenv import load_dotenv
        if environ is None:
            # Never depend on the directory from which a CLI or WSGI server starts.
            load_dotenv(BACKEND_ROOT / '.env')
        env = os.environ if environ is None else environ
        profile_name = str(env_value(env, 'FLASK_ENV', 'APP_ENV', 'production')).strip().lower()
        if profile_name not in PROFILES:
            raise ValueError('FLASK_ENV debe ser production, development o testing.')
        profile = PROFILES[profile_name]
        def truth(key, default='true'):
            return boolean(env.get(key, default), key)
        origins = tuple(x.strip().rstrip('/') for x in
            env_value(env, 'CORS_ORIGINS', 'PUBLIC_ORIGINS', ','.join(profile.public_origins)).split(',') if x.strip())
        # The API's HTTPS origin belongs in CORS_ORIGINS too when using a separate domain.
        # Host trust is configuration-derived, never taken from an incoming header.
        hosts = tuple(dict.fromkeys(('localhost', '127.0.0.1',
                                     *(urlparse(origin).hostname for origin in origins if urlparse(origin).hostname))))
        mode = mail_mode(env)
        data = dict(
            data_dir=Path(env.get('DATA_DIR', BACKEND_ROOT / 'data')).resolve(),
            secret_key=env.get('SECRET_KEY', ''),
            encryption_key=env.get('ENCRYPTION_KEY', ''),
            database_url=env.get('DATABASE_URL', '').strip(),
            production=profile.production,
            human_test_mode=truth('GIANNA_HUMAN_TEST_MODE', 'false'),
            ollama_url=env_value(env, 'OLLAMA_HOST', 'OLLAMA_BASE_URL', 'https://ollama.com').rstrip('/'),
            ollama_api_key=env.get('OLLAMA_API_KEY', ''),
            ollama_model=env.get('OLLAMA_MODEL', ''),
            public_origins=origins,
            trusted_hosts=tuple(x.strip() for x in env['TRUSTED_HOSTS'].split(',') if x.strip()) if 'TRUSTED_HOSTS' in env else hosts,
            proxy_hops=int(env.get('PROXY_HOPS', str(profile.proxy_hops))),
            smtp_host=env_value(env, 'MAIL_SERVER', 'SMTP_HOST'),
            smtp_port=int(env_value(env, 'MAIL_PORT', 'SMTP_PORT', '465' if mode == 'ssl' else '587')),
            smtp_username=env_value(env, 'MAIL_USERNAME', 'SMTP_USERNAME'),
            smtp_password=env_value(env, 'MAIL_PASSWORD', 'SMTP_PASSWORD'),
            smtp_from=env_value(env, 'MAIL_DEFAULT_SENDER', 'SMTP_FROM'), smtp_mode=mode,
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
        if not cfg.database_url:
            if profile_name != 'testing':
                raise ValueError('DATABASE_URL debe apuntar a la base MariaDB de Gianna.')
        else:
            database = urlparse(cfg.database_url)
            if database.scheme not in {'mariadb+mariadbconnector', 'sqlite'}:
                raise ValueError('DATABASE_URL debe usar mariadb+mariadbconnector.')
            if database.scheme == 'sqlite' and profile_name != 'testing':
                raise ValueError('SQLite solo se admite en pruebas automatizadas; usá MariaDB.')
            if database.scheme.startswith('mariadb') and (not database.hostname or not database.path.strip('/')):
                raise ValueError('DATABASE_URL requiere host y nombre de base.')
        from cryptography.fernet import Fernet
        Fernet(cfg.encryption_key.encode())
        if cfg.production and (not cfg.trusted_hosts or not cfg.public_origins):
            raise ValueError('Configurá CORS_ORIGINS con los orígenes HTTPS del portal y de la API.')
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
                raise ValueError('CORS_ORIGINS acepta orígenes exactos, sin rutas ni comodines.')
            if '*' in origin or (cfg.production and p.scheme != 'https'):
                raise ValueError('Los orígenes públicos de producción deben usar HTTPS y no comodines.')
            if p.username or p.password:
                raise ValueError('CORS_ORIGINS no acepta credenciales en los orígenes.')
            try:
                p.port
            except ValueError:
                raise ValueError('CORS_ORIGINS contiene un puerto inválido.') from None
        provider = urlparse(cfg.ollama_url)
        if not provider.hostname or provider.scheme not in {'http', 'https'} or provider.username or provider.password or provider.query or provider.fragment or provider.path not in {'', '/'}:
            raise ValueError('OLLAMA_HOST debe ser un origen HTTP(S) válido, sin rutas ni credenciales.')
        if cfg.production and provider.scheme != 'https':
            raise ValueError('Ollama Cloud requiere HTTPS en producción.')
        if cfg.smtp_mode not in {'starttls','ssl','plain'}:
            raise ValueError('La configuración de correo no es válida.')
        if cfg.production and cfg.smtp_host and cfg.smtp_mode == 'plain':
            raise ValueError('El correo de producción requiere MAIL_USE_TLS=True o MAIL_USE_SSL=True.')
        if not 1 <= cfg.smtp_port <= 65535:
            raise ValueError('MAIL_PORT fuera de rango.')
        if not 1 <= cfg.embedding_threads <= 8 or not 1 <= cfg.embedding_batch_size <= 64:
            raise ValueError('Perfil de CPU fuera de rango.')
        if not 1 <= cfg.max_concurrent_chat <= 16:
            raise ValueError('MAX_CONCURRENT_CHAT fuera de rango.')
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        for sub in ('uploads','exports','models'):
            (cfg.data_dir/sub).mkdir(exist_ok=True)
        return cfg
