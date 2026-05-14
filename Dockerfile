FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

ENV PCB_HOST=0.0.0.0
ENV PCB_PORT=8765
ENV PCB_DATA_DIR=/data
ENV PYTHONPYCACHEPREFIX=/tmp/pycache

RUN mkdir -p /data

EXPOSE 8765

CMD ["python3", "app.py"]
