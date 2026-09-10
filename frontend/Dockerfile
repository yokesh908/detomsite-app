FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install --legacy-peer-deps

# Copy application
COPY . .

# Build application
RUN npm run build

# Expose port
EXPOSE 5173

# Run development server
CMD ["npm", "run", "dev"]
