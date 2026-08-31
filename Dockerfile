# NudgePilot — Cloud Run container.
# Builds against a slim Python runtime. Offline fallback means the container
# boots and serves WITHOUT any secret; adding GOOGLE_API_KEY flips it to Gemini.
FROM python:3.11-slim

WORKDIR /app

# copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# application
COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# run the FastAPI service methods
CMD ["uvicorn", "cloud.app:app", "--host", "0.0.0.0", "--port", "8080"]