# The console is built here and served as static files.
#
# This image used to run `npm run dev` in production. A dev server transforms
# every module on request, so a file the module graph asks for and cannot find
# becomes a full-screen HMR error overlay on top of the running console — which
# is what an operator saw instead of their curriculum. It also ships unminified
# source and rebuilds on every request.
FROM node:20-alpine AS build

WORKDIR /app

# The lockfile is copied so the image installs the versions that were tested.
# Installing from package.json alone let the deployed console drift to
# different dependency versions than the ones the build was verified against.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked at build time because Vite inlines it into the bundle. The default
# matches the proxy below, so the console calls its own origin.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM node:20-alpine

WORKDIR /app

# `vite preview` serves the built bundle and applies the proxy from
# vite.config.ts, so API_PROXY_TARGET stays a runtime setting rather than
# something baked into the image.
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json /app/vite.config.ts ./

EXPOSE 5173

CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "5173"]
