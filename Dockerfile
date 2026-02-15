# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim
WORKDIR /app

# Install system deps (ffmpeg for audio analysis)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./

# Copy built frontend
COPY --from=frontend-build /app/frontend/build ./frontend-build

# Create config directory for SQLite
RUN mkdir -p /config

# Git info baked in at build time
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ENV TITANTRON_GIT_COMMIT=$GIT_COMMIT
ENV TITANTRON_GIT_BRANCH=$GIT_BRANCH

ENV TITANTRON_DB_PATH=/config/titantron.db
ENV TITANTRON_FRONTEND_DIR=/app/frontend-build
ENV TITANTRON_LOG_LEVEL=info

EXPOSE 8765
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
