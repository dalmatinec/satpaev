FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY poster ./poster
RUN useradd -u 1000 -m poster && mkdir -p /session && chown -R poster:poster /session
USER poster

CMD ["python", "-m", "poster"]
