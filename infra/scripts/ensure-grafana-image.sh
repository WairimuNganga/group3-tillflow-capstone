#!/usr/bin/env bash
set -euo pipefail

# Build/push the Grafana image before Terraform applies the ECS task definition
# that references it. This closes the race where Terraform can register a task
# definition for a new immutable tag before CodePipeline has pushed that tag.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_REGION="${AWS_REGION:-us-west-1}"
NAME_PREFIX="${NAME_PREFIX:-devops-g3}"

GRAFANA_VERSION="$(awk -F'"' '/grafana_version[[:space:]]*=/{print $2; exit}' "${ROOT}/infra/envs/dev/main.tf")"
GRAFANA_IMAGE_TAG="$(awk -F'"' '/grafana_image_tag[[:space:]]*=/{print $2; exit}' "${ROOT}/infra/envs/dev/main.tf")"

if [[ -z "${GRAFANA_VERSION}" || -z "${GRAFANA_IMAGE_TAG}" ]]; then
  echo "Could not resolve grafana_version/grafana_image_tag from infra/envs/dev/main.tf" >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
REPOSITORY="${NAME_PREFIX}/grafana"
IMAGE_URI="${REGISTRY}/${REPOSITORY}:${GRAFANA_IMAGE_TAG}"

if aws ecr describe-images \
  --repository-name "${REPOSITORY}" \
  --image-ids imageTag="${GRAFANA_IMAGE_TAG}" >/dev/null 2>&1; then
  echo "Grafana image already exists: ${IMAGE_URI}"
  exit 0
fi

echo "Building and pushing Grafana image before Terraform apply: ${IMAGE_URI}"

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

docker buildx build \
  --platform linux/arm64 \
  --build-arg "GRAFANA_VERSION=${GRAFANA_VERSION}" \
  -f "${ROOT}/infra/grafana/Dockerfile" \
  -t "${IMAGE_URI}" \
  --push \
  "${ROOT}/infra/grafana"

aws ecr describe-images \
  --repository-name "${REPOSITORY}" \
  --image-ids imageTag="${GRAFANA_IMAGE_TAG}" \
  --query 'imageDetails[0].{tags:imageTags,digest:imageDigest,pushedAt:imagePushedAt}' \
  --output table
