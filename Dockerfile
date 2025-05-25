FROM node:18-alpine
WORKDIR /app

# install only prod deps
COPY package.json ./
RUN npm install --production

# copy code
COPY server.js ./

EXPOSE 8081
CMD ["node", "server.js"]
