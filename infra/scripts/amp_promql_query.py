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
import sys
import urllib.parse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def query(workspace_id: str, promql: str, region: str | None = None) -> dict:
    region = region or os.environ.get("AWS_REGION", "us-west-1")
    base = f"https://aps-workspaces.{region}.amazonaws.com/workspaces/{workspace_id}"
    url = f"{base}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"

    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise SystemExit("No AWS credentials (run aws login or set AWS_PROFILE).")

    request = AWSRequest(method="GET", url=url)
    SigV4Auth(creds.get_frozen_credentials(), "aps", region).add_auth(request)
    prepared = request.prepare()

    import urllib.request

    req = urllib.request.Request(prepared.url, headers=dict(prepared.headers))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


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
