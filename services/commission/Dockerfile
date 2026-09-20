# syntax=docker/dockerfile:1.7
# Commission worker image — extends the shared golden-path base.
# Build the base first: see services/_shared/README.md

ARG BASE_IMAGE=tillflow-base:local
ARG SERVICE_NAME=commission
FROM ${BASE_IMAGE} AS commission

ARG SERVICE_NAME=commission
ARG GIT_COMMIT_SHA=unknown

ENV SERVICE_NAME=${SERVICE_NAME} \
    TILLFLOW_SERVICE_NAME=${SERVICE_NAME} \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

USER root
WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY commission ./commission
COPY alembic ./alembic

RUN /opt/venv/bin/pip install --no-cache-dir ".[aws]"

USER tillflow

EXPOSE 8080

# HTTP probes for ECS; SQS worker starts alongside uvicorn via lifespan.
CMD ["uvicorn", "commission.main:app", "--host", "0.0.0.0", "--port", "8080"]
