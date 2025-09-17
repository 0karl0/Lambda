import base64
import json
import logging
import os
from typing import Any, Dict
from urllib.parse import unquote_plus

import boto3

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

SAGEMAKER_ENDPOINT_NAME = os.environ["SAGEMAKER_ENDPOINT_NAME"]
MASK_BUCKET = os.environ["MASK_BUCKET"]
MASK_PREFIX = os.environ.get("MASK_PREFIX", "masks/")
METADATA_SUFFIX = os.environ.get("MASK_METADATA_SUFFIX", ".json")
MASK_SUFFIX = os.environ.get("MASK_IMAGE_SUFFIX", ".png")
THUMBNAIL_MASK_PREFIX = os.environ.get("THUMBNAIL_MASK_PREFIX", "thumbnail-masks/")

sagemaker_runtime = boto3.client(
    "sagemaker-runtime",
    endpoint_url=os.getenv("SAGEMAKER_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
)

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
)


def _decode_image(data: str) -> bytes:
    return base64.b64decode(data.encode("utf-8"))


def _mask_key(prefix: str, original_key: str, suffix: str) -> str:
    sanitized = original_key.replace("..", "")
    return f"{prefix}{sanitized}{suffix}"


def handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    LOGGER.info("Received upload notification: %s", json.dumps(event))

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        LOGGER.info("Invoking SageMaker for s3://%s/%s", bucket, key)

        payload = json.dumps({"bucket": bucket, "key": key})
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType="application/json",
            Body=payload,
        )

        result = json.loads(response["Body"].read().decode("utf-8"))
        LOGGER.debug("SageMaker response: %s", result)

        mask_bytes = _decode_image(result["mask_png"])
        thumbnail_mask_bytes = _decode_image(result["thumbnail_mask_png"])
        thumbnail_size = result.get("thumbnail_size", [512, 512])

        mask_key = _mask_key(MASK_PREFIX, key, MASK_SUFFIX)
        thumbnail_mask_key = _mask_key(THUMBNAIL_MASK_PREFIX, key, MASK_SUFFIX)
        metadata_key = _mask_key(MASK_PREFIX, key, METADATA_SUFFIX)

        s3.put_object(
            Bucket=MASK_BUCKET,
            Key=mask_key,
            Body=mask_bytes,
            ContentType="image/png",
        )
        LOGGER.info("Mask uploaded to s3://%s/%s", MASK_BUCKET, mask_key)

        s3.put_object(
            Bucket=MASK_BUCKET,
            Key=thumbnail_mask_key,
            Body=thumbnail_mask_bytes,
            ContentType="image/png",
        )
        LOGGER.info(
            "Thumbnail mask uploaded to s3://%s/%s", MASK_BUCKET, thumbnail_mask_key
        )

        metadata = {
            "source_bucket": bucket,
            "source_key": key,
            "mask_key": mask_key,
            "thumbnail_mask_key": thumbnail_mask_key,
            "thumbnail_size": thumbnail_size,
        }
        s3.put_object(
            Bucket=MASK_BUCKET,
            Key=metadata_key,
            Body=json.dumps(metadata).encode("utf-8"),
            ContentType="application/json",
        )
        LOGGER.info(
            "Mask metadata stored to s3://%s/%s", MASK_BUCKET, metadata_key
        )

    return {"status": "submitted"}
