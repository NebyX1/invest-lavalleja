#!/usr/bin/env python3
"""Create an untracked .env with new keys; never prints credentials or overwrites an existing file."""
from pathlib import Path
import argparse
import base64
import os
import secrets


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--local',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];dest=root/'.env'
    if dest.exists():raise SystemExit('.env ya existe. No se sobrescribió ni se rotaron claves.')
    content=(root/'.env.example').read_text(encoding='utf8')
    values={'SECRET_KEY':secrets.token_urlsafe(64),'ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}
    if args.local:values.update(FLASK_ENV='development',
        CORS_ORIGINS='http://localhost:8000,http://127.0.0.1:8000,http://localhost:4321,http://127.0.0.1:4321')
    lines=[]
    for line in content.splitlines():
        key=line.split('=',1)[0]
        lines.append(f'{key}={values[key]}' if key in values else line)
    fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as stream:stream.write('\n'.join(lines)+'\n')
    print('.env creado con secretos nuevos. Configurá DATABASE_URL MariaDB, OLLAMA_API_KEY y dominios; no lo subas a Git.')
    print('No cambies ENCRYPTION_KEY sin un plan de migración: protege TOTP y contexto de chat.')

if __name__=='__main__':main()
