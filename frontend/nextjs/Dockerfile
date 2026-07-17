###############################################
# 1) Dependencies layer
###############################################
FROM node:20-alpine AS deps
WORKDIR /app

# Copy only package manifest first for better layer caching
COPY package.json ./

# Install dependencies (no lock file present – recommend adding one for reproducibility)
RUN npm install --legacy-peer-deps

###############################################
# 2) Builder layer – builds Next.js (.next)
###############################################
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# ── Next.js 构建时注入（NEXT_PUBLIC_ 在 build 时内联）──
# BACKEND_URL: 浏览器 → 后端 WebSocket（用宿主机映射端口）
# GPTR_API_URL: Next.js 服务端代理 → 后端 REST（用 Docker 内网）
ARG NEXT_PUBLIC_BACKEND_URL=ws://localhost:8001
ARG NEXT_PUBLIC_GPTR_API_URL=http://backend:8001
ENV NEXT_PUBLIC_BACKEND_URL=${NEXT_PUBLIC_BACKEND_URL}
ENV NEXT_PUBLIC_GPTR_API_URL=${NEXT_PUBLIC_GPTR_API_URL}

# Build Next.js application (produces .next)
RUN npm run build \
	&& npm prune --production

###############################################
# 3) Runner layer – production image serving Next.js
###############################################
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# Copy only what is required at runtime
COPY --from=builder /app/package.json ./
COPY --from=builder /app/next.config.mjs ./
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules

# Expose port (Next.js default)
EXPOSE 3000

# Start the Next.js production server (serves API routes too)
CMD ["npm", "run", "start"]
