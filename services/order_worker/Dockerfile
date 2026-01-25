FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "poetry==1.8.3"

COPY pyproject.toml README.md /app/

RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

COPY services/order_worker /app/services/order_worker
WORKDIR /app/services/order_worker

CMD ["python", "-m", "app.consumer.main"]
