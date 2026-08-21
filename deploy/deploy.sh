#!/usr/bin/env bash
# Stand up the full OTel self-healing stack in a Databricks workspace, from scratch.
# Everything is codified: data -> embedding serving + index -> LLM serving -> capture ->
# grants -> the animated app. Idempotent; safe to re-run.
#
# Usage:
#   ./deploy/deploy.sh <databricks-cli-profile>
# Example:
#   ./deploy/deploy.sh fevm-cmegdemos
set -euo pipefail

PROFILE="${1:?pass a Databricks CLI profile, e.g. fevm-cmegdemos}"
CATALOG="${OTEL_CATALOG:-cmegdemos_catalog}"
SCHEMA="${OTEL_SCHEMA:-otel_selfhealing}"
APP_NAME="${OTEL_APP:-otel-vision}"
WAREHOUSE_ID="${OTEL_WAREHOUSE_ID:-3dca5b181c86a82c}"
LLM_ENDPOINT="${OTEL_LLM_ENDPOINT:-otel-llm-1b-it}"   # reuse governed OTel LLM; or set to your own from 02

ME="$(databricks current-user me --profile "$PROFILE" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')"
WS_DEPLOY="/Workspace/Users/${ME}/otel-selfhealing/deploy"
WS_APPSRC="/Workspace/Users/${ME}/otel-vision-src"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

echo "==> profile=$PROFILE  user=$ME  catalog=$CATALOG.$SCHEMA"

run_nb () {  # run a deploy notebook as a one-shot job, passing shared params
  local nb="$1"; shift
  echo "==> running $nb"
  databricks jobs submit --profile "$PROFILE" --json "$(python3 - "$WS_DEPLOY/$nb" "$@" <<'PY'
import json,sys
path=sys.argv[1]; params=dict(a.split("=",1) for a in sys.argv[2:])
print(json.dumps({"run_name":f"otel-{path.split('/')[-1]}","tasks":[{
  "task_key":"t","notebook_task":{"notebook_path":path,"base_parameters":params}}]}))
PY
)"
}

# 1. upload deploy notebooks + app source
echo "==> syncing deploy notebooks -> $WS_DEPLOY"
databricks sync "$HERE" "$WS_DEPLOY" --profile "$PROFILE" --full
echo "==> syncing app source -> $WS_APPSRC"
databricks sync "$ROOT/app" "$WS_APPSRC" --profile "$PROFILE" --full

# 2. build the stack (each waits for completion)
run_nb 00_seed_data.py       "catalog=$CATALOG" "schema=$SCHEMA"
run_nb 01_serve_embedding.py "catalog=$CATALOG" "schema=$SCHEMA"
run_nb 02_serve_llm.py       "catalog=$CATALOG" "schema=$SCHEMA"    # comment out to reuse an existing OTel LLM
run_nb 03_govern_capture.py  "catalog=$CATALOG" "schema=$SCHEMA"

# 3. create the app (if needed) to mint its service principal, then grant it
databricks apps get "$APP_NAME" --profile "$PROFILE" >/dev/null 2>&1 || \
  databricks apps create "$APP_NAME" --profile "$PROFILE"
APP_SP="$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["service_principal_client_id"])')"
run_nb 04_grant_app.py "catalog=$CATALOG" "schema=$SCHEMA" "app_sp=$APP_SP" "llm_endpoint=$LLM_ENDPOINT" "warehouse_id=$WAREHOUSE_ID"

# 4. deploy the app
echo "==> deploying app $APP_NAME"
databricks apps deploy "$APP_NAME" --source-code-path "$WS_APPSRC" --profile "$PROFILE"
databricks apps get "$APP_NAME" --profile "$PROFILE" -o json | python3 -c 'import sys,json;d=json.load(sys.stdin);print("APP URL:",d["url"])'
echo "==> done"
