#!/usr/bin/env bash
# Deploy a Cloud Run (doc 07 §5.3). La API key va por --set-env-vars, nunca
# dentro de la imagen ni en el repo.
#
# Uso:
#   PROJECT=mi-proyecto REGION=us-central1 ANTHROPIC_API_KEY=sk-... ./deploy.sh
#
# PROJECT y REGION son obligatorios; REGION cae a us-central1 si no se pasa.
# ANTHROPIC_API_KEY debe estar en el entorno (p.ej. `export $(cat .env | xargs)`
# o exportada a mano) — nunca se hardcodea acá.

set -euo pipefail

: "${PROJECT:?Falta PROJECT (tu-project-id de GCP)}"
: "${REGION:=us-central1}"
: "${ANTHROPIC_API_KEY:?Falta ANTHROPIC_API_KEY en el entorno}"
# Memoria del agente (app/agent/): "memory" (default, se pierde al reciclar
# la instancia -- ver la nota de min/max-instances más abajo) o "firestore"
# (persiste de verdad entre instancias y reinicios; ver app/agent/README.md
# para el índice compuesto que necesita y el rol IAM `roles/datastore.user`
# en la cuenta de servicio de Cloud Run).
: "${AGENT_STORE_BACKEND:=memory}"
: "${AGENT_FIRESTORE_PROJECT:=$PROJECT}"

REPO=recomendador
SERVICE=recomendador
IMG="$REGION-docker.pkg.dev/$PROJECT/$REPO/app"
TAG=$(date +%H%M)

echo "==> Proyecto:  $PROJECT"
echo "==> Región:    $REGION"
echo "==> Imagen:    $IMG:$TAG"

# --- una sola vez (noop si ya existen) ---
gcloud artifacts repositories describe "$REPO" \
  --project="$PROJECT" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" \
    --project="$PROJECT" --repository-format=docker --location="$REGION"

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# --- cada deploy ---
docker build -t "$IMG:$TAG" -t "$IMG:latest" .
docker push "$IMG:latest"

gcloud run deploy "$SERVICE" \
  --project="$PROJECT" \
  --image="$IMG:latest" --region="$REGION" \
  --allow-unauthenticated --port=8080 \
  --min-instances=1 --max-instances=1 \
  --set-env-vars="ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,AGENT_STORE_BACKEND=$AGENT_STORE_BACKEND,AGENT_FIRESTORE_PROJECT=$AGENT_FIRESTORE_PROJECT"

# min=1 y max=1 NO son opcionales: la sesión de misión y el carrito viven en
# memoria del proceso (doc 03 §10.4, app/web/session.py). Con dos instancias,
# un request cae en la que no tiene la sesión y el carrito "desaparece".
# min=1 además mata el cold start. Esto NO cambia con AGENT_STORE_BACKEND=firestore:
# el agente sí recordaría la conversación entre instancias, pero el carrito
# y la canasta resuelta siguen siendo estado de proceso, así que la
# restricción de una sola instancia se mantiene igual.
echo "==> Deploy listo (1 instancia fija: el carrito vive en memoria)."
