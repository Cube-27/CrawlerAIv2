# The web UI: the Vite build served by nginx, which also forwards the API's paths with the UI's key (infra/web/).
# The build context is the repo root (docker-compose.yml).
FROM node:24-slim AS build
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.pnpmfile.cjs ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

FROM nginx:1.29-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/web/default.conf.template /etc/nginx/templates/default.conf.template
# `.envsh` files, when executable, are sourced by the entrypoint, so the export reaches the template step.
COPY infra/web/10-ui-key.envsh /docker-entrypoint.d/10-ui-key.envsh
RUN chmod 755 /docker-entrypoint.d/10-ui-key.envsh
