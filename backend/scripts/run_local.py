#!/usr/bin/env python3
"""Development server only. Production uses Gunicorn and the trusted HTTPS proxy."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
os.environ['APP_ENV']='development'
os.environ['PROXY_HOPS']='0'
from gianna import create_app
app=create_app()
if __name__=='__main__':
    services=app.extensions['gianna']
    if services.cfg.worker_enabled:services.jobs.start()
    app.run(host='127.0.0.1',port=8000,debug=False,use_reloader=False,threaded=True)
