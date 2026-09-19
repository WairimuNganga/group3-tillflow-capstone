#!/usr/bin/env python3
"""Run a PromQL query against Amazon Managed Prometheus (SigV4).

Usage:
  export AWS_REGION=us-west-1
  python infra/scripts/amp_promql_query.py ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d \
    'sum(rate(payments_requests_total[5m]))'

Or set AMP_WORKSPACE_ID and pass the query as the only argument.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import MissingDependencyException


def _hydrate_credentials_from_aws_cli() -> None:
    """Use `aws configure export-credentials` so boto3 avoids the login CRT provider."""
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        return
    try:
        proc = subprocess.run(
            ["aws", "configure", "export-credentials", "--format", "env"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, _, value = line.partition("=")
        if key:
            os.environ[key] = value.strip().strip('"')


def query(workspace_id: str, promql: str, region: str | None = None) -> dict:
    region = region or os.environ.get("AWS_REGION", "us-west-1")
    base = f"https://aps-workspaces.{region}.amazonaws.com/workspaces/{workspace_id}"
    url = f"{base}/api/v1/query"
    # POST avoids SigV4/encoding bugs on regex queries (e.g. `.+` in label matchers).
    body = urllib.parse.urlencode({"query": promql}, quote_via=urllib.parse.quote).encode()

    _hydrate_credentials_from_aws_cli()
    session = boto3.Session()
    try:
        creds = session.get_credentials()
    except MissingDependencyException:
        raise SystemExit(
            'AWS login in Python needs: pip install "botocore[crt]"\n'
            "Or run: eval \"$(aws configure export-credentials --format env)\" then retry."
        ) from None
    if creds is None:
        raise SystemExit("No AWS credentials (run aws login or set AWS_PROFILE).")

    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    SigV4Auth(creds.get_frozen_credentials(), "aps", region).add_auth(request)
    prepared = request.prepare()

    req = urllib.request.Request(
        prepared.url,
        data=body,
        headers=dict(prepared.headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        if exc.code == 403:
            if "signature we calculated does not match" in body:
                raise SystemExit(
                    "AMP query returned 403 due to SigV4 signing mismatch (not IAM). "
                    "Report this as a script bug.\n"
                    f"Response: {body or exc.reason}"
                ) from exc
            raise SystemExit(
                "AMP query returned 403 Forbidden — likely missing aps:QueryMetrics on "
                f"workspace {workspace_id}.\n"
                f"Response: {body or exc.reason}"
            ) from exc
        if exc.code == 404:
            raise SystemExit(
                f"AMP query returned 404 — check workspace id {workspace_id!r} and PromQL.\n"
                f"Response: {body or exc.reason}"
            ) from exc
        raise SystemExit(f"AMP query HTTP {exc.code}: {body or exc.reason}") from exc


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    if len(sys.argv) == 2:
        workspace_id = os.environ.get("AMP_WORKSPACE_ID")
        if not workspace_id:
            raise SystemExit("Set AMP_WORKSPACE_ID or pass workspace_id as first argument.")
        promql = sys.argv[1]
    else:
        workspace_id, promql = sys.argv[1], sys.argv[2]

    result = query(workspace_id, promql)
    print(json.dumps(result, indent=2))
    status = result.get("status")
    if status != "success":
        raise SystemExit(f"Query failed: {status}")


if __name__ == "__main__":
    main()
