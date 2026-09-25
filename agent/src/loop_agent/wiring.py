import subprocess
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


def build_deps(config: Config) -> Deps:
    repo_dir = config.repo_dir
    github = GitHubAppClient(config.repo, config.github_app_id, config.github_private_key,
                             config.github_installation_id)
    git = Git(repo_dir, author_name=config.bot_login, author_email=config.git_author_email)

    def run_command(cmd: str):
        return run_allowed(cmd, repo_dir, command_user=config.command_user)

    def ensure_deps() -> None:
        if config.command_user:
            # The worker (root) just reset the checkout; hand it to the command user.
            subprocess.run(["chown", "-R", f"{config.command_user}:{config.command_user}",
                            str(repo_dir)], check=True)
        ensure_dependencies(repo_dir, config.snapshot_lock_file, config.command_user)

    def make_toolbox(issue: int) -> Toolbox:
        workspace = Workspace(repo_dir, load_protected_paths(repo_dir))
        return Toolbox(workspace, Budget(config.max_tool_calls), github, issue, run_command)

    class LazyRunner:
        """Reads CLAUDE.md after prepare(), so the system prompt matches the job's commit."""

        def session(self, toolbox):
            return StrandsAgentRunner(config.model_id, config.aws_region,
                                      system_prompt(repo_dir, PROMPT_FILE)).session(toolbox)

    return Deps(
        github=github, git=git,
        push=lambda branch: git.push(branch, github.push_url()),
        ensure_deps=ensure_deps, make_toolbox=make_toolbox, agent=LazyRunner(),
        verify=lambda: run_command("npm run verify"),
        pr_check=lambda base, body: run_pr_check(repo_dir, base, config.bot_login, body),
        max_verify_retries=config.max_verify_retries,
    )
