# DVC

## What is versioned by DVC

| Path | Kind | Notes |
|---|---|---|
| `data/raw` | tracked dataset (`data/raw.dvc`) | added manually with `dvc add` |
| `data/interim`, `data/processed`, `artifacts/preprocessors/preprocessor.joblib` | stage outputs | reproducible from raw data + params |
| `artifacts/models/candidates/` | stage output | every trained candidate |
| `artifacts/models/voltguard_bundle.joblib`, `manifest.json` | **the deployable model artifact** | pulled at deployment |
| `artifacts/metrics/*.json` | DVC *metrics* (`cache: false`) | stay in Git so `dvc metrics diff` works |

## Pipeline (`dvc.yaml`)

`data_ingestion -> preprocess -> train -> evaluate -> register_model`. Parameters come from `params.yaml`; changing e.g. `train.models.random_forest.n_estimators` re-runs only `train` and downstream stages.

```bash
dvc dag                      # show the DAG
dvc repro                    # run what changed
dvc repro -f train           # force one stage (and downstream)
dvc params diff              # compare params with last commit
dvc metrics show / diff      # compare metrics between commits
```

## S3 remote (no credentials in Git)

```bash
export AWS_REGION=ap-south-1 DVC_S3_BUCKET=<globally-unique-name>
bash scripts/create_dvc_bucket.sh                         # private, versioned bucket
dvc remote modify storage url s3://$DVC_S3_BUCKET/voltguard
dvc remote modify storage region $AWS_REGION
git add .dvc/config && git commit -m "Configure DVC remote"
# credentials: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars, `aws configure`, or an IAM role
dvc push
```

Secrets/overrides go in `.dvc/config.local` (git-ignored): `dvc remote modify --local storage url ...`.

## Retrieving an old model

```bash
git checkout <old-commit>            # restores dvc.lock / data/raw.dvc pointers
dvc pull artifacts/models/voltguard_bundle.joblib artifacts/models/manifest.json
```

## How the container uses DVC

The image contains `.dvc/config`, `dvc.yaml` and the `dvc.lock` produced by the CI run (no Git history, no data, no model). `scripts/bootstrap_model.py` sets `core.no_scm`, applies `DVC_REMOTE_URL`, runs `dvc pull` for the two model files, and verifies the manifest alias + SHA-256. I verified this exact flow against a *local* DVC remote with synthetic data; the S3 variant differs only in the remote URL/credentials.
