FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# pg_dump для бэкапов (версия 15, как у сервера базы)
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
RUN useradd -u 1000 -m bot && mkdir -p /backups /shared && chown -R bot:bot /backups /shared
USER bot

CMD ["python", "-m", "app"]
