"""Gianna Invest: Flask is imported only when the web application starts."""
__version__ = '1.0.0-rc1'


def create_app(overrides=None):
    from .web import create_app as factory
    return factory(overrides)
