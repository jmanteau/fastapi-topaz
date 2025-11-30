FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster package management
RUN pip install --no-cache-dir uv

# Copy library source for build-time installation
COPY src/fastapi_topaz /fastapi-topaz/src/fastapi_topaz
COPY pyproject.toml README.md /fastapi-topaz/

# Copy webapp pyproject.toml and fix path for Docker build
COPY integration-tests/webapp/pyproject.toml ./
RUN sed -i 's|path = "../.."|path = "/fastapi-topaz"|' pyproject.toml

# Install all dependencies including fastapi-topaz
RUN uv sync --no-dev

# Remove library source (will be mounted at runtime for dev)
RUN rm -rf /fastapi-topaz

# Runtime mount will provide the library at /fastapi-topaz
ENV PYTHONPATH="/fastapi-topaz/src:${PYTHONPATH}"

# Copy application code
COPY integration-tests/webapp/app/ ./app/

# Copy Alembic configuration and migrations
COPY integration-tests/webapp/alembic.ini ./
COPY integration-tests/webapp/alembic/ ./alembic/

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
