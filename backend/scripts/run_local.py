#!/usr/bin/env python3
"""Servidor de desarrollo nativo. Producción usa Gunicorn y el proxy HTTPS de confianza.

Uso: python scripts/run_local.py [--port 8001] [--human-test]
"""
import argparse
import os

import local_env

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8000)
parser.add_argument('--human-test', action='store_true', help='Prueba humana local con orígenes de loopback.')
args = parser.parse_args()
local_env.prepare()
if args.human_test:
    os.environ['GIANNA_HUMAN_TEST_MODE'] = 'true'
    os.environ['CORS_ORIGINS'] = ('http://localhost:4321,http://127.0.0.1:4321,'
                                  f'http://localhost:{args.port},http://127.0.0.1:{args.port}')

from gianna import create_app

app = create_app()
if __name__ == '__main__':
    services = app.extensions['gianna']
    if services.cfg.worker_enabled:
        services.jobs.start()
    app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False, threaded=True)
