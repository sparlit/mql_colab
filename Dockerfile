FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Set Python environment for signal handling and unbuffered output
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONTRACEBACK=1

# Copy requirements first for better Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p brain_data/logs models data

# Expose ports: 8050 (Flask/web), 9090 (prometheus scraped externally)
EXPOSE 8050

# Flask environment
ENV FLASK_APP=dashboard.py \
    FLASK_ENV=production

# Copy and set up entrypoint
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Health check — curl the health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8050/api/health')" \
    || exit 1

# Entrypoint handles SIGTERM gracefully via the application's own signal handlers
# (parallel_executor registers atexit/SIGTERM handlers on import)
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command — main AutoTrader process
# Python receives SIGTERM from Docker and gracefully shuts down via parallel_executor handlers
CMD ["python", "mt5_AFxAutoTrader_v1.py"]