#!/bin/sh
set -eu

mkdir -p /etc/grafana/provisioning/datasources

cat > /etc/grafana/provisioning/datasources/amp.yaml <<EOF
apiVersion: 1
datasources:
  - name: AMP
    uid: AMP
    type: prometheus
    access: proxy
    url: ${AMP_PROMETHEUS_ENDPOINT}
    isDefault: true
    jsonData:
      sigV4Auth: true
      sigV4Region: ${AWS_REGION}
      sigV4AuthType: default
EOF

exec /run.sh
