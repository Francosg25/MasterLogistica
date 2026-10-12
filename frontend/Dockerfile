FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY angular.json tsconfig.json tsconfig.app.json ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist/web/browser /usr/share/nginx/html
EXPOSE 8080
