import json
from pathlib import Path

from loop_agent.aws.run_task import MAX_POLLS

ASL = Path(__file__).resolve().parents[1] / "src/loop_agent/aws/state_machine.asl.json"


def machine():
    text = ASL.read_text()
    for name in ("start", "dispatch", "poll", "finish"):
        text = text.replace("${%s_arn}" % name, f"arn:aws:lambda:eu-west-1:1:function:{name}")
    return json.loads(text)


def test_every_task_state_catches_into_finish():
    states = machine()["States"]
    for name, state in states.items():
        if state["Type"] == "Task" and name != "Finish":
            catches = state.get("Catch", [])
            assert catches and catches[0]["ErrorEquals"] == ["States.ALL"], name
            assert catches[0]["Next"] == "Finish" and catches[0]["ResultPath"] == "$.error", name


def test_finish_ends_and_retries():
    finish = machine()["States"]["Finish"]
    assert finish.get("End") is True
    assert finish["Retry"][0]["MaxAttempts"] >= 3


def test_every_path_reaches_finish():
    m = machine()
    states, seen, stack = m["States"], set(), [m["StartAt"]]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        s = states[name]
        nexts = [s.get("Next"), s.get("Default")] + [c["Next"] for c in s.get("Choices", [])] \
            + [c["Next"] for c in s.get("Catch", [])]
        stack += [n for n in nexts if n]
    assert seen == set(states) and "Finish" in seen


def test_poll_cap_matches_the_code():
    choice = machine()["States"]["Done?"]
    caps = [c for c in choice["Choices"] if c.get("Variable") == "$.polls"]
    assert caps[0]["NumericGreaterThanEquals"] == MAX_POLLS
