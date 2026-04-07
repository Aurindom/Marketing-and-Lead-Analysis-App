FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/
COPY run_pipeline.py .
COPY api.py .
COPY static/ static/
COPY scripts/ scripts/
COPY tests/ tests/

RUN mkdir -p /app/output

ENV PLAYWRIGHT_ENABLED=true
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]
