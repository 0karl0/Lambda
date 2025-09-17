import base64
import io
import logging
import os
from dataclasses import dataclass
from typing import Tuple

import boto3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from rembg import remove
from PIL import Image

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

app = FastAPI(title="Serverless Image Mask Generator")


@dataclass
class ModelArtifacts:
    bucket: str
    prefix: str

    def download_all(self, destination: str) -> None:
        if not self.bucket:
            LOGGER.info("No external model artifacts configured")
            return

        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        paginator = s3.get_paginator("list_objects_v2")
        os.makedirs(destination, exist_ok=True)
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                target = os.path.join(destination, os.path.basename(key))
                LOGGER.info("Downloading model artifact %s to %s", key, target)
                s3.download_file(self.bucket, key, target)


class InvocationRequest(BaseModel):
    bucket: str
    key: str


class ImageMasker:
    def __init__(self) -> None:
        artifacts = ModelArtifacts(
            bucket=os.getenv("MODEL_ARTIFACT_BUCKET", ""),
            prefix=os.getenv("MODEL_ARTIFACT_PREFIX", ""),
        )
        artifacts.download_all(os.getenv("MODEL_ARTIFACT_PATH", "/opt/ml/model"))

    @staticmethod
    def _image_from_s3(bucket: str, key: str) -> Image.Image:
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        file_stream = io.BytesIO()
        s3.download_fileobj(bucket, key, file_stream)
        file_stream.seek(0)
        return Image.open(file_stream)

    def _run_background_removal(self, image: Image.Image) -> Image.Image:
        # rembg internally runs a U^2-Net or SAM-based pipeline depending on configuration.
        return remove(image)

    def _extract_mask(self, processed: Image.Image) -> Image.Image:
        if processed.mode != "RGBA":
            processed = processed.convert("RGBA")
        _, _, _, alpha = processed.split()
        return alpha

    def generate_masks(self, bucket: str, key: str) -> Tuple[Image.Image, Image.Image, Tuple[int, int]]:
        image = self._image_from_s3(bucket, key)
        processed = self._run_background_removal(image)
        mask = self._extract_mask(processed)

        thumbnail_size = tuple(
            int(x) for x in os.getenv("THUMBNAIL_SIZE", "512,512").split(",")
        )
        thumbnail = image.copy()
        thumbnail.thumbnail(thumbnail_size, Image.LANCZOS)
        thumbnail_processed = self._run_background_removal(thumbnail)
        thumbnail_mask = self._extract_mask(thumbnail_processed)

        return mask, thumbnail_mask, thumbnail.size

    @staticmethod
    def to_base64_png(image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


masker = ImageMasker()


@app.get("/ping")
def ping() -> dict:
    return {"status": "ok"}


@app.post("/invocations")
def invoke(request: InvocationRequest) -> dict:
    try:
        mask, thumbnail_mask, thumbnail_size = masker.generate_masks(
            request.bucket, request.key
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to generate mask for %s", request)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "mask_png": ImageMasker.to_base64_png(mask),
        "thumbnail_mask_png": ImageMasker.to_base64_png(thumbnail_mask),
        "thumbnail_size": list(thumbnail_size),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
