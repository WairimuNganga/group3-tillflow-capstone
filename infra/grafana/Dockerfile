ARG GRAFANA_VERSION=11.4.0
FROM grafana/grafana:${GRAFANA_VERSION}

USER root

COPY provisioning/dashboards/ /etc/grafana/provisioning/dashboards/
COPY provisioning/alerting/ /etc/grafana/provisioning/alerting/
COPY dashboards/*.json /var/lib/grafana/dashboards/
COPY docker-entrypoint.sh /tillflow-entrypoint.sh

RUN chmod +x /tillflow-entrypoint.sh \
  && chown -R grafana:root /var/lib/grafana/dashboards

USER grafana

ENTRYPOINT ["/tillflow-entrypoint.sh"]
