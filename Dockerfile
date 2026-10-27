FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY config ./config
COPY src ./src
COPY public ./public
ENV VITE_NMS_API_ENABLED=true VITE_NMS_API_BASE=/nms-api
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine AS production
ARG VCS_REF=development
LABEL org.opencontainers.image.source="https://github.com/2500018036-ship-it/nms-dashboard" \
      org.opencontainers.image.revision="${VCS_REF}"
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER root
RUN printf '{"revision":"%s"}\n' "$VCS_REF" > /usr/share/nginx/html/deployment.json
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
