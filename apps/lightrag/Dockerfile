FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "lightrag-hku[api]" \
    neo4j \
    psycopg2-binary \
    asyncpg

COPY workspace_patch.py /app/workspace_patch.py

EXPOSE 9621

CMD ["python", "/app/workspace_patch.py", "--host", "0.0.0.0", "--port", "9621"]
