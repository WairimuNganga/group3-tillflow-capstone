# syntax=docker/dockerfile:1.7
#
# Concrete, buildable instance of the golden path described in
# ../Dockerfile.base — this is what gets deployed as the G1 "one golden-path
# service" proving the base image + ADOT sidecar actually boot on ECS. Every
# real service's Dockerfile (services/{web,pos,payments,commission}/Dockerfile)
# should look like this file with the CMD's module path swapped.
#
# Build (from services/_shared/, after building the base image once):
#
#   docker build -f Dockerfile.base --build-arg SERVICE_NAME=base \
#     --build-arg GIT_COMMIT_SHA=$(git rev-parse --short HEAD) \
#     -t tillflow-base:local .
#   docker build -f examples/Dockerfile \
#     --build-arg GIT_COMMIT_SHA=$(git rev-parse --short HEAD) \
#     -t tillflow-golden-path:local .
#
# Run, proving the read-only-rootfs and non-root claims rather than just
# asserting them:
#
#   docker run --rm -p 8080:8080 --read-only --tmpfs /tmp \
#     --cap-drop ALL --security-opt no-new-privileges \
#     -e TILLFLOW_TELEMETRY_EXPORT=none \
#     tillflow-golden-path:local
#
# (`--tmpfs /tmp` is the one writable path this needs — Python's own tempfile
# module defaults there; nothing else in this image writes to disk. See
# docker-smoke-test.sh for the automated version of this check, run in CI.)

ARG BASE_IMAGE=tillflow-base:local
FROM ${BASE_IMAGE} AS golden-path

WORKDIR /app
COPY --chown=tillflow:tillflow examples/demo_service.py ./examples/demo_service.py

CMD ["uvicorn", "examples.demo_service:app", "--host", "0.0.0.0", "--port", "8080"]
