import logging
from gianna import create_app
logging.basicConfig(level=logging.WARNING,format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.getLogger('gianna').setLevel(logging.INFO)
app=create_app()
