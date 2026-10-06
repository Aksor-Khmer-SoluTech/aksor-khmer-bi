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
COPY --from=build /app/portal/dist /usr/share/nginx/html
EXPOSE 80
