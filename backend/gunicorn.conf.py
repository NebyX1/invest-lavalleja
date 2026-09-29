"""One process keeps one E5 instance and one local worker. Do not increase workers blindly."""
bind='0.0.0.0:8000'
workers=1
worker_class='gthread'
threads=6
preload_app=False
timeout=120
graceful_timeout=30
keepalive=5
max_requests=0
worker_tmp_dir='/tmp'
# Health/admin access logs can expose query-string contents; application audit is the primary trace.
accesslog=None
errorlog='-'
loglevel='info'

def post_worker_init(worker):
    services=worker.wsgi.extensions['gianna']
    if services.cfg.worker_enabled:services.jobs.start()

def worker_exit(server,worker):
    try:
        services=worker.wsgi.extensions['gianna'];services.jobs.stop_event.set();services.jobs.wake.set()
    except AttributeError:pass
