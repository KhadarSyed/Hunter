# Build from the repo root:  docker build -f deploy/Dockerfile .
# Multi-stage build: Vite/React frontend, then the FastAPI backend that serves it.
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
# Chromium (with its system libraries) renders the deck screenshots, PPTX/PDF export and verbatim captures.
# libatomic1 first: Playwright's bundled Node driver (1.65+) needs it to run at all, and --with-deps runs it.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r backend/requirements.txt \
    && python -m playwright install --with-deps chromium
COPY backend/ backend/
COPY data/ data/
COPY --from=frontend-build /app/backend/static /app/backend/static

ENV PYTHONUNBUFFERED=1
EXPOSE 8002
# Render routes to $PORT; 8002 is the local default
CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8002}"]
