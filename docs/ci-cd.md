# CI/CD (GitHub Actions)

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yml` | pull requests, pushes to non-main branches | lint (ruff) -> pytest -> synthetic-data pipeline smoke test. No AWS access needed, so it also works on forks |
| `cd.yml` | push to `main`, manual | `release-preflight` -> `test` -> `pipeline` -> `build-push` -> `deploy` |

## `cd.yml` step by step

1. **release-preflight** - before tests, DVC work, or image builds, verify the non-environment deployment secrets, the EC2 instance ID, HTTPS URL/approved-host configuration, and that the instance is online in Systems Manager. The production `API_KEY` is validated later in `deploy` after the protected environment gate. The HTTPS validator rejects non-HTTPS schemes, userinfo, query/fragment, paths, malformed authorities/ports, IP/localhost hosts, and host mismatches. It normalizes hostname case, a single trailing dot, and explicit numeric port 443 to a canonical HTTPS origin. It performs no network request and never disables TLS verification.
2. **test** - checkout, install Python 3.11 dependencies, run `ruff`, `pytest`, and the synthetic smoke test.
3. **pipeline** - configure AWS and DVC, pull all outputs described by the committed `dvc.lock`, then dry-run through `evaluate`. If the evaluation stages are unchanged, validate the locked registration inputs, manifest, and bundle, and reuse that release without invoking `register_model` or requiring MLflow settings. If an evaluation stage changed, require and validate an approved HTTPS tracking URI before running evaluation. Then verify the updated DVC-locked evaluation metrics and model bundle, run the quality gate and `dvc metrics show`, and dry-run `register_model`. Registration runs only if DVC explicitly reports that stage would run. The release check after registration requires a promoted `champion` alias and verifies the DVC manifest hash and bundle SHA-256. Finally, `dvc push` publishes any new outputs.
4. **build-push** - download that exact `dvc.lock`, log in to ECR, build the image from it, and push `:<git sha>` and `:latest`. The repository is configured as **Immutable with exclusions**, with only `latest` excluded; commit-SHA tags therefore cannot be overwritten.
5. **deploy** - wait at the GitHub `production` environment, then invoke the EC2 deployment through SSM Run Command. The API key is stored briefly as an encrypted Parameter Store `SecureString`; the command payload contains only its parameter name, and the EC2 script writes the decrypted value directly to a mode-600 temporary file without printing it. The deploy script removes that file on normal exit, and the runner deletes the SecureString parameter in a `finally` path. Runner cancellation/loss or EC2 loss can interrupt cleanup and leave the encrypted parameter or a temporary host file; cleanup must be checked after abnormal termination. Docker stores container environment values, visible to Docker administrators. Configure required reviewers and branch restrictions on the GitHub environment; the YAML declaration alone does not prove an approval gate exists. The EC2 instance role supplies ECR/S3 read access plus narrowly scoped `ssm:GetParameter` for `/voltguard/deploy/*`; the script publishes host port **8000** to container port **8000**, aborts if listing/inspection of a prior exact-name container fails, verifies local `/health` and API-key-protected `/model-info` (including expected model version and `champion` alias) at `127.0.0.1`, then checks unauthenticated public HTTPS `/health` for the expected version. A successful public HTTPS response with invalid/malformed health data or the wrong version triggers rollback. If TLS/connection fails or no successful health response arrives after local verification passes, verification fails but leaves the locally healthy service running. All curl calls retain normal certificate verification.

The live ECR repository was verified as **Immutable with exclusions**, with `latest` as the only exclusion. Deployments select the immutable commit-SHA tag.

## Required GitHub Secrets

| Secret | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | GitHub Actions CI IAM user (S3 list/read/write for DVC, ECR push; no EC2 keys) |
| `DVC_S3_BUCKET` | bucket name only (no `s3://`) |
| `ECR_REPOSITORY` | e.g. `voltguard-api` |
| `EC2_INSTANCE_ID` | EC2 instance ID managed by Systems Manager (currently `i-010f53e6c94892a04`) |
| `API_KEY` | Required for deployment; protects `POST /predict`, `/model-info`, and `/metrics` with `X-API-Key`. Read by the `deploy` job after `environment: production` approval (not by early preflight). |
| `MLFLOW_TRACKING_URI` | Secret; required only when evaluation stages change. Must be an HTTPS URL for the persistent MLflow tracking server. Credentials must not be embedded in the URI. |
| `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD` | Optional secrets for MLflow HTTP basic authentication; configure both when required by the approved server. |

## Required GitHub Repository Variables

| Variable | Purpose |
|---|---|
| `PRODUCTION_HTTPS_URL` | Public HTTPS API origin, without a trailing slash or path. The early release preflight checks syntax and exact hostname; the deploy script later performs a public health request with curl's normal TLS certificate verification. |
| `PRODUCTION_HTTPS_HOST` | Exact approved DNS hostname for `PRODUCTION_HTTPS_URL`, without scheme, port, or path. Set as a repository or organization variable so the early preflight can read it. |

## Optional or Conditional Values

| Name | Requirement |
|---|---|
| `AWS_REGION` | Not a secret. The workflow uses `ap-south-1` consistently for AWS, DVC, ECR, and EC2. |
| `MLFLOW_TRACKING_ALLOWED_HOST` | Repository variable; exact approved host (and non-default port, if used), without scheme or path. Set only after confirming the HTTPS server uses persistent database-backed registry storage and durable artifacts. The workflow compares the URI authority against this allowlist; it does not contact or prove the server's persistence. |

Authentication is required by default, including in the production image. Missing server-side key configuration returns HTTP 503; missing or incorrect request keys return HTTP 401. `/health` remains available for deployment checks. Local development or tests must explicitly set `REQUIRE_API_KEY=false` to opt out.

GitHub secret and variable presence cannot be queried from the repository checkout. No persistent MLflow server or approved host is verified in this audit. Configure `MLFLOW_TRACKING_URI` and `MLFLOW_TRACKING_ALLOWED_HOST` only after provisioning and verifying the tracking server, database-backed model registry, durable artifact storage, access controls, and backups. The unchanged locked-v2 reuse path does not need these settings. MLflow supports HTTP(S) tracking-server URIs and local/database-backed stores; this workflow intentionally accepts only HTTPS server URLs for changed evaluation/registration. URI syntax and host allowlisting are validated without contacting the service. See [MLflow tracking URI documentation](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.config.html) and [backend store requirements](https://mlflow.org/docs/latest/tracking/backend-stores/).

GitHub Actions currently uses long-lived AWS access-key secrets because that is the existing authentication design. The EC2 host uses the `VoltGuardEC2S3Role` instance profile for ECR/S3 read access and has no AWS keys in the deployment. GitHub OIDC is not enabled; it requires an AWS IAM role trust policy for this repository and replacing the access-key configuration with that role ARN.

## Prerequisites before the first run

`data/raw.dvc` and the current `dvc.lock` committed, and their referenced DVC outputs pushed to S3; ECR repo + EC2 host + IAM roles created (`docs/aws-deployment.md`). The lockfile must be present so CI and the Docker image pin the same manifest/model release.

## Security notes / trade-offs

* Deployment uses Systems Manager; no inbound SSH rule or host-key exception is required for GitHub-hosted runners. Keep SSH restricted for operator access. The GitHub AWS identity needs scoped `ssm:SendCommand`, `ssm:GetCommandInvocation`, `ssm:DescribeInstanceInformation`, `ssm:PutParameter`, and `ssm:DeleteParameter` permissions. Scope send-command to the single EC2 instance and `AWS-RunShellScript`; scope parameter access to `/voltguard/deploy/*`. The EC2 instance role needs `ssm:GetParameter` on that parameter path. Keep the SSM agent online.
* Port 8000 serves plain HTTP on loopback/host mapping. Public clients must never send `X-API-Key` over HTTP. Public `/health` is unauthenticated; authenticated `/model-info` runs on EC2 at `http://127.0.0.1:8000/model-info` inside the SSM command. Direct public access to port 8000 must remain blocked; serve clients through the verified HTTPS proxy. The API key is encrypted in Parameter Store and is not embedded in the SSM command text or command arguments. Runner cancellation/loss or EC2 loss can interrupt cleanup and leave an encrypted parameter or temporary host file; check both after abnormal runs. Docker administrators can inspect the running container environment.
* Secrets are never echoed; they are passed via `env`. AWS account IDs are masked in the credential setup steps. Third-party actions are pinned to major/minor tags - pin to commit SHAs for stricter supply-chain control.
* The ECR repository setting and remote v2 DVC hashes were verified. The SSM workflow path is code-prepared but still requires GitHub IAM permissions, EC2 `ssm:GetParameter`, and the `EC2_INSTANCE_ID` GitHub secret before a workflow run. No deployment was performed.
