FROM python:3.12-slim

WORKDIR /app

COPY app/ ./app/
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 8769

CMD ["./start.sh"]
