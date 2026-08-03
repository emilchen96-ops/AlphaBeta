FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HOME=/home/alphadesk \
    XDG_CACHE_HOME=/home/alphadesk/.cache

WORKDIR /app

RUN addgroup --system alphadesk \
    && adduser --system --home /home/alphadesk --ingroup alphadesk alphadesk \
    && mkdir -p /home/alphadesk/.cache \
    && chown -R alphadesk:alphadesk /home/alphadesk

COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --requirement requirements.lock

COPY requirements.tradingagents.lock ./requirements.tradingagents.lock
RUN pip install --no-cache-dir --no-deps --requirement requirements.tradingagents.lock

COPY requirements.tradingagents-runtime.lock ./requirements.tradingagents-runtime.lock
RUN pip install --no-cache-dir --requirement requirements.tradingagents-runtime.lock

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY pyproject.toml ./pyproject.toml
COPY src ./src
COPY tests ./tests
COPY docker-entrypoint.sh /usr/local/bin/alphadesk-entrypoint

RUN chown -R alphadesk:alphadesk /app \
    && chmod 0755 /usr/local/bin/alphadesk-entrypoint

ENTRYPOINT ["/usr/local/bin/alphadesk-entrypoint"]

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn alphadesk_api.main:app --host 0.0.0.0 --port 8000"]
