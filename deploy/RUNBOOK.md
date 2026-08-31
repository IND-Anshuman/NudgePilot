# NudgePilot — Deployment Runbook (Google Cloud)
> Deploy the agent as a scale-to-zero Cloud Run service triggered daily by Cloud Scheduler.

## Prerequisites
1. Google Cloud project with billing (grab the **$150 hackathon credit** via the Devpost Resources tab).
2. `gcloud` CLI + `gcloud auth login`; ADC for local: `gcloud auth application-default login`.
3. **Enable APIs**:
   ```
   gcloud services enable run.googleapis.com firestore.googleapis.com \
     cloudscheduler.googleapis.com pubsub.googleapis.com aiplatform.googleapis.com
   ```
4. Create a Firestore DB (Native mode):
   ```
   gcloud firestore databases create --region=us-central1
   ```

## 1. Deploy the Cloud Run service
```bash
cd cloud
# build from the repo root Dockerfile
gcloud builds submit --tag gcr.io/$GOOGLE_CLOUD_PROJECT/nudgepilot .

gcloud run deploy nudgepilot \
  --image gcr.io/$GOOGLE_CLOUD_PROJECT/nudgepilot \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 300 \
  --set-env-vars NUDGEPILOT_STORE=firestore,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT
```
The service exposes:
- `GET  /health`  — liveness / billing-zero proof
- `POST /run`     — runs one full NudgePilot tick (intake→nudge→ghost→digest) and returns the JSON digest
- `GET  /docs`    — Swagger UI (nice for the demo video)

## 2. Schedule the daily tick (Cloud Scheduler → Pub/Sub → Cloud Run)
```bash
gcloud pubsub topics create nudgepilot-tick

gcloud scheduler jobs create http nudgepilot-daily \
  --schedule="0 6 * * *" \
  --uri="REPLACE_WITH_RUN_URL/run" \
  --http-method=POST \
  --oidc-service-account-email=YOUR-SERVICE-ACCOUNT@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --location us-central1
```
The Cloud Run service account needs:
- `roles/datastore.user` (Firestore)
- `roles/aiplatform.user` (Vertex/Gemini)
- `roles/secretmanager.secretAccessor` (for API key)

## 3. Wire real Gemini (Vertex) 
Set in the service env: `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT`, and a
service-account key stored in Secret Manager. `core/llm.py::GeminiBackend` reads ADC.

## 4. Gmail Watch (optional → real inbox)
Production uses Gmail API restricted scopes:
- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.compose`
Enable Gmail Watch → Pub/Sub so new emails push `nudgepilot/tick`. OAuth requires a
[verified app](https://support.google.com/cloud/answer/9110914) for production consent; for the
hackathon, run with **test users** and seed the inbox corpus (see `seed.py`) — this is documented
as production roadmap in `delivery/gmail_sink.py`.

## Demo proof checklist (video bullets)
- [x] `python nudgepilot_cli.py auto` — unedited end-to-end run (offline backend)
- [x] Cloud Run service listed & healthy (`/health` returns 200)
- [x] Firestore documents visible (`nudgepilot_applications` collection)
- [x] A scheduled tick fires from the Scheduler console
- [x] Billing shows near-zero (scale-to-zero)
- [x] `python -m unittest discover -s tests` — 15 green

## Cost
At demo scale: scale-to-zero Cloud Run + `gemini-3.5-flash` + ~30 Firestore docs
≈ **well under $1/month**. Project the $150 credit lasting months.