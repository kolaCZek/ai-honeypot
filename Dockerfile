FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install \
      "fastapi>=0.115" "uvicorn[standard]>=0.32" "httpx>=0.27" \
      "sqlalchemy>=2.0" "aiosqlite>=0.20" "redis>=5.2" \
      "pydantic>=2.9" "pyyaml>=6.0" "jinja2>=3.1" \
      "prometheus-client>=0.21" "ua-parser>=0.18" \
      "python-multipart>=0.0.12" "beautifulsoup4>=4.12"

COPY honeypot/ ./honeypot/
COPY dashboard/ ./dashboard/
COPY shared/ ./shared/

ENV CONFIG_PATH=/config/config.yaml
VOLUME ["/data", "/config"]

# Default cmd overridden by docker-compose
CMD ["uvicorn", "honeypot.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8888"]
