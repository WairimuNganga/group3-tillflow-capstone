# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=tillflow-base:local
ARG SERVICE_NAME=web
FROM ${BASE_IMAGE} AS web

ARG SERVICE_NAME=web
ARG GIT_COMMIT_SHA=unknown

ENV SERVICE_NAME=${SERVICE_NAME} \
    TILLFLOW_SERVICE_NAME=${SERVICE_NAME} \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

USER root
WORKDIR /app

COPY pyproject.toml ./
COPY web ./web

RUN /opt/venv/bin/pip install --no-cache-dir .

USER tillflow

EXPOSE 8080

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8080"]
