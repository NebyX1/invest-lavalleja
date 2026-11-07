"""One process, one cached model pair per requested profile, one recovery worker."""
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
# Gunicorn 26 enables a control socket under $HOME by default. The container is
# intentionally read-only and this deployment does not use that interface.
control_socket_disable=True
# Health/admin access logs can expose query-string contents; application audit is the primary trace.
accesslog=None
errorlog='-'
loglevel='info'

def post_worker_init(worker):
    import logging
    from gianna.observability import configure_logging, event
    services=worker.wsgi.extensions['gianna']
    configure_logging(services.cfg)
    event(logging.getLogger('gianna.process'), 'worker.started', worker_enabled=services.cfg.worker_enabled)
    if services.cfg.worker_enabled:services.jobs.start()

def worker_exit(server,worker):
    try:
        import logging
        from gianna.observability import event
        event(logging.getLogger('gianna.process'), 'worker.stopping')
        services=worker.wsgi.extensions['gianna'];services.jobs.stop_event.set();services.jobs.wake.set()
    except AttributeError:pass
