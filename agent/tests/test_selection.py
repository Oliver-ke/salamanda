import pytest

from loop_agent.aws.selection import closed_issues, depends_on, priority, select_issue
from loop_agent.github import Issue


def issue(n, body="Depends on: none", labels=("agent:ready",)):
    return Issue(n, f"issue {n}", body, list(labels))


@pytest.mark.parametrize("body,expected", [
    ("Depends on: none\n\nText", []),
    ("Depends on: #6, #7\n", [6, 7]),
    ("Intro\ndepends on:   #7 #6 #7", [6, 7]),
    ("Depends on:\n", []),
    ("Depends on: soon", []),
    ("no line at all", []),
])
def test_depends_on_parsing(body, expected):
    assert depends_on(body) == expected


def test_closed_issues_reads_every_closing_form():
    body = "Closes #3. Fixes o/r#4 and resolves https://github.com/o/r/issues/5; see #6"
    assert closed_issues(body) == {3, 4, 5}


def test_picks_the_single_eligible_issue():
    assert select_issue([issue(5)], {}, set()).issue.number == 5


def test_unapproved_and_in_flight_issues_are_skipped_with_reasons():
    sel = select_issue([issue(1, labels=()), issue(2, labels=("agent:ready", "agent:queued")),
                        issue(3, labels=("agent:ready", "agent:failed"))], {}, set())
    assert sel.issue is None
    assert "not approved" in sel.reasons[1]
    assert "agent:queued" in sel.reasons[2] and "agent:failed" in sel.reasons[3]


def test_dependency_must_be_closed():
    sel = select_issue([issue(6, "Depends on: #5")], {5: "open"}, set())
    assert sel.issue is None and sel.reasons[6] == "dependency #5 is still open"
    assert select_issue([issue(6, "Depends on: #5")], {5: "closed"}, set()).issue.number == 6


def test_unknown_dependency_is_blocked():
    sel = select_issue([issue(6, "Depends on: #99")], {99: None}, set())
    assert sel.issue is None and sel.reasons[6] == "depends on unknown issue #99"


def test_self_dependency_is_blocked():
    sel = select_issue([issue(6, "Depends on: #6")], {6: "open"}, set())
    assert sel.issue is None and sel.reasons[6] == "depends on itself"


def test_claimed_by_an_open_pull_request():
    sel = select_issue([issue(3)], {}, {3})
    assert sel.issue is None and sel.reasons[3] == "claimed by an open pull request"


def test_priority_then_lowest_number():
    low = issue(1, labels=("agent:ready", "priority:low"))
    medium_a, medium_b = issue(4), issue(3)
    high = issue(9, labels=("agent:ready", "priority:high"))
    assert [priority(i) for i in (high, medium_a, low)] == [0, 1, 2]
    assert select_issue([low, medium_a, medium_b, high], {}, set()).issue.number == 9
    assert select_issue([low, medium_a, medium_b], {}, set()).issue.number == 3
