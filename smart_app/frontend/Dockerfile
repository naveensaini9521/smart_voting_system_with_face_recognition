FROM --platform=linux/amd64 node:18 AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

RUN npm run build


FROM nginx:alpine

#override change in nginx site config to set all requests hits to /api to goes gunicorn running on hostname is http://backend:5000 port 
COPY default.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]