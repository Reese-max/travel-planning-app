# syntax=docker/dockerfile:1
# Node builder
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY src/package*.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --strict-ssl=true
COPY src .
RUN npm run build

# Server
FROM python:3.12-slim
LABEL maintainer="github.com/itskovacs"
LABEL description="Minimalist POI Map Tracker and Trip Planner"
WORKDIR /app
COPY backend .
RUN --mount=type=secret,id=system_ca \
    if [ -s /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    pip install --no-cache-dir -r trip/requirements.txt
COPY --from=build /app/dist/trip/browser ./frontend
EXPOSE 8000
CMD ["fastapi", "run", "/app/trip/main.py", "--host", "0.0.0.0", "--port", "8000"]
