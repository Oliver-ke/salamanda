import argparse
import json
import subprocess
import sys
from dataclasses import asdict

from .config import Config
from .run import Job, run_job
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


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = Config.from_env()
    deps = build_deps(config)
    if args.command == "run":
        job = Job(config.repo, args.issue, args.sha or _origin_main(config.repo_dir))
        result = run_job(job, deps)
        _print(job, result)
        return 0 if result.outcome == "pr_opened" else 1
    JobServer(lambda job: run_job(job, deps), _print, expected_repo=config.repo,
              port=args.port, once=True).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
