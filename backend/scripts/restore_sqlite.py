#!/usr/bin/env python3
"""Offline restore only. Never accepts uploaded databases over HTTP."""
from pathlib import Path
import argparse
import shutil
import sqlite3
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gianna.config import Config


def main():
    p=argparse.ArgumentParser();p.add_argument('backup');p.add_argument('--confirm-api-stopped',action='store_true');p.add_argument('--confirm',action='store_true');a=p.parse_args()
    if not a.confirm or not a.confirm_api_stopped:raise SystemExit('Detené la API y agregá --confirm-api-stopped --confirm. No restaures con procesos abiertos.')
    source=Path(a.backup).resolve();cfg=Config.from_env()
    if not source.is_file() or source==cfg.db_path:raise SystemExit('Seleccioná un respaldo externo válido.')
    with sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('El respaldo no supera integrity_check.')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_versions'").fetchone():raise SystemExit('No es una base de Gianna.')
    if cfg.db_path.exists():shutil.copy2(cfg.db_path,cfg.db_path.with_suffix('.before-restore-'+str(int(time.time()))))
    for suffix in ('-wal','-shm'):Path(str(cfg.db_path)+suffix).unlink(missing_ok=True)
    shutil.copy2(source,cfg.db_path);cfg.db_path.chmod(0o600)
    with sqlite3.connect(cfg.db_path) as db:
        db.execute('DELETE FROM admin_sessions');db.execute('DELETE FROM auth_challenges');db.execute('DELETE FROM chat_sessions')
        db.execute('UPDATE active_knowledge SET version_id=NULL WHERE singleton=1')
        db.execute("UPDATE jobs SET status='cancelled',cancel_requested=1,message='Cancelado por restauración' WHERE status IN ('queued','running')")
        db.commit()
    print('Respaldo restaurado con sesiones revocadas y sin base publicada. Verificá Qdrant/modelo y publicá o reindexá desde el panel.')

if __name__=='__main__':main()
