FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .


RUN find . -type d -name "__pycache__" -exec rm -rf {} +

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn_config.py", "run:app"]