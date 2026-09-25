from dataclasses import dataclass, field

from loop_agent.commands import CommandResult


@dataclass
class FakeGitHub:
    issues: dict = field(default_factory=dict)
    created: list = field(default_factory=list)
    comments: list = field(default_factory=list)
    prs: list = field(default_factory=list)
    fail_comment: bool = False

    def get_issue(self, number):
        return self.issues[number]

    def create_issue(self, title, body, labels):
        number = 100 + len(self.created)
        self.created.append({"number": number, "title": title, "body": body, "labels": labels})
        return number

    def comment(self, number, body):
        if self.fail_comment:
            raise RuntimeError("comment failed")
        self.comments.append((number, body))

    def open_pull_request(self, head, base, title, body):
        from loop_agent.github import PullRequest
        self.prs.append({"head": head, "base": base, "title": title, "body": body})
        return PullRequest(number=50, url="https://github.com/o/r/pull/50")


def ok(cmd="npm run verify", output="all green"):
    return CommandResult(cmd, 0, output)


def failed(cmd="npm run verify", output="1 test failed"):
    return CommandResult(cmd, 1, output)
