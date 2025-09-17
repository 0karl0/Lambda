# Local Testing Guide

This directory contains helper assets for running the Serverless AI-Powered Image Processing Pipeline on your workstation. The stack relies on [LocalStack](https://github.com/localstack/localstack) for S3-compatible storage and a Dockerized FastAPI application that emulates the SageMaker endpoint.

## Prerequisites

- Docker Engine 20+
- Docker Compose v2
- AWS SAM CLI 1.99+
- Python 3.11 with `pip`
- [`awscli-local`](https://github.com/localstack/awscli-local) (`pip install awscli-local`)
- Node.js 18+ (for running static site tooling such as `serve` if desired)

## Services

- **LocalStack** — exposes an S3-compatible API at `http://localhost:4566`
- **Mask Generator (SageMaker mock)** — the container defined in `../sagemaker` listening on port `8080`

## Quickstart

1. **Start the core services**

   ```bash
   docker compose up --build
   ```

   Wait until both the `localstack` and `sagemaker` containers report as healthy.

2. **Provision buckets**

   ```bash
   export UPLOAD_BUCKET=serverless-ai-upload-local
   export MASK_BUCKET=serverless-ai-masks-local
   export OUTPUT_BUCKET=serverless-ai-output-local
   ./setup-local.sh
   ```

3. **Package Lambda dependencies**

   ```bash
   cd ..
   sam build --use-container
   ```

4. **Launch the Lambdas locally**

   In one terminal run:

   ```bash
   sam local start-lambda --docker-network lambda_default --env-vars local/sam-env.json
   ```

   `lambda_default` is the network created by Docker Compose; adjust if you renamed the project.

5. **Create S3 event source mappings**

   Because LocalStack does not automatically wire bucket notifications for `sam local`, invoke the bootstrap helper:

   ```bash
   python local/wire_local_events.py \
     --upload-bucket "$UPLOAD_BUCKET" \
     --mask-bucket "$MASK_BUCKET"
   ```

   This script subscribes the two Lambda functions to the relevant S3 events through the AWS CLI.

6. **Upload an image**

   ```bash
   awslocal s3 cp sample.jpg "s3://$UPLOAD_BUCKET/sample.jpg"
   ```

   Watch the Lambda logs in the `sam local start-lambda` terminal. The final image will appear in `s3://$OUTPUT_BUCKET/processed/sample.jpg` and `s3://$OUTPUT_BUCKET/thumbnails/sample.jpg` when the pipeline completes.

7. **Run the frontend against LocalStack**

   - Copy `frontend/config.example.js` to `frontend/config.js` and update the bucket names plus `publicBaseUrl` to `http://localhost:4566/${OUTPUT_BUCKET}`.
   - Serve the `frontend/` directory via any static file server (e.g. `npx serve frontend`).
   - Upload an image using the webpage and confirm that the processed results render once available.

## Resetting the Environment

Stop the containers with `docker compose down` and remove generated volumes as needed:

```bash
docker compose down -v
rm -rf local/localstack
```

## Troubleshooting

- **Lambda cannot reach LocalStack S3** — ensure the `AWS_REGION` and `S3_ENDPOINT_URL` environment variables are set when invoking `sam local`.
- **SageMaker container fails to download models** — for local testing you can skip hosting large weights by leaving `MODEL_ARTIFACT_BUCKET` empty. For production, upload the weights to S3 and set the bucket/prefix via environment variables (see `docker-compose.yml`).
- **Large model downloads** — pre-download and mount the models into the container to avoid multi-gigabyte downloads on each start (see the README for the deployment strategy).
