FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

RUN npm run build

FROM nginx:alpine

RUN rm -f /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf

COPY --from=builder /app/dist /usr/share/nginx/html

COPY ./ssl /etc/nginx/ssl

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]