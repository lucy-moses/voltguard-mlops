# CI/CD (GitHub Actions)

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yml` | pull requests, pushes to non-main branches | lint (ruff) -> pytest -> synthetic-data pipeline smoke test. No AWS access needed, so it also works on forks |
| `cd.yml` | push to `main`, manual | `test` -> `pipeline` -> `build-push` -> `deploy` |

## `cd.yml` step by step

1. **test** - checkout, Python 3.11, install, `ruff`, `pytest`.
2. **pipeline** - configure AWS, point DVC at `s3://$DVC_S3_BUCKET/voltguard`, `dvc pull data/raw.dvc`, **`dvc repro`**, **quality gate** (`scripts/quality_gate.py` fails the run if test RMSE exceeds `params.yaml: quality_gate`), `dvc metrics show`, **`dvc push`** (model artifact -> S3), upload `dvc.lock` + metrics + manifest as a workflow artifact.
3. **build-push** - download that `dvc.lock` (so the image is pinned to the model just produced), log in to ECR, `docker build`, push `:<git sha>` **and** `:latest`.
4. **deploy** - copy `deploy.sh` to EC2, run it over SSH with the image tag `= github.sha`; it logs in to ECR, pulls the image, starts the container (which pulls the model from S3 via DVC), waits for `/health`, rolls back to the previous image if unhealthy. A final `curl /health` from the runner confirms public reachability.

Deployments are always by immutable SHA tag - `latest` is only a convenience.

## GitHub Secrets

| Secret | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | CI IAM user (S3 read/write on the DVC bucket, ECR push) |
| `AWS_REGION` | e.g. `ap-south-1` |
| `DVC_S3_BUCKET` | bucket name only (no `s3://`) |
| `ECR_REPOSITORY` | e.g. `voltguard-api` |
| `EC2_HOST` | public DNS/IP (Elastic IP recommended) |
| `EC2_USERNAME` | e.g. `ec2-user` |
| `EC2_SSH_KEY` | private key (PEM contents) for that user |
| `API_KEY` | (optional) value clients must send as `X-API-Key` |
| `MLFLOW_TRACKING_URI` | (optional) remote MLflow server |

## Prerequisites before the first run

`data/raw.dvc` committed and data pushed; ECR repo + EC2 host + IAM roles created (`docs/aws-deployment.md`); an initial `dvc.lock` is *not* required in Git because CI regenerates it.

## Security notes / trade-offs

* SSH from GitHub-hosted runners needs port 22 reachable from GitHub's IP ranges (which change). Options: open 22 broadly with key-only auth (acceptable for a course project, weaker), or switch the deploy job to AWS SSM Run Command. Prefer GitHub OIDC roles over long-lived access keys for anything beyond a course project.
* Secrets are never echoed; they are passed via `env`. Third-party actions are pinned to major/minor tags - pin to commit SHAs for stricter supply-chain control.
* This workflow has **not been executed** by me (no AWS account/GitHub repo available). YAML syntax was validated and the underlying commands (`dvc repro`, `dvc push/pull`, bootstrap, API) were run locally against a local remote.
