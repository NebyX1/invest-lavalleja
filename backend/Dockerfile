FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/data/models/huggingface XDG_CACHE_HOME=/app/data/cache HF_XET_CACHE=/app/data/models/xet
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 gianna && useradd --uid 10001 --gid 10001 --create-home gianna \
    && mkdir -p /app/data && chown -R gianna:gianna /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=gianna:gianna gianna /app/gianna
COPY --chown=gianna:gianna scripts /app/scripts
COPY --chown=gianna:gianna wsgi.py gunicorn.conf.py /app/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=3)" || exit 1
CMD ["gunicorn","--config","gunicorn.conf.py","wsgi:app"]
