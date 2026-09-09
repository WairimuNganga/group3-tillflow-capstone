# syntax=docker/dockerfile:1.7
# Concrete instance of the golden path in ../Dockerfile.base — see README.md
# "Docker golden path" for build/run commands and what this proves.

ARG BASE_IMAGE=tillflow-base:local
FROM ${BASE_IMAGE} AS golden-path

WORKDIR /app
COPY --chown=tillflow:tillflow examples/demo_service.py ./examples/demo_service.py

CMD ["uvicorn", "examples.demo_service:app", "--host", "0.0.0.0", "--port", "8080"]
