FROM ghcr.io/astral-sh/uv:0.9.12-bookworm AS uv

FROM python:3.13-slim-bookworm AS prod

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/usr/local
ENV UV_PYTHON_DOWNLOADS=never
ENV UV_NO_MANAGED_PYTHON=1

WORKDIR /app/src

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=from=uv,source=/usr/local/bin/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . .

RUN --mount=from=uv,source=/usr/local/bin/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Playwright Chromium + system deps untuk crawler non-Apify (trends24, screenshot-evidence, dll).
# Kalau hanya pakai crawler Apify, baris ini bisa dihapus untuk memperkecil image (~700MB).
RUN python -m playwright install --with-deps chromium

# Node.js + tweet-harvest: scripts.crawler.twitter memanggil `npx tweet-harvest`
# (CLI Node.js berbasis Playwright) untuk scrape tweet via auth_token. Tanpa ini
# Twitter gagal: "No such file or directory: 'npx'". tweet-harvest di-install global
# agar `npx` langsung menemukannya tanpa prompt/unduh saat runtime; chromium-nya
# di-install dari versi Playwright bawaan tweet-harvest agar cocok.
RUN apt-get update && apt-get install -y curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g tweet-harvest \
    && (cd "$(npm root -g)" && npx --yes playwright install --with-deps chromium) \
    && rm -rf /var/lib/apt/lists/*

CMD ["/usr/local/bin/python", "-m", "app"]

FROM prod AS dev

RUN --mount=from=uv,source=/usr/local/bin/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --all-groups
