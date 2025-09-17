#!/usr/bin/env python3
"""Wire S3 bucket notifications to locally running Lambda functions."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Dict

import boto3
from botocore.exceptions import BotoCoreError, ClientError


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
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=30.0,
        help=(
            "Seconds to wait for 'sam local start-lambda' to expose functions before "
            "giving up."
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds to wait between attempts when checking for Lambda availability.",
    )
    parser.add_argument(
        "--trigger-function-name",
        default="TriggerSageMakerFunction",
        help="Logical ID of the Lambda that starts the SageMaker workflow.",
    )
    parser.add_argument(
        "--apply-function-name",
        default="ApplyMasksFunction",
        help="Logical ID of the Lambda that processes generated masks.",
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


def resolve_function_arn(
    lambda_client,
    function_name: str,
    *,
    wait_timeout: float,
    poll_interval: float,
) -> str:
    """Return the deployed ARN for the given Lambda function.

    The SAM CLI may take a moment to expose Lambda metadata when
    ``sam local start-lambda`` is booting. To provide a smoother developer
    experience we poll the endpoint until the function appears or a timeout
    is reached.
    """

    deadline = time.monotonic() + wait_timeout
    last_error: Exception | None = None

    while True:
        try:
            response = lambda_client.get_function(FunctionName=function_name)
        except (BotoCoreError, ClientError) as exc:
            last_error = exc
        else:
            configuration = response.get("Configuration") or {}
            function_arn = configuration.get("FunctionArn")
            if function_arn:
                return function_arn
            last_error = RuntimeError(
                f"Lambda get_function response missing ARN for {function_name}: {response}"
            )

        if time.monotonic() >= deadline:
            break

        time.sleep(max(poll_interval, 0.1))

    error_message = (
        f"Unable to look up function ARN for {function_name}. "
        "Ensure 'sam local start-lambda' is running and reachable. "
        "If it runs inside Docker, pass an appropriate --lambda-endpoint (e.g. "
        "http://host.docker.internal:3001)."
    )

    if last_error:
        raise RuntimeError(error_message) from last_error

    raise RuntimeError(error_message)


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

    ensure_permission(
        lambda_client,
        args.trigger_function_name,
        f"arn:aws:s3:::{args.upload_bucket}",
    )
    trigger_arn = resolve_function_arn(
        lambda_client,
        args.trigger_function_name,
        wait_timeout=args.wait_timeout,
        poll_interval=args.poll_interval,
    )
    ensure_permission(
        lambda_client,
        args.apply_function_name,
        f"arn:aws:s3:::{args.mask_bucket}",
    )
    apply_arn = resolve_function_arn(
        lambda_client,
        args.apply_function_name,
        wait_timeout=args.wait_timeout,
        poll_interval=args.poll_interval,
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
                "functions": {
                    args.trigger_function_name: trigger_arn,
                    args.apply_function_name: apply_arn,
                },
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
