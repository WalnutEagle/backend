FROM node:18-alpine
WORKDIR /app

# install deps
COPY package.json ./
RUN npm ci --only=production

# copy code & run
COPY server.js ./
EXPOSE 8081
CMD ["node", "server.js"]
