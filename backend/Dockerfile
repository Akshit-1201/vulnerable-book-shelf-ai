FROM python:3.11-slim
WORKDIR /app

# install minimal build deps (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV DB_PATH=/data/database.db
ENV LLM_API=http://llm:5000/query

EXPOSE 8000
CMD ["python", "app.py"]
