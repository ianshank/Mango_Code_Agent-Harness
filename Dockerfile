# Production Multi-Stage Dockerfile for the Nemotron AI Runner (Node stack)
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

# Dropped here rather than in `.dockerignore`: `tsconfig.json` includes
# `tests/**/*.ts`, so excluding them from the build context would leave the
# `tsc --noEmit` above typechecking less while still reporting success. The
# runtime image reads nothing under `tests/`, and the AI fixtures carry
# `nvapi-...` literals that are allowlisted for the secret scan but have no
# reason to ship.
RUN rm -rf /app/harness/node/tests

ENV NODE_ENV=production

# Default entrypoint: the Nemotron CLI. Without NVIDIA_API_KEY (or an explicit
# prompt) it prints usage instead of making a network call.
EXPOSE 8080
CMD ["node", "--loader", "tsx", "src/ai/nemotron/cli.ts", "--help"]
