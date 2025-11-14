FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for PDF processing and FAISS
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app

# Environment variables
ENV MCP_DATA_DIR=/data/mcp
ENV LLM_EMBED_ENDPOINT=http://llm:5000/embed
ENV LLM_TEXT_ENDPOINT=http://llm:5000/query
ENV EMBED_BATCH=64
ENV EMBED_DIM=0

# Create data directories
RUN mkdir -p /data/mcp/uploads /data/mcp/faiss

EXPOSE 8001

CMD ["python", "app.py"]