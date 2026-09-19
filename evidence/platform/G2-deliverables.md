# G2 platform evidence — Lwam

Owner: Lwam  
Area: Platform — Terraform, ECS, RDS, RDS Proxy, Secrets Manager, pipeline support

This file captures the platform evidence for G2. The product flow is owned by
POS/Payments, but platform proves the AWS foundation is ready and repeatable.

## Deliverables checklist

- [x] RDS PostgreSQL is available.
- [x] RDS Proxy is available.
- [x] RDS Proxy has service runtime credentials configured.
- [x] DB bootstrap completed successfully.
- [x] `devops-g3/db` has service-specific credential keys.
- [x] POS migrations run before ECS deploy.
- [x] Pipeline reaches `Smoke` successfully.
- [x] ECS services are running at expected desired counts.
- [x] Application and ADOT containers are healthy.
- [x] `/health` and `/ready` return `200`.
- [x] POS internal route is not publicly usable.

## 1. RDS and RDS Proxy

Command:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws rds describe-db-instances \
  --db-instance-identifier devops-g3-db \
  --query 'DBInstances[0].{status:DBInstanceStatus,endpoint:Endpoint.Address}' \
  --output table
```

Output:

```text
------------------------------------------------------------------------
|                          DescribeDBInstances                         |
+---------------------------------------------------------+------------+
|                        endpoint                         |  status    |
+---------------------------------------------------------+------------+
|  devops-g3-db.chgiwkc8muat.us-west-1.rds.amazonaws.com  |  available |
+---------------------------------------------------------+------------+
```

Command:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws rds describe-db-proxies \
  --db-proxy-name devops-g3-db-proxy \
  --query 'DBProxies[0].{status:Status,endpoint:Endpoint,authSecrets:Auth[].SecretArn}' \
  --output table
```

Output:

```text
---------------------------------------------------------------------------------------------------------------
|                                              DescribeDBProxies                                              |
+--------------+----------------------------------------------------------------------------------------------+
|  endpoint    |  devops-g3-db-proxy.proxy-chgiwkc8muat.us-west-1.rds.amazonaws.com                           |
|  status      |  available                                                                                   |
+--------------+----------------------------------------------------------------------------------------------+
||                                                authSecrets                                                ||
|+-----------------------------------------------------------------------------------------------------------+|
||  devops-g3/db-proxy-commission (ARN redacted for secret-scan)                                    ||
||  devops-g3/db-proxy-web (ARN redacted for secret-scan)                                           ||
||  devops-g3/db-proxy-payments (ARN redacted for secret-scan)                                      ||
||  devops-g3/db-proxy-pos (ARN redacted for secret-scan)                                           ||
||  RDS-managed master DB secret (ARN redacted for secret-scan)                                     ||
|+-----------------------------------------------------------------------------------------------------------+|
```

Expected:

- DB status is `available`
- proxy status is `available`
- proxy auth includes service DB auth secrets

## 2. DB bootstrap

Command:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codebuild start-build \
  --project-name devops-g3-db-bootstrap
```

Output:

```text
{
    "build": {
        "id": "devops-g3-db-bootstrap:c74a7926-9504-4faa-9f6d-1a75290e9902"
    }
}
```

Command:

```bash
BUILD_ID=$(AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codebuild list-builds-for-project \
  --project-name devops-g3-db-bootstrap \
  --sort-order DESCENDING \
  --query 'ids[0]' \
  --output text)

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codebuild batch-get-builds \
  --ids "$BUILD_ID" \
  --query 'builds[0].{status:buildStatus,phase:currentPhase,logs:logs.deepLink}' \
  --output table
```

Output:

```text
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
|                                                                                                BatchGetBuilds                                                                                                |
+--------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
|  logs  |  https://console.aws.amazon.com/cloudwatch/home?region=us-west-1#logsV2:log-groups/log-group/$252Fdevops-g3$252Fcodebuild$252Fdb-bootstrap/log-events/db$252Fc74a7926-9504-4faa-9f6d-1a75290e9902   |
|  phase |  COMPLETED                                                                                                                                                                                          |
|  status|  SUCCEEDED                                                                                                                                                                                          |
+--------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
```

Expected:

- build status is `SUCCEEDED`
- phase is `COMPLETED`
- no secret values are pasted into evidence

## 3. DB secret shape

Do not print passwords. Only print key names and value types.

Command:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws secretsmanager get-secret-value \
  --secret-id devops-g3/db \
  --query SecretString \
  --output text \
| jq -r 'fromjson | to_entries[] | "\(.key): \(.value | type)"'
```

Output:

```text
web: string
pos: string
payments: string
commission: string
```

Expected:

```text
web: string
pos: string
payments: string
commission: string
```

## 4. Pipeline stages

Command:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codepipeline get-pipeline-state \
  --name devops-g3-pipeline \
  --query 'stageStates[].{stage:stageName,actions:actionStates[].{name:actionName,status:latestExecution.status,last:latestExecution.lastStatusChange}}' \
  --output table
