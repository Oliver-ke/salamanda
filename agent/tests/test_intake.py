from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loop_agent.aws.intake import IntakeDeps, run_intake
from loop_agent.github import Issue

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
FRESH = (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")


@dataclass
class FakeGitHub:
    by_label: dict = field(default_factory=dict)
    states: dict = field(default_factory=dict)
    prs: list = field(default_factory=list)
    calls: list = field(default_factory=list)

    def list_issues(self, label):
        return list(self.by_label.get(label, []))

    def issue_state(self, n):
        return self.states.get(n)

    def list_open_pull_requests(self):
        return self.prs

    def add_labels(self, n, labels):
        self.calls.append(("add", n, tuple(labels)))

    def remove_label(self, n, label):
        self.calls.append(("remove", n, label))

    def comment(self, n, body):
        self.calls.append(("comment", n, body))

    def branch_sha(self, branch="main"):
        return "c" * 40


def ready(n, body="Depends on: none", extra=()):
    return Issue(n, "t", body, ["agent:ready", *extra], FRESH)


def deps(gh, running=0):
    sent = []
    return IntakeDeps(gh, lambda: running, sent.append, "o/r", lambda: NOW), sent


def test_queues_the_best_eligible_issue_and_swaps_its_label():
    gh = FakeGitHub(by_label={"agent:ready": [ready(8, extra=("priority:low",)), ready(5)]})
    d, sent = deps(gh)
    out = run_intake(d)
    assert out["queued"] == 5
    assert sent == [{"repo": "o/r", "issue": 5, "sha": "c" * 40}]
    assert gh.calls[:2] == [("add", 5, ("agent:queued",)), ("remove", 5, "agent:ready")]


def test_nothing_queued_while_an_execution_runs():
    gh = FakeGitHub(by_label={"agent:ready": [ready(5)]})
    d, sent = deps(gh, running=1)
    assert run_intake(d)["queued"] is None and sent == [] and gh.calls == []


def test_nothing_queued_while_an_issue_is_in_flight():
    gh = FakeGitHub(by_label={"agent:ready": [ready(6)],
                              "agent:running": [Issue(5, "t", "", ["agent:running"], FRESH)]})
    d, sent = deps(gh)
    out = run_intake(d)
    assert out["queued"] is None and out["in_flight"] == [5] and sent == []


def test_stale_queued_claim_is_reclaimed_when_idle():
    gh = FakeGitHub(by_label={"agent:queued": [Issue(5, "t", "", ["agent:queued"], OLD)]})
    d, sent = deps(gh)
    run_intake(d)
    assert ("remove", 5, "agent:queued") in gh.calls and ("add", 5, ("agent:ready",)) in gh.calls
    assert any(c[0] == "comment" and "stale" in c[2] for c in gh.calls)


def test_stale_claim_is_left_alone_while_an_execution_runs():
    gh = FakeGitHub(by_label={"agent:queued": [Issue(5, "t", "", ["agent:queued"], OLD)]})
    d, _ = deps(gh, running=1)
    run_intake(d)
    assert gh.calls == []


def test_stale_running_label_becomes_failed():
    gh = FakeGitHub(by_label={"agent:running": [Issue(5, "t", "", ["agent:running"], OLD)]})
    d, _ = deps(gh)
    run_intake(d)
    assert ("add", 5, ("agent:failed",)) in gh.calls


def test_dependencies_and_pr_claims_feed_selection():
    gh = FakeGitHub(by_label={"agent:ready": [ready(6, "Depends on: #5"), ready(7), ready(3)]},
                    states={5: "open"}, prs=[(4, "Closes #3")])
    d, sent = deps(gh)
    out = run_intake(d)
    assert out["queued"] == 7
    assert "still open" in out["reasons"]["6"] and "claimed" in out["reasons"]["3"]


def test_nothing_eligible_queues_nothing():
    gh = FakeGitHub(by_label={"agent:ready": [ready(6, "Depends on: #5")]}, states={5: "open"})
    d, sent = deps(gh)
    assert run_intake(d)["queued"] is None and sent == []
