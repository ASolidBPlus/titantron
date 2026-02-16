FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/ ./app/
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 8769

CMD ["./start.sh"]
