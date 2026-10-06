FROM python:3.12-slim

WORKDIR /app

# System dependencies for psycopg (PostgreSQL driver)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[dev]" && \
    pip install --no-cache-dir gunicorn

# Copy application code
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY app/ ./app/
COPY scripts/ ./scripts/

# Create keys directory (mounted at runtime via Docker secret or volume)
RUN mkdir -p ./keys && chmod 700 ./keys

# Run migrations and start server
EXPOSE 8000
CMD ["python", "scripts/start_production.py"]
