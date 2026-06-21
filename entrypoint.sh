#!/usr/bin/env sh

# Fail fast on any error
set -e

# Ensure Flask sees the correct app (environment variable already set in Dockerfile)
# Run database migrations before starting the main process
if command -v flask >/dev/null 2>&1; then
  echo "Running Flask-Migrate upgrade..."
  # Try migrations, retry a few times if DB not ready
max_retries=5
retry=0
while true; do
  if flask db upgrade; then
    echo "Flask-Migrate upgrade succeeded"
    break
  else
    retry=$((retry+1))
    if [ $retry -ge $max_retries ]; then
      echo "Flask-Migrate upgrade failed after $max_retries attempts. Continuing..."
      break
    fi
    echo "Flask-Migrate upgrade failed – likely DB not ready (attempt $retry/$max_retries). Sleeping 3s..."
    sleep 3
  fi
done
else
  echo "Flask command not found – skipping DB migration."
fi

# Exec the command passed to the container (CMD or overrides)
exec "$@"
