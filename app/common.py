SEVERITIES = ["INFO", "WARN", "ERROR", "CRITICAL"]


class Collector:
    def __init__(self, stage):
        self.stage, self.findings, self.passed = stage, [], []

    def add(self, rule_id, severity, message, **evidence):
        self.findings.append({"rule_id": rule_id, "severity": severity, "message": message,
                              "evidence": evidence, "stage_key": self.stage})

    def ok(self, text):
        self.passed.append(text)


def get(d, path, default=None):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return default if cur is None else cur


def stage_status(findings):
    sev = {f["severity"] for f in findings}
    if sev & {"ERROR", "CRITICAL"}:
        return "error"
    if "WARN" in sev:
        return "warn"
    return "ok"
