FROM node:22-alpine AS runtime

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig.json eslint.config.js ./
COPY src ./src
COPY tests ./tests

RUN addgroup -S alphadesk && adduser -S alphadesk -G alphadesk && chown -R alphadesk:alphadesk /app
USER alphadesk

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
