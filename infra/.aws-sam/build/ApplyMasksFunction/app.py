import io
import json
import logging
import os
from typing import Any, Dict
from urllib.parse import unquote_plus

import boto3
import numpy as np
from PIL import Image

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed/")
THUMBNAIL_PREFIX = os.environ.get("THUMBNAIL_PREFIX", "thumbnails/")
MASK_METADATA_SUFFIX = os.environ.get("MASK_METADATA_SUFFIX", ".json")

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
)


def _load_image_from_s3(bucket: str, key: str) -> Image.Image:
    LOGGER.info("Downloading s3://%s/%s", bucket, key)
    response = s3.get_object(Bucket=bucket, Key=key)
    return Image.open(io.BytesIO(response["Body"].read()))


def _apply_mask(image: Image.Image, mask: Image.Image) -> Image.Image:
    image_rgba = image.convert("RGBA")
    mask_resized = mask.resize(image_rgba.size, Image.BILINEAR).convert("L")

    alpha = np.array(mask_resized).astype(np.float32) / 255.0
    image_array = np.array(image_rgba)
    image_array[..., 3] = (image_array[..., 3] * alpha).astype("uint8")

    return Image.fromarray(image_array, mode="RGBA")


def _save_png(image: Image.Image, bucket: str, key: str) -> None:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue(), ContentType="image/png")
    LOGGER.info("Saved processed image to s3://%s/%s", bucket, key)


def handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    LOGGER.info("Received mask notification: %s", json.dumps(event))

    for record in event.get("Records", []):
        mask_bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if not key.endswith(MASK_METADATA_SUFFIX):
            LOGGER.debug("Skipping non-metadata object %s", key)
            continue

        metadata_body = s3.get_object(Bucket=mask_bucket, Key=key)["Body"].read()
        metadata = json.loads(metadata_body.decode("utf-8"))
        LOGGER.info("Processing metadata %s", metadata)

        source_bucket = metadata["source_bucket"]
        source_key = metadata["source_key"]
        mask_key = metadata["mask_key"]
        thumbnail_mask_key = metadata["thumbnail_mask_key"]
        thumbnail_size = tuple(metadata.get("thumbnail_size", [512, 512]))

        original_image = _load_image_from_s3(source_bucket, source_key)
        mask_image = _load_image_from_s3(mask_bucket, mask_key)
        thumbnail_mask_image = _load_image_from_s3(mask_bucket, thumbnail_mask_key)

        processed = _apply_mask(original_image, mask_image)
        processed_key = f"{PROCESSED_PREFIX}{source_key}"
        _save_png(processed, OUTPUT_BUCKET, processed_key)

        thumbnail = original_image.copy()
        thumbnail.thumbnail(thumbnail_size, Image.LANCZOS)
        processed_thumbnail = _apply_mask(thumbnail, thumbnail_mask_image)
        thumbnail_key = f"{THUMBNAIL_PREFIX}{source_key}"
        _save_png(processed_thumbnail, OUTPUT_BUCKET, thumbnail_key)

    return {"status": "completed"}
