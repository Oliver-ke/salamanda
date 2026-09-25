import getpass
import os
import subprocess

from loop_agent.config import Config
from loop_agent.wiring import build_deps, hand_over

from .conftest import REPO_ROOT


def config(**overrides):
    base = dict(repo="o/r", repo_dir=REPO_ROOT, model_id="m", aws_region="us-east-1",
                github_app_id="1", github_installation_id="2", github_private_key="PEM",
                bot_login="loop-sdlc[bot]", git_author_email="1+loop-sdlc[bot]@users.noreply.github.com")
    return Config(**{**base, **overrides})


def test_hand_over_gives_the_tree_to_the_user_then_takes_git_back(tmp_path):
    ran = []

    def runner(argv, **kwargs):
        ran.append(argv)
        assert kwargs.get("check") is True
        return subprocess.CompletedProcess(argv, 0)

    hand_over(tmp_path, "runner", runner=runner)
    assert ran == [
        ["chown", "-R", "runner:runner", str(tmp_path)],
        ["chown", "-R", "root:root", str(tmp_path / ".git")],
        ["chmod", "-R", "go-w", str(tmp_path / ".git")],
    ]


def test_build_deps_warns_when_commands_run_as_the_worker(capsys):
    build_deps(config())
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "LOOP_COMMAND_USER" in err and "uid" in err


def test_build_deps_is_quiet_with_a_command_user_and_hands_new_files_to_them(capsys):
    deps = build_deps(config(command_user=getpass.getuser()))
    assert capsys.readouterr().err == ""
    assert deps.make_toolbox(7).workspace.owner == (os.getuid(), os.getgid())


def test_push_sends_the_credential_through_the_environment_only():
    deps = build_deps(config(command_user=getpass.getuser()))
    auth_env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "k", "GIT_CONFIG_VALUE_0": "v"}
    deps.github.push_auth = lambda: ("https://github.com/o/r.git", auth_env)
    pushed = []
    deps.git.push = lambda branch, url, env=None: pushed.append((branch, url, env))
    deps.push("agent/issue-7-x-aaaaaaa")
    assert pushed == [("agent/issue-7-x-aaaaaaa", "https://github.com/o/r.git", auth_env)]
