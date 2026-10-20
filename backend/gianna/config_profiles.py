"""Deployment profiles: operational defaults belong in code, not in every .env."""


class DevelopmentConfig:
    production = False
    proxy_hops = 0
    public_origins = (
        'http://localhost:4321', 'http://127.0.0.1:4321',
        'http://localhost:8000', 'http://127.0.0.1:8000',
    )


class ProductionConfig:
    production = True
    # Compose exposes the API only to Coolify's HTTPS reverse proxy.
    proxy_hops = 1
    public_origins = ()


class TestingConfig(DevelopmentConfig):
    pass


PROFILES = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}
