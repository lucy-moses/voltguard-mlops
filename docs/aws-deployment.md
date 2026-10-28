# AWS deployment (S3 + ECR + EC2)

> **Status:** these commands were written from AWS documentation and not executed by me (no AWS account available). Run them in order and fix region/naming to your account. Expect to spend a little on EC2/S3/ECR - stop or terminate resources afterwards.

```bash
export AWS_REGION=ap-south-1
export DVC_S3_BUCKET=voltguard-dvc-<your-unique-suffix>
export ECR_REPOSITORY=voltguard-api
aws configure            # or use env vars / SSO with an admin-ish user for one-time setup
```

## 1. S3 bucket (DVC remote)

```bash
bash scripts/create_dvc_bucket.sh
dvc remote modify storage url s3://$DVC_S3_BUCKET/voltguard
dvc remote modify storage region $AWS_REGION
dvc push
```

## 2. ECR repository

```bash
bash scripts/create_ecr_repo.sh      # scan-on-push, keeps the last 15 images
```

## 3. IAM

**a) CI user** (its keys go into GitHub Secrets). Policy `voltguard-ci`:

```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::BUCKET" },
  { "Effect": "Allow", "Action": ["s3:GetObject","s3:PutObject"], "Resource": "arn:aws:s3:::BUCKET/*" },
  { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
  { "Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability","ecr:InitiateLayerUpload","ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload","ecr:PutImage","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
    "Resource": "arn:aws:ecr:REGION:ACCOUNT_ID:repository/voltguard-api" } ] }
```

**b) EC2 instance role** `VoltGuardEC2S3Role` (attached via an instance profile) - *no keys on the box*:

```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::BUCKET" },
  { "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::BUCKET/*" },
  { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
  { "Effect": "Allow", "Action": ["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:BatchCheckLayerAvailability"],
    "Resource": "arn:aws:ecr:REGION:ACCOUNT_ID:repository/voltguard-api" } ] }
```

The instance only needs *read* on S3 - it can fetch models but not modify them.

## 4. EC2 instance

* AMI: Ubuntu, type `t3.small` or larger (xgboost + sklearn + DVC need ~1 GB RAM), 20 GB gp3.
* Attach the `VoltGuardEC2S3Role` instance profile and keep the Systems Manager Agent online. CI targets the instance by ID, so a public IP is not required for deployment.
* **Security group** (least privilege):

| Direction | Port | Source | Why |
|---|---|---|---|
| Inbound | 22/tcp | operator IP only, or closed when using SSM exclusively | Optional manual SSH administration |
| Inbound | 8000/tcp | none from public clients; proxy access only if required | API (host 8000 -> container 8000) |
| Outbound | all (default) | | ECR, S3 |

  Do not open 5000 or 9090. Ports 80/443 may be open for the configured HTTPS proxy and certificate renewal. Never expose port 8000 publicly. `/metrics` is served on port 8000; block it at the proxy/ALB if the API is public.

### Systems Manager deployment permissions

The GitHub Actions AWS identity needs `ssm:DescribeInstanceInformation`, `ssm:SendCommand` (restricted to this instance and `AWS-RunShellScript`), `ssm:GetCommandInvocation`, and `ssm:PutParameter`/`ssm:DeleteParameter` on `arn:aws:ssm:ap-south-1:270068815292:parameter/voltguard/deploy/*`. The EC2 instance role needs `ssm:GetParameter` on that parameter path. The workflow stores the API key as a temporary `SecureString`; the Run Command payload contains only the parameter name. The workflow removes the parameter after the deployment command, and the remote script removes its temporary file on normal exit. Forced cancellation or host loss can interrupt cleanup.
* **IMDSv2 hop limit** - containers reach the instance role credentials only if the hop limit is 2:

```bash
aws ec2 modify-instance-metadata-options --instance-id i-XXXX --http-tokens required \
    --http-put-response-hop-limit 2 --http-endpoint enabled
```

## 5. Prepare the host once

```bash
scp -i key.pem scripts/setup_ec2.sh ubuntu@$EC2_HOST:~ && ssh -i key.pem ubuntu@$EC2_HOST 'bash setup_ec2.sh'
```

## 6. Configure GitHub and deploy

Configure the secrets and repository variables from `docs/ci-cd.md`, including `EC2_INSTANCE_ID`, `PRODUCTION_HTTPS_URL`, and its exact allowlisted `PRODUCTION_HTTPS_HOST`, only after HTTPS ingress is configured. These must be repository/organization variables available to the early preflight. The CD workflow fails closed before tests, DVC pipeline work, or image builds when either HTTPS setting is missing, malformed, or mismatched, or when the EC2 instance is not online in Systems Manager. Do not push to `main` or dispatch the *CD* workflow for production before the HTTPS endpoint and certificate are configured and verified.

Manual deploy (same locked-image flow as the pipeline; production remains blocked until HTTPS is configured):

```bash
ssh -i key.pem ubuntu@$EC2_HOST
export AWS_REGION=ap-south-1 ECR_REGISTRY=<acct>.dkr.ecr.ap-south-1.amazonaws.com ECR_REPOSITORY=voltguard-api \
       IMAGE_TAG=<git-sha> DVC_REMOTE_URL=s3://<bucket>/voltguard HOST_PORT=8000 \
       API_KEY_FILE=/tmp/voltguard/api-key.env EXPECTED_MODEL_VERSION=<locked-version> \
       PRODUCTION_HTTPS_URL=<approved-https-origin>
bash /tmp/voltguard/deploy.sh
```

For a manual operator deployment, transfer both scripts and a mode-600 API-key env file over an authenticated SSH session; do not put the key in shell command arguments or terminal history. CI uses Systems Manager and a temporary Parameter Store `SecureString` instead. The deploy script removes the remote file on normal exit. Runner cancellation/loss or EC2 loss can interrupt cleanup.

## 7. Test it

```bash
curl --fail "$PRODUCTION_HTTPS_URL/health"
```

Never send `X-API-Key` to a public HTTP URL. The deploy script verifies authenticated `/model-info` locally on EC2 at `http://127.0.0.1:8000/model-info` through Systems Manager. Public protected API calls and production use require HTTPS with a valid certificate and no direct public access to port 8000.

## Troubleshooting

* `NoCredentialsError` in container logs -> instance profile missing or hop limit is 1.
* `Checksum mismatch` / `alias` errors -> `dvc.lock` in the image is not from the run that pushed the model, or the model was not promoted to `champion`.
* `docker logs voltguard-api` shows bootstrap output first.
