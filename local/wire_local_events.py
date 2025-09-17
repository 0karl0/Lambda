#!/usr/bin/env python3
"""Wire S3 bucket notifications to locally running Lambda functions."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict

import boto3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload-bucket", required=True)
    parser.add_argument("--mask-bucket", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--endpoint-url",
        default="http://localhost:4566",
        help="Endpoint for LocalStack APIs.",
    )
    parser.add_argument(
        "--lambda-endpoint",
        default="http://127.0.0.1:3001",
        help="Endpoint for sam local start-lambda.",
    )
    parser.add_argument(
        "--metadata-suffix",
        default=".json",
        help="Suffix used for mask metadata objects.",
    )
    return parser.parse_args()


def ensure_permission(
    lambda_client, function_name: str, bucket_arn: str
) -> None:
    statement_id = f"AllowExecutionFrom{function_name}"
    try:
        lambda_client.add_permission(
            FunctionName=function_name,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=bucket_arn,
        )
    except Exception:  # pylint: disable=broad-except
        pass


def configure_notifications(
    s3_client,
    bucket: str,
    lambda_arn: str,
    events,
    suffix: str | None = None,
) -> None:
    notification: Dict[str, object] = {
        "LambdaFunctionConfigurations": [
            {
                "LambdaFunctionArn": lambda_arn,
                "Events": events,
            }
        ]
    }
    if suffix:
        notification["LambdaFunctionConfigurations"][0]["Filter"] = {
            "Key": {
                "FilterRules": [
                    {
                        "Name": "suffix",
                        "Value": suffix,
                    }
                ]
            }
        }

    s3_client.put_bucket_notification_configuration(
        Bucket=bucket,
        NotificationConfiguration=notification,
    )


def main() -> int:
    args = parse_args()
    session = boto3.session.Session(region_name=args.region)
    s3_client = session.client("s3", endpoint_url=args.endpoint_url)
    lambda_client = session.client(
        "lambda", endpoint_url=args.lambda_endpoint, region_name=args.region
    )

    account_id = "000000000000"
    trigger_arn = f"arn:aws:lambda:{args.region}:{account_id}:function:TriggerSageMakerFunction"
    apply_arn = f"arn:aws:lambda:{args.region}:{account_id}:function:ApplyMasksFunction"

    ensure_permission(
        lambda_client,
        "TriggerSageMakerFunction",
        f"arn:aws:s3:::{args.upload_bucket}",
    )
    ensure_permission(
        lambda_client,
        "ApplyMasksFunction",
        f"arn:aws:s3:::{args.mask_bucket}",
    )

    configure_notifications(
        s3_client,
        args.upload_bucket,
        trigger_arn,
        ["s3:ObjectCreated:*"],
    )
    configure_notifications(
        s3_client,
        args.mask_bucket,
        apply_arn,
        ["s3:ObjectCreated:*"],
        suffix=args.metadata_suffix,
    )

    print("Bucket notifications configured:")
    print(
        json.dumps(
            {
                "upload_bucket": args.upload_bucket,
                "mask_bucket": args.mask_bucket,
                "functions": [
                    "TriggerSageMakerFunction",
                    "ApplyMasksFunction",
                ],
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
