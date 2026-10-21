# syntax=docker/dockerfile:1
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . ./
ARG PUBLIC_GIANNA_API_BASE=
ARG PUBLIC_SITE_URL=
ARG PUBLIC_INDEXING=false
ENV PUBLIC_GIANNA_API_BASE=$PUBLIC_GIANNA_API_BASE \
    PUBLIC_SITE_URL=$PUBLIC_SITE_URL \
    PUBLIC_INDEXING=$PUBLIC_INDEXING
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/health || exit 1
CMD ["nginx", "-g", "daemon off;"]
