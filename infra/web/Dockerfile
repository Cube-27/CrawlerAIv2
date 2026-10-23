# The web UI: the Vite build served by nginx, which also forwards the API's paths with the UI's key (infra/web/).
# The build context is the repo root (docker-compose.yml).
FROM node:24-slim AS build
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.pnpmfile.cjs ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

# The unprivileged build: nginx runs as its own user and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/web/default.conf.template /etc/nginx/templates/default.conf.template
# `.envsh` files, when executable, are sourced by the entrypoint, so the export reaches the template step.
COPY --chmod=755 infra/web/10-ui-key.envsh /docker-entrypoint.d/10-ui-key.envsh
