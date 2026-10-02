"""Offline OPS-001 documentation validation; no cloud/network/secret access."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = "99fa263724cabfb82245aa4d225a215d6ae60b00"
SCOPE = "docs/implementation/OPS-001/"
checks = []


def check(name, condition):
    checks.append({"name": name, "passed": bool(condition)})


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True)


files = [HERE / n for n in (
    "report.md", "operator-evidence.md", "public-probes.json", "validate_report.py"
)]
check("regular artifacts without symlinks", all(p.is_file() and not p.is_symlink() for p in files))
texts = {p.name: p.read_text(encoding="utf-8") for p in files}
report = texts["report.md"]
operator = texts["operator-evidence.md"]
probes = json.loads(texts["public-probes.json"])
check("dated report and owner", "2 October 2026" in report and "Vova" in report)
check("claim/base/branch provenance", BASE in report and "research/ops-001-runtime-evidence-20261002" in report)
for label in (
    "VERIFIED DEPLOYED FACT", "REPOSITORY DECLARATION", "AZURE PLATFORM CAPABILITY",
    "OWNER DECISION NEEDED", "UNKNOWN / EVIDENCE REQUIRED",
):
    check("classification: " + label, label in report)
check("exact blockers B1 through B8", all(f"B{i} / D{i}" in report for i in range(1, 9)))
check("pending Vova decisions D1 through D8", all(f"| D{i} |" in report for i in range(1, 9)))
check("operator evidence E1 through E7", all(f"| E{i} —" in operator for i in range(1, 8)))
check("independent DATA application delivery", "independent application implementation" in report)
check("no inferred acceptance", "never **done**" in report and "acceptance pending" in report)
check("declared topology conflict", "conflict is unresolved" in report and "AWS" in report and "B1" in report)
check("no safe load target claim", "No safe deployed load-test environment was established" in report)
check("no Azure control-plane inventory claim", "No sanitized Azure control-plane/operator inventory" in report)
for name in ("report.md", "operator-evidence.md"):
    text = texts[name]
    check(name + " balanced fences", len(re.findall(r"^```", text, re.M)) % 2 == 0)
    rows = []
    valid = True
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            rows.append(len(re.findall(r"(?<!\\)\|", line)))
        elif rows:
            valid &= len(set(rows)) == 1
            rows = []
    check(name + " table columns", valid)
    local_ok = True
    pinned_ok = True
    link_count = 0
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith("https://github.com/VladimirMalevanik/flare/blob/"):
            match = re.fullmatch(r"https://github\.com/VladimirMalevanik/flare/blob/([0-9a-f]{40})/([^#]+)(?:#L(\d+))?", target)
            if not match or match[1] != BASE or ".env" in match[2] or ".codex" in match[2]:
                pinned_ok = False
                continue
            try:
                source = git("show", f"{BASE}:{match[2]}")
                pinned_ok &= not match[3] or 1 <= int(match[3]) <= len(source.splitlines())
                link_count += 1
            except subprocess.CalledProcessError:
                pinned_ok = False
        elif not target.startswith(("https://", "#")):
            local_ok &= (HERE / target.split("#")[0]).is_file()
    check(name + " local links", local_ok)
    check(name + " pinned source paths and line anchors", pinned_ok)
    if name == "report.md":
        check("at least 20 pinned source references", link_count >= 20)

check("six dated unauthenticated GET observations", probes["method"] == "GET" and probes["authenticated"] is False and probes["probe_count"] == len(probes["results"]) == 6)
headers = {"Content-Type", "Content-Security-Policy", "Strict-Transport-Security", "Cache-Control", "X-Content-Type-Options", "X-Frame-Options"}
safe = True
for row in probes["results"]:
    url = urlparse(row["url"])
    safe &= url.scheme == "https" and not url.query and not url.username and not url.password
    safe &= url.hostname in {"flare4u.tech", "flare-api-vm-260914.azurewebsites.net", "flare-worker-vm-260914.azurewebsites.net"}
    safe &= set(row) <= {"url", "observed_at_utc", "http_status", "headers", "safe_health_fields"}
    safe &= set(row["headers"]) <= headers
    safe &= set(row.get("safe_health_fields", {})) <= {"status", "role"}
    safe &= set(row.get("safe_health_fields", {}).values()) <= {"ok", "ready", "worker"}
    safe &= row["observed_at_utc"].startswith("2026-10-02T") and row["http_status"] == 200
check("probe allowlist and successful outcomes", safe)
check("live CSP evidence", "connect-src 'self'" in probes["results"][0]["headers"]["Content-Security-Policy"])
for name, text in texts.items():
    forbidden = [
        r"(?i)/subscriptions/[0-9a-f-]+", r"(?i)[?&](?:sig|sv|se)=",
        r"(?i)(?:postgres(?:ql)?|mysql)://", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
        r"(?i)(?:DefaultEndpointsProtocol|AccountKey|SharedAccessSignature)=",
        r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b",
    ]
    # The validator contains detection expressions, not credential values.
    if name != "validate_report.py":
        check(name + " forbidden secret/resource-ID patterns", not any(re.search(p, text) for p in forbidden))
changed = set(git("diff", "--name-only", BASE).splitlines())
changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
check("all substantive changes in declared directory", bool(changed) and all(p.startswith(SCOPE) for p in changed))
check("only expected report artifacts", all(Path(p).name in {"report.md", "operator-evidence.md", "public-probes.json", "validate_report.py", "validation.json"} for p in changed))
check("git diff whitespace", subprocess.run(["git", "diff", "--check", BASE], cwd=REPO, capture_output=True).returncode == 0)
result = {
    "task": "OPS-001", "validated_at_utc": datetime.now(timezone.utc).isoformat(),
    "source_base_sha": BASE, "scope": SCOPE,
    "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks),
    "checks": checks,
    "artifact_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in files},
    "limitations": "Offline documentation/scope/redaction checks only; no Azure inventory, capacity, acceptance or production mutation verification. Pattern scan is not proof of arbitrary-secret detection; manual review is also required.",
}
print(json.dumps(result, indent=2))
raise SystemExit(0 if all(c["passed"] for c in checks) else 1)
