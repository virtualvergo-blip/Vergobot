# ─────────────────────────────────────────────
# Base: Python 3.11 slim
# ─────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# ─────────────────────────────────────────────
# System deps + Node.js (untuk gmgn-cli)
# ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────
# Install gmgn-cli globally via npm
# ─────────────────────────────────────────────
RUN npm install -g gmgn-cli

# ─────────────────────────────────────────────
# Python dependencies
# ─────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────
# App code
# ─────────────────────────────────────────────
COPY . .

RUN mkdir -p data

EXPOSE 8080

CMD ["python", "main.py"]
