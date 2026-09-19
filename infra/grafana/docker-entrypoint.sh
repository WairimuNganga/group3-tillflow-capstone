#!/bin/sh
set -eu

mkdir -p /etc/grafana/provisioning/datasources
mkdir -p /etc/grafana/provisioning/alerting

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

if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  cat > /etc/grafana/provisioning/alerting/contact-points.yaml <<EOF
apiVersion: 1
contactPoints:
  - orgId: 1
    name: slack-tillflow
    receivers:
      - uid: slack-tillflow
        type: slack
        settings:
          url: "${SLACK_WEBHOOK_URL}"
          title: '{{ .CommonLabels.alertname }} (TillFlow)'
          text: '{{ .CommonAnnotations.summary }} — {{ .CommonAnnotations.runbook }}'
EOF
else
  echo "SLACK_WEBHOOK_URL unset; skipping Slack contact point provisioning (Phase E)."
fi

exec /run.sh
