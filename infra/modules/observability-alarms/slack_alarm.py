"""Deliver CloudWatch alarm state changes to the TillFlow Slack webhook."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

import boto3


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable {name} is empty")
    return value


def _webhook_url() -> str:
    response = boto3.client("secretsmanager").get_secret_value(
        SecretId=_required_env("SLACK_WEBHOOK_SECRET_ARN")
    )
    value = response.get("SecretString", "").strip()
    if not value:
        raise RuntimeError("Slack webhook secret has no SecretString")

    # The deployed secret is a plain URL. Accept a JSON object as well so a
    # future secret rotation can adopt the team's structured-secret format.
    if value.startswith("{"):
        document = json.loads(value)
        value = str(
            document.get("SLACK_WEBHOOK_URL")
            or document.get("webhook_url")
            or document.get("url")
            or ""
        ).strip()

    if not value.startswith("https://hooks.slack.com/"):
        raise RuntimeError("Slack webhook secret is not an incoming-webhook URL")
    return value


def _alarm_payload(event: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return alarm name, state, reason and description.

    CloudWatch direct Lambda actions use ``alarmData``. Supporting the older
    SNS-shaped fields as a fallback makes local fixture testing straightforward
    without weakening validation of the live event.
    """

    alarm_data = event.get("alarmData", {})
    state_data = alarm_data.get("state", {})
    configuration = alarm_data.get("configuration", {})

    alarm_name = str(alarm_data.get("alarmName") or event.get("AlarmName") or "unknown-alarm")
    state = str(state_data.get("value") or event.get("NewStateValue") or "UNKNOWN").upper()
    reason = str(state_data.get("reason") or event.get("NewStateReason") or "No reason supplied")
    description = str(configuration.get("description") or event.get("AlarmDescription") or "")
    return alarm_name, state, reason, description


def _service_for(alarm_name: str) -> str:
    if "reconciliation" in alarm_name:
        return "payments"
    if "payout" in alarm_name:
        return "commission"
    return "platform"


def _message(event: dict[str, Any]) -> str:
    alarm_name, state, reason, description = _alarm_payload(event)
    service = _service_for(alarm_name)
    firing = state == "ALARM"
    status = "FIRING" if firing else "RECOVERED" if state == "OK" else state
    icon = ":rotating_light:" if firing else ":white_check_mark:"

    symptom = (
        "One or more messages are visible in the reconciliation/payout DLQ."
        if firing
        else "DLQ depth returned below the alarm threshold."
    )
    impact = (
        "Payments or attendant payouts may remain non-terminal and breach their SLO."
        if firing
        else "The queue is clear; verify affected money records reached a legal terminal state."
    )
    first_action = (
        "Inspect the DLQ message and consumer logs; do not purge or redeploy until the cause is understood."
        if firing
        else "Confirm DLQ depth is zero and reconcile affected provider references before closing the incident."
    )

    # Keep the provider-generated reason bounded so a noisy expression cannot
    # make Slack reject the payload. It never contains the webhook itself.
    observed = reason[:1200]
    if description:
        observed = f"{observed} ({description[:300]})"

    return "\n".join(
        [
            f"{icon} *{alarm_name} — {status}*",
            f"*environment:* {_required_env('ENVIRONMENT')}",
            f"*service:* {service}",
            f"*symptom:* {symptom}",
            f"*user/SLO impact:* {impact}",
            f"*observed value:* {observed}",
            f"*Grafana panel:* {_required_env('GRAFANA_PANEL_URL')}",
            f"*runbook:* {_required_env('RUNBOOK_URL')}",
            f"*owner:* {_required_env('OWNER')}",
            f"*first safe action:* {first_action}",
        ]
    )


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    message = _message(event)
    request = urllib.request.Request(
        _webhook_url(),
        data=json.dumps({"text": message}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        status = response.status
        body = response.read(256).decode("utf-8", errors="replace")

    if status != 200 or body.strip() != "ok":
        raise RuntimeError(f"Slack rejected alarm notification with HTTP {status}")

    alarm_name, state, _, _ = _alarm_payload(event)
    LOGGER.info("delivered alarm notification", extra={"alarm_name": alarm_name, "state": state})
    return {"delivered": True, "alarm_name": alarm_name, "state": state}
