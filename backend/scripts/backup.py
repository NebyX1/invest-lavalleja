#!/usr/bin/env python3
"""Administrative SQLite backup. Treat the result as confidential and retain its encryption key separately."""
from pathlib import Path
import argparse
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gianna.config import Config
from gianna.db import Database


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    cfg=Config.from_env();dest=Path(args.output).resolve()
    if dest.exists():raise SystemExit('El destino ya existe; no se sobrescribió.')
    dest.parent.mkdir(parents=True,exist_ok=True)
    Database(cfg.db_path).backup(dest);dest.chmod(0o600)
    print(f'Respaldo SQLite creado en {dest}. Es confidencial.')
    print('No incluye Qdrant, modelos ni .env. Leé docs/SEGURIDAD_Y_OPERACION.md para respaldo/restauración completa.')

if __name__=='__main__':main()
