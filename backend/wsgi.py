import logging
from gianna import create_app
from gianna.observability import configure_logging, event, safe_exception

configure_logging()
LOG = logging.getLogger('gianna.startup')
event(LOG, 'process.starting')
try:
    app = create_app()
    configure_logging(app.extensions['gianna'].cfg)
    event(LOG, 'process.http_initialized')
except Exception as exc:
    event(LOG, 'process.startup_failed', level=logging.ERROR, exception=safe_exception(exc))
    raise
