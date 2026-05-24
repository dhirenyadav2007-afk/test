FROM python:3.11-slim

# System deps: ffmpeg for metadata injection
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Working dirs for downloads / metadata processing
RUN mkdir -p downloads metadata

CMD ["python", "bot.py"]
