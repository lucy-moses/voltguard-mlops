#!/usr/bin/env bash
# One-time: create the private S3 bucket used as the DVC remote.
set -euo pipefail
AWS_REGION="${AWS_REGION:?set AWS_REGION}"; BUCKET="${DVC_S3_BUCKET:?set DVC_S3_BUCKET}"
if [ "$AWS_REGION" = "us-east-1" ]; then aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION"
else aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" --create-bucket-configuration LocationConstraint="$AWS_REGION"; fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
echo "Bucket s3://$BUCKET ready. Next: dvc remote modify storage url s3://$BUCKET/voltguard"
