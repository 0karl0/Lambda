window.APP_CONFIG = {
  awsRegion: "us-east-1",
  publicBaseUrl: "http://localhost:4566/${OUTPUT_BUCKET}"
  identityPoolId: "us-east-1:example-identity-pool-id",
  uploadBucket: "serverless-ai-upload-bucket",
  outputBucket: "serverless-ai-output-bucket",
  thumbnailPrefix: "thumbnails/",
  processedPrefix: "processed/",
  pollingIntervalMs: 5000
};
