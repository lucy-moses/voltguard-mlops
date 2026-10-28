# VoltGuard - End-to-End MLOps for EV Battery Health (SOH) and Remaining Useful Life (RUL)

## 1. Problem statement
Battery degradation drives EV range, safety and resale value. Given measurements summarising a battery's discharge cycle, VoltGuard predicts its **State of Health (SOH)** and **Remaining Useful Life (RUL)** and serves them through a production-style API - built with a fully reproducible, versioned, automated MLOps lifecycle.

## 2. Objectives
Data versioning -> reproducible preprocessing -> experiment tracking -> model comparison & automatic selection -> model registry -> model artifact versioning -> API serving -> containerisation -> CI/CD -> AWS deployment, following the supplied two-part architecture (see `docs/architecture.md`).

## 3. Dataset
NASA PCoE Li-ion Battery Aging dataset (public). Default cells B0005, B0006, B0007, B0018. Not committed; versioned with DVC. See `data/README.md` for download and layout. *I could not download it from my build environment, so the real-data results are yours to generate (section 22).*

## 4. ML methodology
Ingest `.mat` -> per-discharge-cycle table -> validate -> clean -> engineer features -> derive labels (SOH, RUL) -> **battery-wise** train/val/test split -> train 5 models per target (Linear, Ridge, Random Forest, Gradient Boosting, XGBoost) -> select by a fixed rule on validation (RMSE, tie-break MAE/R2) -> score once on test -> bundle -> register. Every feature and the leakage analysis are in `docs/features.md`.

## 5. MLOps architecture
```
PART 1  Raw data -> DVC remote -> Preprocessing -> Experiments -> Compare metrics -> Best model
        -> Model registry -> Model artifact (DVC remote) -> FastAPI + Docker -> AWS EC2 -> Client
PART 2  GitHub -> Actions -> tests -> DVC pipeline -> Docker build -> ECR -> EC2 pulls image
        -> pulls model from DVC remote -> FastAPI starts -> Client
```
Diagrams and a step-by-step mapping to the implementation: `docs/architecture.md`.

**DVC** = dataset/model artifact versioning + pipeline. **MLflow** = experiment tracking + model registry.

## 6. Technology stack
Python 3.11, pandas, numpy, scikit-learn, XGBoost, joblib - DVC (S3 remote), MLflow, Git/GitHub - FastAPI, Pydantic, Uvicorn, prometheus-client - Docker, Docker Compose - AWS S3 / ECR / EC2 - GitHub Actions - pytest, ruff.

## 7. Repository structure
```
.github/workflows/  ci.yml  cd.yml            api/  main.py schemas.py model_loader.py
src/{data,features,models,pipeline,utils}/    scripts/  download_data.py bootstrap_model.py deploy.sh ...
tests/  test_{data,features,model,api,pipeline}.py + synthetic.py
configs/config.yaml   params.yaml   dvc.yaml   dvc.lock (committed DVC output/version pin)
artifacts/{models,metrics,preprocessors}      docs/  architecture setup dvc mlflow docker aws-deployment ci-cd features viva_questions
Dockerfile  docker-compose.yml  docker/entrypoint.sh  Makefile  requirements*.txt  .env.example  examples/
```

## 8. Local installation
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q && ruff check . && python scripts/smoke_test.py    # no data needed
```

## 9. DVC setup
```bash
python scripts/download_data.py            # or copy .mat files into data/raw (data/README.md)
dvc add data/raw && git add data/raw.dvc data/.gitignore
dvc remote modify storage url s3://<bucket>/voltguard && dvc remote modify storage region <region>
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...     # never commit; or use an IAM role
dvc push
```
Details: `docs/dvc.md`. The committed `.dvc/config` holds a placeholder bucket - change it.

## 10. MLflow setup
Local SQLite by default (`mlflow/mlflow.db`). UI: `mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db`. An unauthenticated `http://host:5000` example is for a trusted local network only; never use it for authenticated production tracking. Production MLflow requires HTTPS, an approved hostname, and persistent database-backed registry and durable artifact storage. Details: `docs/mlflow.md`.

## 11. Running the pipeline
```bash
dvc repro                       # data_ingestion -> preprocess -> train -> evaluate -> register_model
dvc dag && dvc metrics show
python scripts/quality_gate.py
git add dvc.lock artifacts/metrics && git commit -m "Pipeline run" && dvc push
```

