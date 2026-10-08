# CI/CD (GitHub Actions)

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yml` | pull requests, pushes to non-main branches | lint (ruff) -> pytest -> synthetic-data pipeline smoke test. No AWS access needed, so it also works on forks |
| `cd.yml` | push to `main`, manual | `test` -> `pipeline` -> `build-push` -> `deploy` |

## `cd.yml` step by step

1. **test** - checkout, Python 3.11, install, `ruff`, `pytest`.
2. **pipeline** - configure AWS, point DVC at `s3://$DVC_S3_BUCKET/voltguard`, pull all outputs described by the committed `dvc.lock`, then run **`dvc repro evaluate`**. With unchanged inputs, this reuses the locked outputs. The quality gate runs before MLflow registration, so a rejected evaluation cannot create/promote a model version. Before registration, a DVC dry run checks whether the registry stage needs to execute; if it does, a persistent `MLFLOW_TRACKING_URI` is required. A release check verifies the manifest hash matches `dvc.lock`, verifies the bundle SHA-256, and requires a promoted `champion` alias. Finally, `dvc push` publishes any new outputs and uploads this run's lock + manifest.
3. **build-push** - download that exact `dvc.lock`, log in to ECR, build the image from it, and push `:<git sha>` **and** `:latest`. Deployment uses only the immutable commit SHA tag.
4. **deploy** - copy `scripts/deploy.sh` to EC2 and run it over SSH with the exact image SHA and expected model version. The EC2 instance role supplies ECR/S3 read access; the script publishes host port **8000** to container port **8000**, waits for `/health` and `/model-info` to report the expected champion version, and restores the previous image if startup or verification fails. The runner checks the public `http://$EC2_HOST:8000` endpoints.

Deployments are always by immutable SHA tag - `latest` is only a convenience.

## Required GitHub Secrets

| Secret | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | GitHub Actions CI IAM user (S3 list/read/write for DVC, ECR push; no EC2 keys) |
| `DVC_S3_BUCKET` | bucket name only (no `s3://`) |
| `ECR_REPOSITORY` | e.g. `voltguard-api` |
| `EC2_HOST` | public DNS/IP (Elastic IP recommended) |
| `EC2_USERNAME` | Ubuntu EC2 login user (commonly `ubuntu`) |
| `EC2_SSH_KEY` | private key (PEM contents) for that user |

## Optional or Conditional Values

| Name | Requirement |
|---|---|
| `AWS_REGION` | Not a secret. The workflow uses `ap-south-1` consistently for AWS, DVC, ECR, and EC2. |
| `API_KEY` | Optional. When omitted or empty, `/predict` is unauthenticated; when set, clients must send it as `X-API-Key`. |
| `MLFLOW_TRACKING_URI` | Conditional. Needed only when the DVC dry run says `register_model` must execute. Use a persistent remote URI; the workflow fails closed if registration would run without it, because a fresh runner's SQLite registry cannot preserve champion history. |

GitHub secret presence cannot be queried from the repository checkout. Confirm the required names above are configured and add `MLFLOW_TRACKING_URI` if model registration needs to run.

GitHub Actions currently uses long-lived AWS access-key secrets because that is the existing authentication design. The EC2 host uses the `VoltGuardEC2S3Role` instance profile for ECR/S3 read access and has no AWS keys in the deployment. GitHub OIDC is not enabled; it requires an AWS IAM role trust policy for this repository and replacing the access-key configuration with that role ARN.

## Prerequisites before the first run

`data/raw.dvc` and the current `dvc.lock` committed, and their referenced DVC outputs pushed to S3; ECR repo + EC2 host + IAM roles created (`docs/aws-deployment.md`). The lockfile must be present so CI and the Docker image pin the same manifest/model release.

## Security notes / trade-offs

* SSH from GitHub-hosted runners needs port 22 reachable from the runner (GitHub-hosted runner IPs change). Keep SSH key-only and restrict source IPs where practical, or later migrate deployment to AWS SSM. Prefer GitHub OIDC once the AWS trust policy is configured.
* Secrets are never echoed; they are passed via `env`. Third-party actions are pinned to major/minor tags - pin to commit SHAs for stricter supply-chain control.
* This audit did not execute the workflow or deploy to AWS. Repository secret presence and live EC2 behavior could not be queried here.
