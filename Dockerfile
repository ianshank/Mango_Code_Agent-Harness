# Production Multi-Stage Dockerfile for the Nemotron AI Runner (Node stack)
FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS base
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
RUN rm -rf /app/harness/node/tests \
    && chown -R node:node /app

ENV NODE_ENV=production

# Non-root. Node 26 type-strips `.ts`, so the CLI runs without a TypeScript
# loader (a dev dependency that must not ship in the runtime command).
USER node
CMD ["node", "src/ai/nemotron/cli.ts", "--help"]
