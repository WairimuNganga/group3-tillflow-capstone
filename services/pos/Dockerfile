# syntax=docker/dockerfile:1.7
# POS service image — extends the shared golden-path base.
# Build the base first: see services/_shared/README.md

ARG BASE_IMAGE=tillflow-base:local
ARG SERVICE_NAME=pos
FROM ${BASE_IMAGE} AS pos

ARG SERVICE_NAME=pos
ARG GIT_COMMIT_SHA=unknown

ENV SERVICE_NAME=${SERVICE_NAME} \
    TILLFLOW_SERVICE_NAME=${SERVICE_NAME} \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

USER root
WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY pos ./pos
COPY alembic ./alembic

RUN /opt/venv/bin/pip install --no-cache-dir .

USER tillflow

EXPOSE 8080

CMD ["uvicorn", "pos.main:app", "--host", "0.0.0.0", "--port", "8080"]
