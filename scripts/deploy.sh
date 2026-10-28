#!/usr/bin/env bash
# Runs ON the EC2 host (invoked by GitHub Actions through Systems Manager, or manually).
# Required env: AWS_REGION ECR_REGISTRY IMAGE_TAG DVC_REMOTE_URL API_KEY_FILE PRODUCTION_HTTPS_URL
# Optional env: MODEL_ALIAS (default champion) HOST_PORT (default 8000)
# AWS access for ECR pull and S3 model pull comes from the EC2 instance IAM role (no keys on disk).
set -euo pipefail

: "${API_KEY_FILE:?API_KEY_FILE is required for production deployment}"
if [[ "$API_KEY_FILE" != "/tmp/voltguard/api-key.env" ]]; then
  echo "API_KEY_FILE must use the protected temporary deployment path." >&2
  exit 1
fi
umask 077
HEALTH_RESPONSE_FILE=""
cleanup_temp_files() {
  rm -f -- "$API_KEY_FILE"
  if [[ -n "$HEALTH_RESPONSE_FILE" ]]; then
    rm -f -- "$HEALTH_RESPONSE_FILE"
  fi
}
trap cleanup_temp_files EXIT
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/deploy_guards.sh"

# Install cleanup as soon as the exact secret path is established, before any
# remaining configuration or file-content checks can fail.
: "${AWS_REGION:?}" "${ECR_REGISTRY:?}" "${ECR_REPOSITORY:?}" "${IMAGE_TAG:?}" "${DVC_REMOTE_URL:?}"
: "${PRODUCTION_HTTPS_URL:?PRODUCTION_HTTPS_URL is required for public verification}"
: "${EXPECTED_MODEL_VERSION:?EXPECTED_MODEL_VERSION is required for release verification}"
chmod 600 "$API_KEY_FILE"
mapfile -t secret_lines < "$API_KEY_FILE"
if (( ${#secret_lines[@]} != 1 )) || [[ "${secret_lines[0]}" != API_KEY=* ]]; then
  echo "API_KEY_FILE must contain exactly one API_KEY entry." >&2
  exit 1
fi
API_KEY="${secret_lines[0]#API_KEY=}"
unset secret_lines
if [[ -z "${API_KEY//[[:space:]]/}" ]]; then
  echo "API_KEY_FILE contains an empty API_KEY." >&2
  exit 1
fi
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
    -e MODEL_ALIAS="${MODEL_ALIAS}" -e REQUIRE_API_KEY=true \
    --env-file "${API_KEY_FILE}" \
    "${1}"
}

check_service() {
  # This check runs on EC2 inside the existing Systems Manager command. Keep the API key
  # local to the host and send it to curl over stdin, never to the public HTTP endpoint.
  local base="http://127.0.0.1:${HOST_PORT}"
  local expected_version="${1-${EXPECTED_MODEL_VERSION}}"
  curl -fsS "${base}/health" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); expected=sys.argv[1]; sys.exit(0 if d.get("status")=="ok" and d.get("model_loaded") is True and (not expected or d.get("model_version")==expected) else 1)' \
    "${expected_version}" || return 1
  printf 'X-API-Key: %s\n' "${API_KEY}" | curl -fsS --header @- "${base}/model-info" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); expected=sys.argv[1]; alias=sys.argv[2]; sys.exit(0 if d.get("alias")==alias and alias in d.get("aliases_in_manifest",[]) and (not expected or str(d.get("model_version"))==expected) else 1)' \
    "${expected_version}" "${MODEL_ALIAS}"
}

check_public_health() {
  # This check is unauthenticated and TLS verification remains enabled by curl.
  # A responding but invalid health payload is a release mismatch; a transport
  # outage is indeterminate and must not roll back a locally healthy service.
  local base="${PRODUCTION_HTTPS_URL%/}"
  local status=""
  local saw_2xx_response=false
  HEALTH_RESPONSE_FILE="$(mktemp)"
  for i in $(seq 1 30); do
    if status="$(curl --proto '=https' --silent --show-error --max-time 10 \
      --output "$HEALTH_RESPONSE_FILE" --write-out '%{http_code}' "${base}/health")"; then
      if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then
        saw_2xx_response=true
        if python3 -c \
          'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); expected=sys.argv[2]; sys.exit(0 if d.get("status")=="ok" and d.get("model_loaded") is True and str(d.get("model_version"))==expected else 1)' \
          "$HEALTH_RESPONSE_FILE" "$EXPECTED_MODEL_VERSION" 2>/dev/null; then
          rm -f -- "$HEALTH_RESPONSE_FILE"
          HEALTH_RESPONSE_FILE=""
          return 0
        fi
      fi
    fi
    sleep 6
  done

  rm -f -- "$HEALTH_RESPONSE_FILE"
  HEALTH_RESPONSE_FILE=""
  if [[ "$saw_2xx_response" == true ]]; then
    echo "!! Public HTTPS endpoint returned a successful response with invalid health or model-version data."
    return 2
  fi
  echo "!! Public HTTPS endpoint was unreachable or returned no successful health response; local deployment is healthy but public verification is unconfirmed."
  return 3
}

rollback() {
  docker rm -f "${NAME}" >/dev/null 2>&1 || true
  if [ -z "${PREV_IMAGE}" ]; then
    echo "!! No previous image was running; removed the failed container."
    return 1
  fi

  echo "!! Restoring the previous image."
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

echo ">> Logging in to the configured ECR registry."
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo ">> Pulling the requested commit image from ECR."
docker pull "${IMAGE}"

PREV_IMAGE=""
PREV_CONTAINER_ID=""
if ! inspect_previous_container "$NAME"; then
  exit 1
fi
if [[ -n "$PREV_CONTAINER_ID" ]]; then
  docker rm -f "${NAME}" >/dev/null
fi

echo ">> Starting ${NAME} on host port ${HOST_PORT}; container port remains 8000."
echo ">> The entrypoint pulls the locked model from the configured DVC remote."
if ! start_container "${IMAGE}"; then
  echo "!! New container could not start."
  rollback || true
  exit 1
fi

echo ">> Waiting for /health"
LOCAL_HEALTHY=false
for i in $(seq 1 40); do
  if check_service; then
    echo ">> Local health and authenticated champion/version verification passed."
    LOCAL_HEALTHY=true
    break
  fi
  sleep 3
done

if [[ "$LOCAL_HEALTHY" != true ]]; then
  echo "!! Local health or authenticated model verification failed. Recent logs:"; docker logs --tail 50 "${NAME}" || true
  rollback || true
  exit 1
fi

if check_public_health; then
  echo ">> Public HTTPS health and expected model-version verification passed."
  exit 0
else
  public_check_status=$?
  if should_rollback_public_check "$public_check_status"; then
    rollback || true
  else
    echo "!! Leaving the locally verified candidate running because public ingress verification was unavailable."
  fi
  exit 1
fi