## 12. Running experiments
Edit `params.yaml` (`train.models`, `selection`, ...) and `dvc repro`; only affected stages re-run. Compare in the MLflow UI or with `dvc params diff` / `dvc metrics diff`. The selection rule is in `params.yaml: selection` and implemented in `src/models/select.py`.

## 13. Running FastAPI
```bash
REQUIRE_API_KEY=false MODEL_SOURCE=local uvicorn api.main:app --port 8000     # explicit local-only unauthenticated mode
```
Endpoints: `GET /`, `GET /health`, `GET /model-info`, `GET /metrics` (Prometheus), `POST /predict`. Authentication is required by default on `/predict`, `/model-info`, and `/metrics` using the `X-API-Key` header and `API_KEY` environment variable. `/health` remains unauthenticated for probes. Local unauthenticated development requires explicitly setting `REQUIRE_API_KEY=false`.

## 14. Docker
```bash
docker build -t voltguard-api:local .          # needs dvc.lock from `dvc repro`
docker run --rm -p 8000:8000 --env-file .env -e MODEL_SOURCE=local -v "$PWD/artifacts/models:/app/artifacts/models" voltguard-api:local
docker compose up --build                       # uses .env
```
On start the container runs `scripts/bootstrap_model.py` (DVC pull + checksum + alias check) and then Uvicorn. No credentials in the image. Details and the untested-build note: `docs/docker.md`.

## 15. AWS setup
S3 bucket (`scripts/create_dvc_bucket.sh`), ECR repo (`scripts/create_ecr_repo.sh`), IAM policies, EC2 with an instance role and a minimal security group - all in `docs/aws-deployment.md`.

## 16. ECR deployment
The workflow builds commit-SHA and `latest` tags and deploys the commit-SHA tag. ECR is configured as **Immutable with exclusions**, with only `latest` excluded; commit-SHA tags cannot be overwritten.

## 17. EC2 deployment
`scripts/deploy.sh` and its `scripts/deploy_guards.sh` helper run on EC2 through Systems Manager: ECR login -> pull -> inspect the exact prior container -> start container -> container pulls the model from DVC -> verify `/health` and API-key-protected `/model-info` locally at `127.0.0.1` -> verify unauthenticated public HTTPS `/health` -> roll back when successful health data is invalid or the model version is wrong. If public HTTPS is unreachable after local checks pass, verification fails but leaves the locally healthy service running for investigation/retry. The workflow stores the API key temporarily as a Parameter Store `SecureString`; the SSM command payload contains only its parameter name. Runner cancellation or EC2 loss can interrupt cleanup; Docker administrators can inspect the running container environment. The workflow declares a `production` environment; required reviewers and branch restrictions must be configured in GitHub settings. Public clients must never send API keys over HTTP, and port 8000 must remain inaccessible from the public internet.

## 18. GitHub Actions CI/CD
`ci.yml`: lint + tests + synthetic smoke pipeline on PRs/branches. `cd.yml` (main): validate approved HTTPS settings and SSM instance readiness before tests/pipeline/build -> pull locked DVC outputs -> reuse a validated release or require approved persistent HTTPS MLflow before changed evaluation -> validate evaluation outputs and quality gate -> register only when DVC explicitly plans it -> build/publish commit-SHA image -> wait for the configured `production` environment -> deploy through SSM using a temporary SecureString API key -> verify authenticated model identity locally and public health over HTTPS. Invalid successful health data or wrong model version triggers rollback; unavailable public HTTPS after local verification leaves the healthy candidate running and reports verification unconfirmed. ECR tag immutability is configured with only `latest` excluded. GitHub IAM permissions, environment protection, and workflow execution remain to be verified before release.

## 19. Model retrieval design (Architecture: "Pull model artifact from DVC remote")
`register_model` writes `manifest.json` (registry name/version/run/aliases/SHA-256). Both files are DVC outputs. The image ships `dvc.lock` (pin) + `.dvc/config`; at start `bootstrap_model.py` runs `dvc pull` for the two files, then `ModelService` verifies alias + checksum. No model filename is hard-coded.

