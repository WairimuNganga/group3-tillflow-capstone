# Extend the pinned upstream ADOT image with TillFlow collector config.
ARG SOURCE_IMAGE
FROM ${SOURCE_IMAGE}

COPY tillflow-collector.yaml /etc/ecs/tillflow-collector.yaml
