import pwd
import subprocess
import sys
from pathlib import Path

from .agent import StrandsAgentRunner
from .checks import ensure_dependencies, run_pr_check
from .commands import run_allowed
from .config import Config
from .github import GitHubAppClient
from .gitops import Git
from .prompts import system_prompt
from .protected import load_protected_paths
from .run import Deps
from .sandbox import Workspace
from .toolbox import Budget, Toolbox

PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompt.md"


def hand_over(repo_dir: Path, user: str, runner=subprocess.run) -> None:
    """Give the working tree to the command user, but keep .git the worker's:
    the worker runs git as root, so a runner-writable .git (hooks, config) would
    be code execution as root."""
    git_dir = repo_dir / ".git"
    runner(["chown", "-R", f"{user}:{user}", str(repo_dir)], check=True)
    runner(["chown", "-R", "root:root", str(git_dir)], check=True)
    runner(["chmod", "-R", "go-w", str(git_dir)], check=True)


def build_deps(config: Config) -> Deps:
    repo_dir = config.repo_dir
    owner = None
    if config.command_user:
        entry = pwd.getpwnam(config.command_user)
        owner = (entry.pw_uid, entry.pw_gid)
    else:
        print("warning: LOOP_COMMAND_USER is not set; agent-run commands run with the "
              "worker's own uid", file=sys.stderr)
    github = GitHubAppClient(config.repo, config.github_app_id, config.github_private_key,
                             config.github_installation_id)
    git = Git(repo_dir, author_name=config.bot_login, author_email=config.git_author_email)

    def run_command(cmd: str):
        return run_allowed(cmd, repo_dir, command_user=config.command_user)

    def ensure_deps() -> None:
        if config.command_user:
            # The worker (root) just reset the checkout; hand it to the command user.
            hand_over(repo_dir, config.command_user)
        ensure_dependencies(repo_dir, config.snapshot_lock_file, config.command_user)

    def make_toolbox(issue: int) -> Toolbox:
        workspace = Workspace(repo_dir, load_protected_paths(repo_dir), owner=owner)
        return Toolbox(workspace, Budget(config.max_tool_calls), github, issue, run_command)

    class LazyRunner:
        """Reads CLAUDE.md after prepare(), so the system prompt matches the job's commit."""

        def session(self, toolbox):
            return StrandsAgentRunner(config.model_id, config.aws_region,
                                      system_prompt(repo_dir, PROMPT_FILE)).session(toolbox)

    return Deps(
        github=github, git=git,
        push=lambda branch: git.push(branch, *github.push_auth()),
        ensure_deps=ensure_deps, make_toolbox=make_toolbox, agent=LazyRunner(),
        verify=lambda: run_command("npm run verify"),
        pr_check=lambda base, body: run_pr_check(repo_dir, base, config.bot_login, body),
        max_verify_retries=config.max_verify_retries,
    )
