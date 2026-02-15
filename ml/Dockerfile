FROM python:3.12-slim

WORKDIR /app

# Install PyTorch CPU-only first (from dedicated index)
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining deps from PyPI
RUN pip install --no-cache-dir \
    panns_inference \
    fastapi \
    "uvicorn[standard]"

COPY app/ ./app/

EXPOSE 8769

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8769"]
