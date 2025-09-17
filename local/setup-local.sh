#!/usr/bin/env bash
set -euo pipefail

UPLOAD_BUCKET=${UPLOAD_BUCKET:-serverless-ai-upload-local}
MASK_BUCKET=${MASK_BUCKET:-serverless-ai-masks-local}
OUTPUT_BUCKET=${OUTPUT_BUCKET:-serverless-ai-output-local}

if ! command -v awslocal >/dev/null 2>&1; then
  echo "awslocal CLI is required. Install with 'pip install awscli-local'." >&2
  exit 1
fi

echo "Creating buckets in LocalStack..."
awslocal s3 mb "s3://$UPLOAD_BUCKET" || true
awslocal s3 mb "s3://$MASK_BUCKET" || true
awslocal s3 mb "s3://$OUTPUT_BUCKET" || true

# Enable public read for the output bucket when running locally.
awslocal s3api put-bucket-acl \
  --bucket "$OUTPUT_BUCKET" \
  --acl public-read

echo "Buckets ready:"
awslocal s3 ls
