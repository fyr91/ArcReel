ARG PYTHON_IMAGE=dockerproxy.net/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
        "httpx==0.28.1" "pydantic==2.11.7" \
    && addgroup --system arcreel \
    && adduser --system --ingroup arcreel arcreel

COPY asset_sync_worker /app/asset_sync_worker

USER arcreel

CMD ["python", "-m", "asset_sync_worker.main"]
