# Serverless AI-Powered Image Processing Pipeline

This repository contains a complete reference implementation for a fully serverless background removal workflow on AWS. Users upload images via a static webpage, the upload triggers a serverless pipeline powered by SageMaker, and the resulting background-free image plus thumbnail are written back to an S3 bucket for viewing in the browser.


> **Note:** The included components focus on the orchestration, infrastructure-as-code, and developer experience. You can swap in alternative segmentation models or extend the workflow with additional post-processing steps.

## Architecture Overview

1. **Static Web App (S3 + CloudFront)** — Provides the upload form, progress bar, and dynamic preview of the processed assets using the AWS SDK for JavaScript.
2. **Upload Bucket** — Stores the original images and triggers the first Lambda function.
3. **Trigger Lambda (`TriggerSageMakerFunction`)** — Sends the image location to the SageMaker endpoint and persists the returned masks to the mask bucket.
4. **Mask Bucket** — Holds the generated masks and a metadata JSON object that describes the workflow state.
5. **Apply Lambda (`ApplyMasksFunction`)** — Reacts to new metadata files, applies the masks at full resolution and thumbnail resolution, and writes the results to the public bucket.
6. **Public Bucket** — Serves the background-free PNG and thumbnail for consumption by the frontend.
7. **Amazon SageMaker Endpoint** — Hosts a containerised FastAPI application that loads the pre-trained rembg + Segment Anything models one time during start-up and exposes an `/invocations` endpoint for mask generation.

All components are defined as code so that the same stack can run locally (via Docker Compose + LocalStack) and in AWS (via AWS SAM and SageMaker).

## Repository Layout

| Path | Description |
| --- | --- |
| `frontend/` | Static website assets (HTML/CSS/JS) that interact directly with AWS services from the browser using Cognito credentials. |
| `infra/` | AWS SAM template that declares the buckets, Lambda functions, and permissions. |
| `lambdas/trigger_sagemaker/` | First Lambda that invokes the SageMaker endpoint and persists the masks and metadata. |
| `lambdas/apply_masks/` | Second Lambda that rescales masks, creates the final images, and writes them to the public bucket. |
| `sagemaker/` | Docker assets for the custom SageMaker inference container (FastAPI + rembg + SAM). |
| `local/` | Scripts and documentation for running the whole stack locally using Docker Compose, LocalStack, and the SAM CLI. |
| `docker-compose.yml` | Spins up LocalStack and the SageMaker container for local development. |

## Frontend Configuration

1. Copy `frontend/config.example.js` to `frontend/config.js`.
2. Update the Cognito Identity Pool ID, bucket names, and (optionally) `publicBaseUrl` if you are fronting the output bucket with CloudFront.
3. Host the contents of `frontend/` using Amazon S3 static website hosting, AWS Amplify Hosting, or any static site host.
4. Configure the upload bucket to allow PUT operations from the authenticated Cognito role and grant read access on the output bucket (or use signed URLs / CloudFront signed cookies for finer-grained control).

The site uses the AWS SDK for JavaScript (v2) directly from a CDN and polls the public bucket for the processed results.

## Local Development Workflow

A dedicated [local guide](local/README.md) walks through standing up LocalStack, the SageMaker container, and the Lambda functions using `sam local`. The high-level flow is:

1. `docker compose up --build` to start LocalStack and the SageMaker mock service.
2. `./local/setup-local.sh` to create the three S3 buckets in LocalStack.
3. `sam build` and `sam local start-lambda` to run both Lambda functions inside Docker.
4. `python local/wire_local_events.py` to connect S3 events to the locally running Lambdas.
5. Upload a file to the upload bucket (via CLI or the frontend) and watch the pipeline finish end-to-end.

## Deploying to AWS

### 1. Prerequisites

- AWS CLI with administrator access to the target account.
- AWS SAM CLI installed locally.
- Docker (required for building dependencies and the SageMaker container image).
- An S3 bucket to host Lambda deployment artifacts (e.g. `serverless-ai-sam-artifacts`).

### 2. Build and Package Lambda Functions

```bash
sam build --use-container
sam package \
  --output-template-file packaged.yaml \
  --s3-bucket serverless-ai-sam-artifacts
```

### 3. Deploy the Infrastructure Stack

```bash
sam deploy \
  --template-file packaged.yaml \
  --stack-name serverless-ai-pipeline \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      UploadBucketName=serverless-ai-upload \
      MaskBucketName=serverless-ai-masks \
      OutputBucketName=serverless-ai-output \
      SageMakerEndpointName=serverless-ai-endpoint
```

The deployment creates three S3 buckets, two Lambda functions, IAM roles, and configures the bucket notifications. After the stack completes, note the function ARNs from the outputs—they are required when granting S3 invoke permissions if you customise the bucket names.

### 4. Build and Push the SageMaker Inference Image

1. Authenticate Docker to Amazon ECR and create a repository (one-time):

   ```bash
   aws ecr create-repository --repository-name serverless-ai-rembg
   aws ecr get-login-password | docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.<region>.amazonaws.com
   ```

2. Build and push the image:

   ```bash
   docker build -t serverless-ai-rembg:latest sagemaker/
   docker tag serverless-ai-rembg:latest <aws_account_id>.dkr.ecr.<region>.amazonaws.com/serverless-ai-rembg:latest
   docker push <aws_account_id>.dkr.ecr.<region>.amazonaws.com/serverless-ai-rembg:latest
   ```

### 5. Provision the SageMaker Endpoint

1. **Upload model weights**: Store the required SAM and rembg weights in `s3://serverless-ai-models/` (or any bucket). The container loads these assets on start-up using the `MODEL_ARTIFACT_BUCKET` and `MODEL_ARTIFACT_PREFIX` environment variables.
2. **Create a SageMaker model** referencing the ECR image and pointing to the weight bucket via the `Environment` property.
3. **Create an endpoint configuration** with an appropriate instance type (e.g. `ml.g5.2xlarge` for GPU acceleration when using SAM + rembg) and attach the model.
4. **Deploy the endpoint** using `aws sagemaker create-endpoint`.

The FastAPI app inside the container loads the models once at boot and keeps them in memory to minimise invocation latency.

### 6. Grant the Lambda Role Access to SageMaker

The SAM template already grants `sagemaker:InvokeEndpoint` to the first Lambda. If you change the endpoint name post-deployment, update the role policy accordingly.

### 7. Expose the Frontend

- Upload `frontend/` to an S3 bucket configured for static hosting or to AWS Amplify.
- Update the JS config with the production Cognito Identity Pool ID and bucket names.
- (Optional) Front the public bucket with CloudFront for TLS and custom domains.

## Extending the Pipeline

- **Additional outputs** — e.g. depth maps, matte previews, or composite backgrounds.
- **Notification hooks** — integrate Amazon EventBridge or SNS to notify users when processing completes.
- **Security** — restrict object access with signed URLs, leverage Amazon Cognito groups for quotas.
- **Observability** — connect Lambda logs to CloudWatch dashboards, add metrics for processing time, mask accuracy, etc.

## Cleaning Up

To remove all deployed resources:

1. Delete the SageMaker endpoint, endpoint configuration, and model.
2. Run `sam delete --stack-name serverless-ai-pipeline` to tear down the Lambda functions and buckets.
3. Delete the ECR repository and any S3 buckets storing artifacts or outputs.

## Additional Documentation

- [Local testing guide](local/README.md)
- [SageMaker container Dockerfile](sagemaker/Dockerfile)
- [AWS SAM template](infra/template.yaml)

## License

This project is provided as-is for educational purposes.
