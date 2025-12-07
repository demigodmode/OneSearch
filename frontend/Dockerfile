# Multi-stage build for production-ready frontend

# Stage 1: Build the React app
FROM node:18-alpine as builder

WORKDIR /app

# Copy dependency files (including lock file for reproducibility)
COPY package.json package-lock.json ./

# Install ALL dependencies (devDependencies needed for build: Vite, TypeScript, etc.)
RUN npm ci

# Copy source code
COPY . .

# Build the production bundle
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
