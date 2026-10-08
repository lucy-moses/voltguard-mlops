#!/usr/bin/env bash
# Runs ON the EC2 host (invoked by GitHub Actions over SSH, or manually).
# Required env: AWS_REGION ECR_REGISTRY ECR_REPOSITORY IMAGE_TAG DVC_REMOTE_URL
# Optional env: API_KEY MODEL_ALIAS (default champion) HOST_PORT (default 8000)
#               EXPECTED_MODEL_VERSION (checked against the running API when set)
# AWS access for ECR pull and S3 model pull comes from the EC2 instance IAM role (no keys on disk).
set -euo pipefail

: "${AWS_REGION:?}" "${ECR_REGISTRY:?}" "${ECR_REPOSITORY:?}" "${IMAGE_TAG:?}" "${DVC_REMOTE_URL:?}"
NAME=voltguard-api
IMAGE="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
HOST_PORT="${HOST_PORT:-8000}"
MODEL_ALIAS="${MODEL_ALIAS:-champion}"
EXPECTED_MODEL_VERSION="${EXPECTED_MODEL_VERSION:-}"

start_container() {
  docker run -d --name "${NAME}" --restart unless-stopped \
    -p "${HOST_PORT}:8000" \
    -e AWS_REGION="${AWS_REGION}" -e AWS_DEFAULT_REGION="${AWS_REGION}" \
    -e DVC_REMOTE_URL="${DVC_REMOTE_URL}" -e MODEL_SOURCE=dvc \
    -e MODEL_ALIAS="${MODEL_ALIAS}" -e API_KEY="${API_KEY:-}" \
    "${1}"
}

check_service() {
  local base="http://localhost:${HOST_PORT}"
  local expected_version="${1-${EXPECTED_MODEL_VERSION}}"
  curl -fsS "${base}/health" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); expected=sys.argv[1]; sys.exit(0 if d.get("status")=="ok" and d.get("model_loaded") is True and (not expected or d.get("model_version")==expected) else 1)' \
    "${expected_version}" || return 1
  curl -fsS "${base}/model-info" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); expected=sys.argv[1]; alias=sys.argv[2]; sys.exit(0 if d.get("alias")==alias and alias in d.get("aliases_in_manifest",[]) and (not expected or str(d.get("model_version"))==expected) else 1)' \
    "${expected_version}" "${MODEL_ALIAS}"
}

rollback() {
  docker rm -f "${NAME}" >/dev/null 2>&1 || true
  if [ -z "${PREV_IMAGE}" ]; then
    echo "!! No previous image was running; removed the failed container."
    return 1
  fi

  echo "!! Restoring previous image ${PREV_IMAGE}"
  if ! start_container "${PREV_IMAGE}"; then
    echo "!! Could not start the previous image."
    return 1
  fi
  for i in $(seq 1 40); do
    if check_service ""; then
      echo ">> Previous image is healthy again."
      return 0
    fi
    sleep 3
  done
  echo "!! Previous image did not recover health; recent logs:"
  docker logs --tail 50 "${NAME}" || true
  return 1
}

echo ">> Logging in to ECR ${ECR_REGISTRY}"
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo ">> Pulling ${IMAGE}"
docker pull "${IMAGE}"

PREV_IMAGE="$(docker inspect --format '{{.Config.Image}}' "${NAME}" 2>/dev/null || true)"
docker rm -f "${NAME}" >/dev/null 2>&1 || true

echo ">> Starting ${NAME} on host port ${HOST_PORT}; container port remains 8000."
echo ">> The entrypoint pulls the model from ${DVC_REMOTE_URL}"
if ! start_container "${IMAGE}"; then
  echo "!! New container could not start."
  rollback || true
  exit 1
fi

echo ">> Waiting for /health"
for i in $(seq 1 40); do
  if check_service; then
    echo ">> Healthy: $(curl -fsS "http://localhost:${HOST_PORT}/health")"
    exit 0
  fi
  sleep 3
done

echo "!! Service did not become healthy. Recent logs:"; docker logs --tail 50 "${NAME}" || true
rollback || true
exit 1
