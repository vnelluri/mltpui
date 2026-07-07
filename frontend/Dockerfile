# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Multi-Tenant ML Training Platform — Frontend image (React 18 + TS + Vite)
# Stages: base → dev → build → prod. Prod serves static assets via nginx.
# EXPOSE: 3000 in dev (Vite dev server) / 80 in prod (nginx). Only the final
# prod stage's EXPOSE (80) matters to ECS; the dev EXPOSE is informational.
# ─────────────────────────────────────────────────────────────────────────────

# ── base ─────────────────────────────────────────────────────────────────────
# Installs node modules once for reuse in dev and build stages.
FROM node:20-alpine AS base

WORKDIR /app

# Copy manifests first for better layer caching. package-lock.json is required
# by `npm ci`; the glob keeps the build working before/after it is generated.
COPY package*.json ./
RUN npm ci

# ── dev ──────────────────────────────────────────────────────────────────────
# Target used by docker-compose. Source is bind-mounted for Vite HMR; the COPY
# here keeps a plain `docker build` runnable too. node_modules is preserved by
# an anonymous volume in docker-compose so host mounts don't clobber it.
FROM base AS dev

COPY . .

# EXPOSE 3000  (Vite dev server — informational only)
EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

# ── build ────────────────────────────────────────────────────────────────────
# Produces the optimized static bundle in /app/dist.
FROM base AS build

COPY . .
RUN npm run build

# ── prod ─────────────────────────────────────────────────────────────────────
# Default target (used for ECS). Serves the built SPA via nginx on port 80.
FROM nginx:alpine AS prod

# SPA routing + gzip + asset caching (see frontend/nginx.conf).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets built in the previous stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
