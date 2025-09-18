#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
SAM_PID_FILE="$PROJECT_ROOT/local/.sam-local-lambda.pid"
SAM_LOG_FILE="$PROJECT_ROOT/local/sam-local.log"
UPLOAD_BUCKET="${UPLOAD_BUCKET:-serverless-ai-upload-local}"
MASK_BUCKET="${MASK_BUCKET:-serverless-ai-masks-local}"
OUTPUT_BUCKET="${OUTPUT_BUCKET:-serverless-ai-output-local}"
SAM_NETWORK="${SAM_NETWORK:-lambda_default}"
SAM_ENV_FILE="${SAM_ENV_FILE:-local/sam-env.json}"
SAM_LAMBDA_ENDPOINT="${SAM_LAMBDA_ENDPOINT:-http://127.0.0.1:3001}"
CLEAN_VOLUMES=false
START_SAM=true
WIRE_EVENTS=true
SETUP_BUCKETS=true
REBUILD_SAM=false
COMPOSE_BIN=""
COMPOSE_CMD=()

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Restart the local Lambda development stack (LocalStack, mock SageMaker, and sam local).

Options:
  --clean-volumes       Remove Docker volumes when tearing the stack down.
  --skip-sam            Do not start 'sam local start-lambda'.
  --skip-wire           Do not call local/wire_local_events.py.
  --skip-buckets        Skip bucket provisioning via local/setup-local.sh.
  --rebuild-sam         Run 'sam build --use-container' before starting sam local.
  --help                Display this help message.

Environment variables:
  UPLOAD_BUCKET, MASK_BUCKET, OUTPUT_BUCKET
      Override the LocalStack bucket names (defaults defined in local/setup-local.sh).
  SAM_NETWORK
      Docker network name used by 'sam local start-lambda' (default: lambda_default).
  SAM_ENV_FILE
      Path to the sam local environment JSON file (default: local/sam-env.json).
  SAM_LAMBDA_ENDPOINT
      Endpoint URL for lambda invocations when wiring events (default: http://127.0.0.1:3001).
  COMPOSE_COMMAND
      Override the docker compose command (default resolves to 'docker compose' or 'docker-compose').
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean-volumes)
      CLEAN_VOLUMES=true
      shift
      ;;
    --skip-sam)
      START_SAM=false
      shift
      ;;
    --skip-wire)
      WIRE_EVENTS=false
      shift
      ;;
    --skip-buckets)
      SETUP_BUCKETS=false
      shift
      ;;
    --rebuild-sam)
      REBUILD_SAM=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

ensure_command() {
  local name=$1
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Required command '$name' not found in PATH." >&2
    exit 1
  fi
}

resolve_compose() {
  if [[ -n "${COMPOSE_COMMAND:-}" ]]; then
    echo "$COMPOSE_COMMAND"
    return
  fi

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  else
    echo "Unable to locate docker compose command. Install Docker Compose v2." >&2
    exit 1
  fi
}

bring_down_stack() {
  echo "Stopping Docker services..."
  if [[ $CLEAN_VOLUMES == true ]]; then
    "${COMPOSE_CMD[@]}" down --remove-orphans -v
  else
    "${COMPOSE_CMD[@]}" down --remove-orphans
  fi
}

wait_for_service() {
  local service=$1
  local retries=${2:-30}
  local sleep_seconds=${3:-5}
  local attempt=1

  while (( attempt <= retries )); do
    local container_id
    container_id=$("${COMPOSE_CMD[@]}" ps -q "$service" || true)
    if [[ -n "$container_id" ]]; then
      local status
      status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")
      if [[ "$status" == "healthy" || "$status" == "running" ]]; then
        echo "Service '$service' is $status."
        return 0
      fi
      echo "Service '$service' status: $status (attempt $attempt/$retries)"
    else
      echo "Waiting for container of service '$service' to start (attempt $attempt/$retries)..."
    fi
    ((attempt++))
    sleep "$sleep_seconds"
  done

  echo "Service '$service' failed to become healthy within timeout." >&2
  return 1
}

