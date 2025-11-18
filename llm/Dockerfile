FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV GEMINI_TEXT_MODEL=models/gemini-2.5-flash
ENV GEMINI_EMBED_MODEL=models/gemini-embedding-001
ENV EMBED_BATCH_SIZE=64

EXPOSE 5000
CMD ["python", "app.py"]
