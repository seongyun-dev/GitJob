# Assumed contract: FE is an npm-based React application whose production
# output is written to dist/. Adjust the package manager/output directory when
# the frontend repository contract is finalized.

FROM node:22.12-alpine AS build

WORKDIR /workspace/FE
COPY FE/package*.json ./
RUN npm ci
COPY FE/ ./

ARG VITE_API_BASE_URL=/api
ARG VITE_WS_URL=/ws
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_URL=$VITE_WS_URL

RUN npm run build

FROM nginx:1.27.1-alpine
COPY --from=build /workspace/FE/dist /usr/share/nginx/html
COPY Infra/docker/frontend/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
