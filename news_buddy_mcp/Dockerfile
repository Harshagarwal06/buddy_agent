# news_buddy_mcp/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "news_buddy_mcp.server"]
