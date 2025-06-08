# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./App ./App
COPY ./Tests ./Tests

# CMD ["uvicorn", "App.eventReceiver:app", "--host", "0.0.0.0", "--port", "8000"]
