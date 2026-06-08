FROM node:18 AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

ENV NODE_ENV=production

COPY . .

RUN npm run build

FROM nginx:1.25

RUN rm /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf

COPY --from=build /app/dist /usr/share/nginx/html

COPY ./ssl /etc/nginx/ssl

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]