# Extend the pinned upstream ADOT image with TillFlow collector config.
ARG SOURCE_IMAGE
FROM ${SOURCE_IMAGE}

COPY tillflow-collector.yaml /etc/ecs/tillflow-collector.yaml

# Same uid:gid as ecs-service adot_container_user (Trivy DS-0002).
USER 10001:10001
