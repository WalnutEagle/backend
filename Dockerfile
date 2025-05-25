FROM node:18-alpine
WORKDIR /app

# Copy package files and install deps
COPY package.json ./
RUN npm ci --only=production

# Copy server code
COPY server.js ./

# Expose your WS port
EXPOSE 8081

# Run the server
CMD ["node", "server.js"]
