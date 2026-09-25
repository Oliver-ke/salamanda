import json
import os
import subprocess

import pytest

from loop_agent.commands import CommandResult
from loop_agent.github import Issue
from loop_agent.prompts import fix_prompt, pr_body, slugify, system_prompt, task_prompt

from .conftest import REPO_ROOT

ISSUE = Issue(7, "Add expense form", "A form with amount and category.", ["agent:ready"])


def test_slugify():
    assert slugify("Add expense form") == "add-expense-form"
    assert slugify("Fix: crash on £ amounts!!") == "fix-crash-on-amounts"
    assert slugify("日本語") == "issue"
    assert len(slugify("word " * 40)) <= 40 and not slugify("word " * 40).endswith("-")


def test_task_prompt_carries_the_issue():
    text = task_prompt(ISSUE)
    assert "#7" in text and "Add expense form" in text and "amount and category" in text
    assert "finish" in text and "give_up" in text


def test_fix_prompt_carries_the_failure_output():
    assert "1 test failed" in fix_prompt(CommandResult("npm run verify", 1, "1 test failed"))


def test_pr_body_closes_exactly_this_issue():
    body = pr_body(ISSUE, "Added the form; verify passes")
    assert body.startswith("Closes #7\n")
    assert "Added the form; verify passes" in body


def test_system_prompt_includes_prompt_and_rules(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Rules for every run\nBe good.")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("You are the loop agent.")
    text = system_prompt(tmp_path, prompt_file)
    assert text.startswith("You are the loop agent.") and "Be good." in text


def _closed_issues(body):
    """The harness's own parser, so this test fails if the two ever drift apart."""
    script = ("import { closedIssuesFrom } from './harness/src/pr-claim.mjs';"
              "process.stdout.write(JSON.stringify(closedIssuesFrom(process.env.BODY)));")
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO_ROOT,
                         env={"PATH": os.environ["PATH"], "BODY": body},
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_pr_body_neutralises_closing_keywords_in_the_summary():
    body = pr_body(ISSUE, "Fixes #9")
    assert "Fixes #9" not in body and body.startswith("Closes #7\n")
    assert _closed_issues(body) == [7]


@pytest.mark.parametrize("summary", [
    "Fixes #9", "closes: #9 and resolves #10", "fixes o/r#9", "Resolved\nhttps://github.com/o/r/issues/9",
    "\u00e9fixes #9", "FIXED #9", "fixes\u00a0#9", "fixes\ufeff#9", "fixes\u2028#9",
])
def test_pr_body_closes_only_this_issue_whatever_the_summary_says(summary):
    assert _closed_issues(pr_body(ISSUE, summary)) == [7]
