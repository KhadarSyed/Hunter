# Multi-stage build: Vite/React frontend, then the FastAPI backend that serves it.
FROM node:20-slim AS frontend-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY agent/requirements.txt agent/requirements.txt
# Chromium (with its system libraries) renders the deck screenshots, PPTX/PDF export and verbatim captures
RUN pip install --no-cache-dir -r agent/requirements.txt \
    && python -m playwright install --with-deps chromium
COPY agent/ agent/
COPY --from=frontend-build /app/agent/static /app/agent/static

ENV PYTHONUNBUFFERED=1
EXPOSE 8002
# Render routes to $PORT; 8002 is the local default
CMD ["sh", "-c", "python -m uvicorn agent.app.main:app --host 0.0.0.0 --port ${PORT:-8002}"]
