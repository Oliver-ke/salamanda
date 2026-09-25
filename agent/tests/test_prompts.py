from loop_agent.commands import CommandResult
from loop_agent.github import Issue
from loop_agent.prompts import fix_prompt, pr_body, slugify, system_prompt, task_prompt

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
