"""Secrets Manager reads and the GitHub client for the Lambdas. AWS wiring only."""

import os

from ..github import GitHubAppClient


def secret(arn: str) -> str:  # pragma: no cover - AWS wiring
    import boto3
    return boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"].strip()


def github_client() -> GitHubAppClient:  # pragma: no cover - AWS wiring
    return GitHubAppClient(os.environ["LOOP_REPO"], os.environ["GITHUB_APP_ID"],
                           secret(os.environ["GITHUB_KEY_SECRET_ARN"]),
                           os.environ["GITHUB_APP_INSTALLATION_ID"])
