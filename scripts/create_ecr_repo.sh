#!/usr/bin/env bash
# One-time: create the ECR repository (scan-on-push, immutable-ish lifecycle to cap storage).
set -euo pipefail
AWS_REGION="${AWS_REGION:?set AWS_REGION}"
REPO="${ECR_REPOSITORY:-voltguard-api}"
aws ecr describe-repositories --repository-names "$REPO" --region "$AWS_REGION" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$REPO" --region "$AWS_REGION" \
    --image-scanning-configuration scanOnPush=true
aws ecr put-lifecycle-policy --repository-name "$REPO" --region "$AWS_REGION" --lifecycle-policy-text '{
  "rules":[{"rulePriority":1,"description":"keep last 15 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":15},"action":{"type":"expire"}}]}'
echo "ECR repo ready: $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO}"
