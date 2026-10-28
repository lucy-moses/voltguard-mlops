#!/usr/bin/env bash
# Pure deployment guards. Docker is called only by inspect_previous_container;
# tests source this file and replace the docker command with a shell mock.

inspect_previous_container() {
  local container_name="$1"
  local container_ids image

  if ! container_ids="$(docker ps -aq --filter "name=^/${container_name}$")"; then
    echo "Docker container listing failed; refusing to remove or replace a container." >&2
    return 1
  fi
  if [[ -z "$container_ids" ]]; then
    PREV_CONTAINER_ID=""
    PREV_IMAGE=""
    return 0
  fi
  if [[ "$container_ids" == *$'\n'* ]]; then
    echo "Docker returned multiple exact-name containers; refusing to continue." >&2
    return 1
  fi

  if ! image="$(docker inspect --format '{{.Config.Image}}' "$container_ids")"; then
    echo "Docker inspection failed; refusing to remove or replace the current container." >&2
    return 1
  fi
  if [[ -z "$image" ]]; then
    echo "Docker inspection returned no image; refusing to remove the current container." >&2
    return 1
  fi

  PREV_CONTAINER_ID="$container_ids"
  PREV_IMAGE="$image"
}

should_rollback_public_check() {
  # Exit 3 is the explicit transport/no-successful-response outcome. Every
  # other failed public check is treated as a verification mismatch.
  [[ "${1:-}" != 3 ]]
}
