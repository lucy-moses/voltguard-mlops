#!/usr/bin/env bash
# Runs ON the EC2 host (invoked by GitHub Actions over SSH, or manually).
# Required env: AWS_REGION ECR_REGISTRY ECR_REPOSITORY IMAGE_TAG DVC_REMOTE_URL
# Optional env: API_KEY MODEL_ALIAS (default champion) HOST_PORT (default 80)
# AWS access for ECR pull and S3 model pull comes from the EC2 instance IAM role (no keys on disk).
set -euo pipefail

: "${AWS_REGION:?}" "${ECR_REGISTRY:?}" "${ECR_REPOSITORY:?}" "${IMAGE_TAG:?}" "${DVC_REMOTE_URL:?}"
NAME=voltguard-api
IMAGE="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
HOST_PORT="${HOST_PORT:-80}"

echo ">> Logging in to ECR ${ECR_REGISTRY}"
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo ">> Pulling ${IMAGE}"
docker pull "${IMAGE}"

PREV_IMAGE="$(docker inspect --format '{{.Config.Image}}' "${NAME}" 2>/dev/null || true)"
docker rm -f "${NAME}" >/dev/null 2>&1 || true

echo ">> Starting ${NAME} (the container entrypoint pulls the model from ${DVC_REMOTE_URL})"
docker run -d --name "${NAME}" --restart unless-stopped \
  -p "${HOST_PORT}:8000" \
  -e AWS_REGION="${AWS_REGION}" -e AWS_DEFAULT_REGION="${AWS_REGION}" \
  -e DVC_REMOTE_URL="${DVC_REMOTE_URL}" -e MODEL_SOURCE=dvc \
  -e MODEL_ALIAS="${MODEL_ALIAS:-champion}" -e API_KEY="${API_KEY:-}" \
  "${IMAGE}"

echo ">> Waiting for /health"
for i in $(seq 1 40); do
  if curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    echo ">> Healthy: $(curl -fsS "http://localhost:${HOST_PORT}/health")"
    docker image prune -f >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 3
done

echo "!! Service did not become healthy. Recent logs:"; docker logs --tail 50 "${NAME}" || true
if [ -n "${PREV_IMAGE}" ]; then
  echo "!! Rolling back to ${PREV_IMAGE}"
  docker rm -f "${NAME}" >/dev/null 2>&1 || true
  docker run -d --name "${NAME}" --restart unless-stopped -p "${HOST_PORT}:8000" \
    -e AWS_REGION="${AWS_REGION}" -e AWS_DEFAULT_REGION="${AWS_REGION}" -e DVC_REMOTE_URL="${DVC_REMOTE_URL}" \
    -e MODEL_SOURCE=dvc -e MODEL_ALIAS="${MODEL_ALIAS:-champion}" -e API_KEY="${API_KEY:-}" "${PREV_IMAGE}" || true
fi
exit 1
