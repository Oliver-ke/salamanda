import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict

from .config import Config, ConfigError
from .run import Job, RunResult, run_job
from .server import JobServer
from .wiring import build_deps


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="loop_agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="do one issue now, in the foreground")
    run.add_argument("--issue", type=int, required=True)
    run.add_argument("--sha", help="commit of main to start from (default: current origin/main)")
    serve = sub.add_parser("serve", help="accept jobs over HTTP")
    serve.add_argument("--port", type=int, default=8080)
    return parser.parse_args(argv)


def _origin_main(repo_dir) -> str:
    out = subprocess.run(["git", "ls-remote", "origin", "refs/heads/main"], cwd=repo_dir,
                         check=True, capture_output=True, text=True).stdout
    return out.split()[0]


def _print(job, result) -> None:
    print(json.dumps({"job": asdict(job), "result": asdict(result)}), flush=True)


SECRET_ENV = {"anthropic_api_key": "ANTHROPIC_API_KEY", "github_app_private_key": "GITHUB_APP_PRIVATE_KEY"}


def make_job_handler(env: Mapping[str, str], build=build_deps, run=run_job):
    """Per job: config from the image's environment plus the secrets sent with the
    job. Nothing is built before a job arrives, so nothing lands in the snapshot."""
    def handle(job: Job, secrets: Mapping[str, str]) -> RunResult:
        try:
            config = Config.from_env({**env, **{SECRET_ENV[k]: v for k, v in secrets.items()}})
            deps = build(config)
        except ConfigError as exc:
            return RunResult("error", None, f"configuration: {exc}")
        return run(job, deps)
    return handle


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "serve":
        repo = os.environ.get("LOOP_REPO")
        if not repo:
            print("LOOP_REPO is not set", file=sys.stderr)
            return 2
        JobServer(make_job_handler(os.environ), _print, expected_repo=repo,
                  port=args.port, once=True).serve_forever()
        return 0
    config = Config.from_env()
    deps = build_deps(config)
    job = Job(config.repo, args.issue, args.sha or _origin_main(config.repo_dir))
    result = run_job(job, deps)
    _print(job, result)
    return 0 if result.outcome == "pr_opened" else 1


if __name__ == "__main__":
    raise SystemExit(main())
