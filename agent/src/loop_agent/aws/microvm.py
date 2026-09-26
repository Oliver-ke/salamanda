"""Lambda MicroVMs for the task Lambdas: run, wait, authenticate, talk, terminate.
No execution role is ever passed: the worker needs no AWS access, and a role's
credentials would be reachable from agent-run code via the metadata endpoint."""

import json
import time
import urllib.error
import urllib.request

INGRESS = "arn:aws:lambda:{region}:aws:network-connector:aws-network-connector:ALL_INGRESS"
EGRESS = "arn:aws:lambda:{region}:aws:network-connector:aws-network-connector:INTERNET_EGRESS"


def http_json(method: str, url: str, headers: dict, body: dict | None = None, timeout: float = 30,
              opener=urllib.request.urlopen) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**headers, "content-type": "application/json"})
    try:
        with opener(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except ValueError:
            return err.code, {}
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, {}


class MicroVMs:
    def __init__(self, client, region: str, sleep=time.sleep, clock=time.monotonic):
        self.client, self.region, self.sleep, self.clock = client, region, sleep, clock

    def run(self, image_arn: str, max_duration_s: int, client_token: str) -> dict:
        out = self.client.run_microvm(
            imageIdentifier=image_arn, maximumDurationInSeconds=max_duration_s,
            ingressNetworkConnectors=[INGRESS.format(region=self.region)],
            egressNetworkConnectors=[EGRESS.format(region=self.region)],
            idlePolicy={"maxIdleDurationSeconds": 3600, "suspendedDurationSeconds": 60,
                        "autoResumeEnabled": True},
            clientToken=client_token)
        return {"microvmId": out["microvmId"]}

    def wait_running(self, microvm_id: str, timeout_s: float = 120) -> str:
        deadline = self.clock() + timeout_s
        while True:
            vm = self.client.get_microvm(microvmIdentifier=microvm_id)
            if vm["state"] == "RUNNING":
                return vm["endpoint"].removeprefix("https://").removeprefix("http://").rstrip("/")
            if vm["state"] in ("TERMINATED", "TERMINATING", "FAILED") or self.clock() > deadline:
                raise RuntimeError(f"MicroVM {microvm_id} is {vm['state']}: {vm.get('stateReason')}")
            self.sleep(2)

    def auth_headers(self, microvm_id: str) -> dict:
        return dict(self.client.create_microvm_auth_token(
            microvmIdentifier=microvm_id, expirationInMinutes=15, allowedPorts=[{"port": 8080}])["authToken"])

    def terminate(self, microvm_id: str) -> None:
        try:
            self.client.terminate_microvm(microvmIdentifier=microvm_id)
        except (self.client.exceptions.ResourceNotFoundException, self.client.exceptions.ConflictException):
            pass
