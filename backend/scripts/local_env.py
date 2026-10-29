"""Entorno local nativo (sin Docker) para scripts y la API de prueba humana."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def prepare():
    sys.path.insert(0, str(BACKEND))
    for name, value in {'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '1',
                        'MKL_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false'}.items():
        os.environ.setdefault(name, value)
    from dotenv import load_dotenv
    load_dotenv(BACKEND / '.env')
    # Fuera del contenedor, host.docker.internal no resuelve hacia MariaDB.
    url = os.environ.get('DATABASE_URL', '')
    if 'host.docker.internal' in url:
        os.environ['DATABASE_URL'] = url.replace('host.docker.internal', '127.0.0.1')
    os.environ['FLASK_ENV'] = 'development'
    os.environ['PROXY_HOPS'] = '0'
    return BACKEND
