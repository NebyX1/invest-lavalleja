"""Resolve the backend checkout used by the RAG maintenance tools."""
import os
from pathlib import Path
import sys


def add_backend_path(tool_file):
    repo_root = Path(tool_file).resolve().parents[2]
    configured = os.environ.get('GIANNA_BACKEND_ROOT', '').strip()
    candidates = [Path(configured).expanduser()] if configured else [
        repo_root / 'backend',
        repo_root.parent / 'invest-lavalleja-backend',
    ]
    for candidate in candidates:
        backend_root = candidate.resolve()
        if (backend_root / 'gianna').is_dir() and (backend_root / 'scripts').is_dir():
            sys.path.insert(0, str(backend_root))
            return repo_root
    raise SystemExit(
        'No se encontró el backend de Gianna. Definí GIANNA_BACKEND_ROOT con la ruta '
        'del repositorio backend o clonalo junto al frontend.'
    )
