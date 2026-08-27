# Production Multi-Stage Dockerfile for Agentic SSD Pong & Nemotron AI Runner
FROM node:22-alpine AS base
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.23.0 --activate

FROM base AS dependencies
WORKDIR /app/harness/node
COPY harness/node/package.json harness/node/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS build
WORKDIR /app
COPY harness/ /app/harness/
WORKDIR /app/harness/node
RUN pnpm exec tsc --noEmit

FROM base AS runtime
WORKDIR /app/harness/node
# `build` extends `dependencies`, so this one copy carries both the sources and
# the installed node_modules. Sourcing it from `build` rather than the context
# also keeps that stage in the graph: BuildKit skips unreferenced stages, which
# would silently drop its `tsc --noEmit` typecheck.
COPY --from=build /app/harness /app/harness
ENV NODE_ENV=production

# Healthcheck & Default CLI Autoplay Entrypoint
EXPOSE 8080
CMD ["node", "--loader", "tsx", "src/pong/cli/pong-cli.ts", "--autoplay", "--ticks", "300"]
