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
* Attach the `VoltGuardEC2S3Role` instance profile; allocate an **Elastic IP** so `EC2_HOST` is stable.
* **Security group** (least privilege):

| Direction | Port | Source | Why |
|---|---|---|---|
| Inbound | 22/tcp | your IP (or GitHub runner ranges / use SSM instead) | SSH for deploy |
| Inbound | 8000/tcp | clients (`0.0.0.0/0`, or a restricted range) | API (host 8000 -> container 8000) |
| Outbound | all (default) | | ECR, S3 |

  Do not open 80, 5000, or 9090 for this deployment. For HTTPS put an ALB/CloudFront or Caddy/nginx in front (not included). `/metrics` is served on port 8000; block it at the proxy/ALB if the API is public.
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

Add the secrets from `docs/ci-cd.md`, then push to `main` (or run the *CD* workflow manually).

Manual deploy (what the pipeline does):

```bash
ssh -i key.pem ubuntu@$EC2_HOST
export AWS_REGION=ap-south-1 ECR_REGISTRY=<acct>.dkr.ecr.ap-south-1.amazonaws.com ECR_REPOSITORY=voltguard-api \
       IMAGE_TAG=<git-sha> DVC_REMOTE_URL=s3://<bucket>/voltguard HOST_PORT=8000 API_KEY=<secret>
bash /tmp/voltguard/deploy.sh
```

## 7. Test it

```bash
curl http://$EC2_HOST:8000/health
curl http://$EC2_HOST:8000/model-info
curl -X POST http://$EC2_HOST:8000/predict -H 'Content-Type: application/json' -H "X-API-Key: $API_KEY" -d @examples/predict_request.json
```

## Troubleshooting

* `NoCredentialsError` in container logs -> instance profile missing or hop limit is 1.
* `Checksum mismatch` / `alias` errors -> `dvc.lock` in the image is not from the run that pushed the model, or the model was not promoted to `champion`.
* `docker logs voltguard-api` shows bootstrap output first.
