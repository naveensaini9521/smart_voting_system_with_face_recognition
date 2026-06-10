FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY app.py .
COPY run.py .
COPY config.py .
COPY extensions.py .
COPY broadcast.py .
COPY mongo_models.py .
COPY gunicorn_config.py .
COPY socket_events.py .
COPY routes/ routes/
COPY services/ services/
COPY utils/ utils/

RUN find /usr/local -type d -name "__pycache__" -exec rm -rf {} + || true && \
    find /usr/local -name "*.pyc" -delete && \
    find /usr/local -name "*.pyo" -delete

RUN rm -rf /root/.cache/pip

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn_config.py", "run:app"]