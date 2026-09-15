# syntax=docker/dockerfile:1.7
# Payments service image — extends the shared golden-path base.
# Build the base first: see services/_shared/README.md

ARG BASE_IMAGE=tillflow-base:local
ARG SERVICE_NAME=payments
FROM ${BASE_IMAGE} AS payments

ARG SERVICE_NAME=payments
ARG GIT_COMMIT_SHA=unknown

ENV SERVICE_NAME=${SERVICE_NAME} \
    TILLFLOW_SERVICE_NAME=${SERVICE_NAME} \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

USER root
WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY payments ./payments
COPY alembic ./alembic

RUN /opt/venv/bin/pip install --no-cache-dir .

USER tillflow

EXPOSE 8080

CMD ["uvicorn", "payments.main:app", "--host", "0.0.0.0", "--port", "8080"]
