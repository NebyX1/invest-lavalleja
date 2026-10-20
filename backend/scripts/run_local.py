#!/usr/bin/env python3
"""Development server only. Production uses Gunicorn and the trusted HTTPS proxy."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env')
os.environ['FLASK_ENV']='development'
os.environ['PROXY_HOPS']='0'
# Same CPU limits as the Docker image, without requiring them in .env.
for name,value in {'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'}.items():
    os.environ.setdefault(name,value)
from gianna import create_app
app=create_app()
if __name__=='__main__':
    services=app.extensions['gianna']
    if services.cfg.worker_enabled:services.jobs.start()
    app.run(host='127.0.0.1',port=8000,debug=False,use_reloader=False,threaded=True)
