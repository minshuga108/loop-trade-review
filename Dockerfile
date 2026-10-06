# Loop: always-on, read-only review app (FastAPI). No keys are baked in.
#
# Layout inside the image matches the repo's expectations:
#   /srv/loop                    this repository (app/, engine/, adapters/, eval/, LOSSES.md)
#   /srv/data/trader_samples     the anonymised wallet CSVs (app/service.py reads parents[2]/data/trader_samples)
# Build after running:  python scripts/prepare_samples.py
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# uid 1000: Hugging Face Spaces runs containers as this user; harmless elsewhere
RUN useradd --create-home --uid 1000 loop
WORKDIR /srv/loop

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=loop:loop deploy_data/trader_samples /srv/data/trader_samples
COPY --chown=loop:loop . /srv/loop
RUN mkdir -p /srv/loop/data/snapshots && chown -R loop:loop /srv/loop/data

USER loop
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"

# One worker: the rulebook sandbox and the selftest state live in process memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
