FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN addgroup --system alphadesk && adduser --system --ingroup alphadesk alphadesk

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --requirement requirements.lock

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY pyproject.toml ./pyproject.toml
COPY src ./src
COPY tests ./tests

RUN chown -R alphadesk:alphadesk /app

USER alphadesk

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn alphadesk_api.main:app --host 0.0.0.0 --port 8000"]