bring_up_stack() {
  echo "Starting Docker services..."
  "${COMPOSE_CMD[@]}" up -d --build
  wait_for_service localstack
  wait_for_service sagemaker
}

stop_sam_local() {
  if [[ -f "$SAM_PID_FILE" ]]; then
    local pid
    pid=$(cat "$SAM_PID_FILE" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "Stopping 'sam local start-lambda' (PID $pid)..."
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
    rm -f "$SAM_PID_FILE"
  fi

  if pgrep -f "sam local start-lambda" >/dev/null 2>&1; then
    echo "Killing stray 'sam local start-lambda' processes..."
    pkill -f "sam local start-lambda" || true
  fi
}

build_sam() {
  if [[ $REBUILD_SAM == true ]]; then
    ensure_command sam
    echo "Building SAM application..."
    (cd "$PROJECT_ROOT" && sam build --use-container)
  fi
}

start_sam_local() {
  if ! command -v sam >/dev/null 2>&1; then
    echo "SAM CLI not found; skipping 'sam local start-lambda'." >&2
    return 1
  fi
  if [[ ! -f "$PROJECT_ROOT/$SAM_ENV_FILE" ]]; then
    echo "SAM environment file '$SAM_ENV_FILE' not found relative to project root; skipping sam local start-lambda." >&2
    return 1
  fi

  if pgrep -f "sam local start-lambda" >/dev/null 2>&1; then
    echo "'sam local start-lambda' appears to already be running; skipping start."
    return 0
  fi

  echo "Starting 'sam local start-lambda'..."
  (cd "$PROJECT_ROOT" && sam local start-lambda \
    --docker-network "$SAM_NETWORK" \
    --env-vars "$SAM_ENV_FILE" \
    > "$SAM_LOG_FILE" 2>&1 & echo $! > "$SAM_PID_FILE")

  sleep 2
  local pid
  pid=$(cat "$SAM_PID_FILE" 2>/dev/null || true)
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "Failed to launch 'sam local start-lambda'. Check $SAM_LOG_FILE for details." >&2
    return 1
  fi
  echo "'sam local start-lambda' running (PID $pid). Logs: $SAM_LOG_FILE"
}

setup_buckets() {
  if [[ $SETUP_BUCKETS == false ]]; then
    echo "Skipping bucket provisioning as requested."
    return 0
  fi

  if ! command -v awslocal >/dev/null 2>&1; then
    echo "awslocal not found; skipping bucket provisioning." >&2
    return 0
  fi

  echo "Provisioning LocalStack buckets..."
  UPLOAD_BUCKET="$UPLOAD_BUCKET" \
  MASK_BUCKET="$MASK_BUCKET" \
  OUTPUT_BUCKET="$OUTPUT_BUCKET" \
    "$PROJECT_ROOT/local/setup-local.sh"
}

wire_events() {
  if [[ $WIRE_EVENTS == false ]]; then
    echo "Skipping bucket notification wiring as requested."
    return 0
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found; skipping bucket notification wiring." >&2
    return 0
  fi

  echo "Configuring S3 notifications to invoke local Lambdas..."
  if ! python3 "$PROJECT_ROOT/local/wire_local_events.py" \
    --upload-bucket "$UPLOAD_BUCKET" \
    --mask-bucket "$MASK_BUCKET" \
    --lambda-endpoint "$SAM_LAMBDA_ENDPOINT"; then
    echo "Warning: wiring S3 notifications failed. Ensure sam local is running and try again." >&2
  fi
}

main() {
  cd "$PROJECT_ROOT"
  COMPOSE_BIN=$(resolve_compose)
  COMPOSE_CMD=($COMPOSE_BIN -f "$COMPOSE_FILE")
  ensure_command docker
  stop_sam_local
  bring_down_stack
  bring_up_stack
  setup_buckets
  build_sam
  if [[ $START_SAM == true ]]; then
    start_sam_local || true
  else
    echo "Skipping 'sam local start-lambda' startup."
  fi

  if [[ $WIRE_EVENTS == true ]]; then
    wire_events
  fi

  echo "Stack restart complete."
}

main "$@"