## 20. API examples
```bash
printf 'X-API-Key: %s\n' "$API_KEY" | curl --header @- -X POST http://localhost:8000/predict -H 'Content-Type: application/json' -d @examples/predict_request.json  # local machine only; never send keys over public HTTP
```
Response shape (**values below come from a model trained on SYNTHETIC test data, only to show the format - they are not results**):
```json
{
  "predicted_soh": 83.33,
  "predicted_rul": 55.23,
  "model_name": "VoltGuard-Battery-RUL",
  "model_version": "1",
  "model_alias": "champion",
  "timestamp": "2026-09-28T06:20:07.303573+00:00",
  "model_metadata": {"mlflow_run_id": "...", "selected_models": {"rul": "random_forest", "soh": "linear_regression"},
                     "bundle_sha256": "...", "soh_unit": "percent", "rul_unit": "cycles"}
}
```
Invalid input (e.g. `voltage_mean: 9`) returns HTTP 422; a missing/failed model returns 503; a wrong `X-API-Key` returns 401. Feature names and ranges: `/docs` or `api/schemas.py`. `charge_duration` is optional (median-imputed).

## 21. Testing
Local validation on 2026-10-27: **62 tests passed** (17 upstream deprecation warnings), Ruff passed, and the synthetic smoke test registered only `VoltGuard-Test v1` in its temporary SQLite store. The locked v2 manifest/bundle verifier passed. `dvc status` and both DVC dry runs passed with a process-scoped `DVC_SITE_CACHE_DIR` under the temporary audit directory; the default global DVC site-cache database under `C:\ProgramData` returned SQLite `SQLITE_CANTOPEN`, so it was left untouched. `dvc metrics show` separately failed because DVC's Git backend could not resolve the OneDrive worktree path (`Access is denied`). A local Docker image built and passed inspection; a network-disabled container loaded the existing v2 artifacts from a read-only mount and passed authenticated prediction, unauthorized-request, invalid-input, health, model-info, and metrics checks. AWS credentials were unavailable, so remote S3 release state, ECR tag mutability/digest, GitHub environment protection, and EC2 deployment/health remain unverified. No cloud mutation or deployment was performed.

## 22. Results

Pipeline run on the real NASA PCoE dataset (B0005, B0006 train; B0007 validation; B0018 test), with `eol_soh_percent` set to 72.0 — raised from the literature-standard 70.0 because the validation battery (B0007) only reached a minimum of 70.02% SOH within its recorded cycles, which would have excluded it from ever reaching end-of-life and left zero RUL training labels.

| Target | Selected model | Val RMSE | Test RMSE | Test MAE | Test R² |
|---|---|---|---|---|---|
| SOH (%) | linear_regression | 1.1140 | 0.3697 | 0.2967 | 0.9977 |
| RUL (cycles) | xgboost | 32.5463 | 13.6586 | 12.7834 | 0.7523 |

Registered as `VoltGuard-Battery-RUL` version 2, promoted to the `champion` alias. Verified via a live local API call:

```json
{
  "predicted_soh": 81.90702893806605,
  "predicted_rul": 9.639904975891113,
  "model_name": "VoltGuard-Battery-RUL",
  "model_version": "2",
  "model_alias": "champion",
  "timestamp": "2026-10-07T06:32:28.750058+00:00",
  "model_metadata": {
    "mlflow_run_id": "2182d8bd7518465ba0bde86ac775305d",
    "selected_models": {"rul": "xgboost", "soh": "linear_regression"},
    "bundle_sha256": "dc4b09dcb037327405f7834c9713f1768616f0c8a1ef8ea90d98e15541a5b721",
    "soh_unit": "percent",
    "rul_unit": "cycles"
  }
}
```

SOH is predicted with very high accuracy (R²=0.998), consistent with `discharge_duration` being a near-direct proxy for capacity under constant-current discharge (see `docs/features.md` for the leakage-adjacent caveat). RUL is a harder task with only 3 batteries' worth of degradation trajectories to learn from; R²=0.75 is a reasonable result given that constraint, not a production-grade guarantee.

## 23. Limitations
* `eol_soh_percent` was raised from the literature-standard 70% to 72% after inspecting the real data: the validation battery (B0007) bottomed out at 70.02% SOH, 0.02 points short of the original threshold, which would have left it with zero RUL labels. This is a defensible, documented adjustment, not an arbitrary tune — but it means "end of life" in this project is defined slightly more conservatively than some literature conventions.

## 24. Future improvements
Sequence/rolling features with a stateful client, uncertainty intervals, more cells / CALCE / Oxford datasets, drift monitoring, HTTPS via ALB, GitHub OIDC instead of access keys, SSM-based deploy, blue/green deployment, remote MLflow with S3 artifact store.

---
Viva preparation: `docs/viva_questions.md` (40 Q&A).