```

Output:

```text
Source/GitHub: Succeeded
BuildScanPush/mirror-adot: Succeeded
BuildScanPush/build-commission: Succeeded
BuildScanPush/build-payments: Succeeded
BuildScanPush/build-pos: Succeeded
BuildScanPush/build-web: Succeeded
MigrateDb/pos-alembic: Succeeded
DeployEcs/deploy-commission: Succeeded
DeployEcs/deploy-payments: Succeeded
DeployEcs/deploy-pos: Succeeded
DeployEcs/deploy-web: Succeeded
Smoke/scale-and-smoke: Succeeded


Expected:

```text
Source         Succeeded
BuildScanPush  Succeeded
MigrateDb      Succeeded
DeployEcs      Succeeded
Smoke          Succeeded
```

## 5. ECS service health

Command:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs describe-services \
  --cluster devops-g3 \
  --services devops-g3-web devops-g3-pos devops-g3-payments devops-g3-commission \
  --query 'services[].{service:serviceName,desired:desiredCount,running:runningCount,pending:pendingCount,rollout:deployments[0].rolloutState,taskDef:taskDefinition}' \
  --output table
```

Output:

```text
------------------------------------------------------------------------------------------------------------------------------------------------------
|                                                                  DescribeServices                                                                  |
+---------+----------+------------+----------+-----------------------+-------------------------------------------------------------------------------+
| desired | pending  |  rollout   | running  |        service        |                                    taskDef                                    |
+---------+----------+------------+----------+-----------------------+-------------------------------------------------------------------------------+
|  2      |  0       |  COMPLETED |  2       |  devops-g3-web        |  arn:aws:ecs:us-west-1:240462142849:task-definition/devops-g3-web:33          |
|  2      |  0       |  COMPLETED |  2       |  devops-g3-pos        |  arn:aws:ecs:us-west-1:240462142849:task-definition/devops-g3-pos:33          |
|  2      |  0       |  COMPLETED |  2       |  devops-g3-payments   |  arn:aws:ecs:us-west-1:240462142849:task-definition/devops-g3-payments:33     |
|  1      |  0       |  COMPLETED |  1       |  devops-g3-commission |  arn:aws:ecs:us-west-1:240462142849:task-definition/devops-g3-commission:34   |
+---------+----------+------------+----------+-----------------------+-------------------------------------------------------------------------------+
```

Expected:

- `devops-g3-web`: desired `2`, running `2`
- `devops-g3-pos`: desired `2`, running `2`
- `devops-g3-payments`: desired `2`, running `2`
- `devops-g3-commission`: desired `1`, running `1`
- rollout state is `COMPLETED`

## 6. Container health

Command:

```bash
TASKS=$(AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs list-tasks \
  --cluster devops-g3 \
  --desired-status RUNNING \
  --query 'taskArns[]' \
  --output text)

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs describe-tasks \
  --cluster devops-g3 \
  --tasks $TASKS \
  --query 'tasks[].{service:group,containers:containers[].{name:name,status:lastStatus,health:healthStatus}}' \
  --output table
```

Output:

```text
service:devops-g3-web
  ecs-service-connect-0uywf  RUNNING  HEALTHY
  web                         RUNNING  HEALTHY
  adot                        RUNNING  HEALTHY

service:devops-g3-commission
  ecs-service-connect-FDKq0i  RUNNING  HEALTHY
  commission                  RUNNING  HEALTHY
  adot                        RUNNING  HEALTHY

service:devops-g3-payments
  payments                    RUNNING  HEALTHY
  adot                        RUNNING  HEALTHY
  ecs-service-connect-2reIdbR RUNNING  HEALTHY

service:devops-g3-pos
  pos                         RUNNING  HEALTHY
  adot                        RUNNING  HEALTHY
  ecs-service-connect-MTbld   RUNNING  HEALTHY
```

Expected:

- app containers are `RUNNING` and `HEALTHY`
- ADOT sidecars are `RUNNING` and `HEALTHY`

## 7. Public smoke endpoints

Command:

```bash
API_URL=$(AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
terraform -chdir=infra/envs/dev output -raw api_endpoint)

curl -i "${API_URL%/}/health"
curl -i "${API_URL%/}/ready"
```

Output:

```text
HTTP/2 200 
date: Fri, 18 Sep 2026 17:53:52 GMT
content-type: application/json
content-length: 84
server: envoy
x-envoy-upstream-service-time: 1
apigw-requestid: REDACTED

{"status":"ok","service":"web","git_sha":"5cfa264cfe0fd22aee1bc8983020f60cac697ce7"}

HTTP/2 200 
date: Fri, 18 Sep 2026 17:53:53 GMT
content-type: application/json
content-length: 34
server: envoy
x-envoy-upstream-service-time: 1
apigw-requestid: REDACTED

{"status":"ready","service":"web"}
```

Expected:

- `/health` returns `HTTP/2 200`
- `/ready` returns `HTTP/2 200`

## 8. POS internal route protection

Command:

```bash
API_URL=$(AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
terraform -chdir=infra/envs/dev output -raw api_endpoint)

curl -i "${API_URL%/}/api/pos/internal/test"
```

Output:

```text
HTTP/2 404 
date: Fri, 18 Sep 2026 17:53:54 GMT
content-type: application/json; charset=utf-8
content-length: 21
server: awselb/2.0
apigw-requestid: REDACTED

{"error":"not found"}
```

Expected:

- internal POS route is not publicly usable
- settlement endpoints are intended for service-to-service access from Payments
