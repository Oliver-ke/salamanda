"""Build or rebuild the worker's Lambda MicroVM image. Run by a human.

Terraform's aws_lambdamicrovms_image cannot set the /ready hook the worker needs,
so the image lives outside Terraform; the bucket and build role it uses come from
Terraform outputs. Secrets never go into an image: its snapshot is readable by
anyone who can run it, so the env file may only hold non-secret settings."""

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXCLUDE_PARTS = {".venv", "__pycache__", ".pytest_cache", "node_modules"}
FORBIDDEN_PREFIXES = ("ANTHROPIC_API_KEY", "GITHUB_APP_PRIVATE_KEY", "AWS_")
READY_HOOK = {"port": 8080, "microvmImageHooks": {"ready": "ENABLED", "readyTimeoutInSeconds": 600}}
BASE_IMAGE = "arn:aws:lambda:{region}:aws:microvm-image:al2023-1"


def make_artifact(repo_root: Path = REPO_ROOT) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(repo_root / "agent" / "Dockerfile", "Dockerfile")
        for path in sorted((repo_root / "agent").rglob("*")):
            rel = path.relative_to(repo_root)
            if path.is_file() and not EXCLUDE_PARTS & set(rel.parts):
                z.write(path, rel.as_posix())
    return buf.getvalue()


def read_image_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.startswith(FORBIDDEN_PREFIXES):
            raise SystemExit(f"{key} may not go into a MicroVM image (secrets travel with each job; "
                             "AWS_REGION is reserved)")
        env[key] = value
    return env


def image_request(name: str, artifact_uri: str, build_role_arn: str, base_image_arn: str,
                  env: dict[str, str]) -> dict:
    return {
        "name": name,
        "codeArtifact": {"uri": artifact_uri},
        "baseImageArn": base_image_arn,
        "buildRoleArn": build_role_arn,
        "cpuConfigurations": [{"architecture": "ARM_64"}],
        "resources": [{"minimumMemoryInMiB": 2048}],
        "environmentVariables": env,
        "hooks": READY_HOOK,
        "tags": {"project": "salamanda"},
    }


def accepted(client, operation: str, request: dict) -> dict:
    members = client.meta.service_model.operation_model(operation).input_shape.members
    return {k: v for k, v in request.items() if k in members}


def main(argv=None) -> int:  # pragma: no cover - AWS wiring
    import boto3

    p = argparse.ArgumentParser(prog="build_image")
    p.add_argument("--bucket", required=True)
    p.add_argument("--build-role-arn", required=True)
    p.add_argument("--env-file", required=True, type=Path)
    p.add_argument("--name", default="salamanda-worker")
    p.add_argument("--region", default="eu-west-1")
    p.add_argument("--profile", default=None)
    args = p.parse_args(argv)

    session = boto3.session.Session(profile_name=args.profile, region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    image_arn = f"arn:aws:lambda:{args.region}:{account}:microvm-image:{args.name}"
    key = f"worker/{int(time.time())}.zip"
    session.client("s3").put_object(Bucket=args.bucket, Key=key, Body=make_artifact())
    request = image_request(args.name, f"s3://{args.bucket}/{key}", args.build_role_arn,
                            BASE_IMAGE.format(region=args.region), read_image_env(args.env_file))
    mvm = session.client("lambda-microvms")
    try:
        mvm.get_microvm_image(imageIdentifier=image_arn)
        mvm.update_microvm_image(**accepted(mvm, "UpdateMicrovmImage", {**request, "imageIdentifier": image_arn}))
    except mvm.exceptions.ResourceNotFoundException:
        mvm.create_microvm_image(**accepted(mvm, "CreateMicrovmImage", request))
    start = time.monotonic()
    while True:
        image = mvm.get_microvm_image(imageIdentifier=image_arn)
        print(f"[{time.monotonic() - start:5.0f}s] {image['state']}", flush=True)
        if image["state"] in ("CREATED", "UPDATED"):
            print(image_arn)
            return 0
        if image["state"].endswith("FAILED"):
            versions = mvm.list_microvm_image_versions(imageIdentifier=image_arn).get("items", [])
            reasons = [v.get("stateReason") for v in versions if v.get("state") == "FAILED"]
            print(f"build failed: {reasons[-1:] or image.get('stateReason')} — see CloudWatch "
                  f"/aws/lambda-microvms/{args.name}", file=sys.stderr)
            return 1
        time.sleep(15)


if __name__ == "__main__":
    raise SystemExit(main())
