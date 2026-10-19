# Multi-stage: build the Vite/React app with Node, then serve only the
# resulting static files with nginx — the deployed image stays a few MB
# with no Node/npm in it, same "no Python/LibreOffice weight" rationale
# that justifies this being a separate service from ../api (see
# specs/template_portal_design.md).
FROM node:22-alpine AS build
WORKDIR /app
# Built from the repo root (not ./portal): the in-app guides are /docs/*.md, which the
# bundler inlines (see portal/src/docs/registry.ts).
COPY portal/package.json portal/package-lock.json* ./portal/
ARG NPM_REGISTRY=https://registry.npmjs.org/
RUN cd portal && npm ci --registry "$NPM_REGISTRY"
COPY portal portal
COPY docs docs
RUN cd portal && npm run build

FROM nginx:alpine
# .mjs is JavaScript too: nginx's mime.types maps only .js, so the PDF preview's worker (pdf.worker.min-*.mjs) went out
# as application/octet-stream, and browsers refuse to load a module script of that type ("Setting up fake worker
# failed: Failed to fetch dynamically imported module"). The grep fails the build if the line ever changes shape.
RUN sed -i -E 's#^([[:space:]]*application/javascript[[:space:]]+)js;#\1js mjs;#' /etc/nginx/mime.types \
    && grep -qE 'application/javascript[[:space:]]+js mjs;' /etc/nginx/mime.types
COPY portal/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/portal/dist /usr/share/nginx/html
# config.js is written at each start from this default plus the PORTAL_* settings, or replaced by a mounted
# config/portal/config.js (docker-entrypoint.d/40-aksor-config.sh) -- a server needs no copy of the repository.
RUN cp /usr/share/nginx/html/config.js /usr/share/nginx/html/config.default.js
COPY --chmod=755 portal/docker-entrypoint.d/40-aksor-config.sh /docker-entrypoint.d/40-aksor-config.sh
EXPOSE 80
