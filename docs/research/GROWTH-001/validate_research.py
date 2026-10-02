"""Validate this research bundle only; no app imports, credentials or network.

The SQLite fixture illustrates reporting definitions, not deployed product logic.
All fixture users, campaigns and events are fictional. Run from any directory.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCOPE = "docs/research/GROWTH-001/"
BASE = "7d734d4deabb90eb0d22a6e2840bf8755f44c13b"
checks = []


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


evidence = json.loads((HERE / "repository-evidence.json").read_text())
check("source SHA pinned", evidence["source_sha"] == BASE)
for entry in evidence["files"]:
    data = subprocess.check_output(["git", "-C", str(ROOT), "show", BASE + ":" + entry["path"]])
    check("source hash: " + entry["path"], hashlib.sha256(data).hexdigest() == entry["sha256"])
    lines = data.decode().splitlines()
    check("line anchors: " + entry["path"], all(
        1 <= a["line"] <= len(lines) and a["text"] in lines[a["line"] - 1]
        for a in entry["anchors"]
    ))

report = (HERE / "report.md").read_text()
links = re.findall(r"https://github.com/VladimirMalevanik/flare/blob/([a-f0-9]{40})/([^\s)]+)", report)
for sha, target in links:
    check("report source link pinned", sha == BASE)
    path, _, fragment = target.partition("#")
    lines = git("show", sha + ":" + path).splitlines()
    if fragment:
        match = re.fullmatch(r"L(\d+)(?:-L(\d+))?", fragment)
        check("report source line range: " + target, bool(match) and
              1 <= int(match[1]) <= int(match[2] or match[1]) <= len(lines))

probes = json.loads((HERE / "public-probes.json").read_text())
check("nine timestamped public observations", len(probes) == 9 and all(p.get("checked_at") for p in probes))
check("eight successful public reads, one auth denial", sum(p.get("status") == 200 for p in probes) == 8
      and probes[-1]["status"] == 401)
assets = json.loads((HERE / "public-assets.json").read_text())
check("eleven checked static landing assets", len(assets["scripts"]) == 11)
check("no configured telemetry markers in checked assets", all(not a["markers"] for a in assets["scripts"]))
check("observed CSP limits browser connections", "connect-src 'self'" in
      assets["public_response_headers"]["Content-Security-Policy"])
check("report preserves bounded observation caveat", "server-side instrumentation" in report)

# A small, executable example of dedupe, chronology and cohort eligibility.
# D7 is a proposed half-open [signup+7d, signup+8d) UTC window, not an approved KPI.
db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE accounts(id TEXT, signup TEXT, channel TEXT, verification TEXT);
CREATE TABLE events(actor TEXT, at TEXT, kind TEXT, mode TEXT, outcome TEXT);
INSERT INTO accounts VALUES
 ('u1','2026-01-01','alpha','bypass'),
 ('u2','2026-01-01','beta','link_confirmed'),
 ('u3','2026-01-25','unknown','unknown');
INSERT INTO events VALUES
 ('u1','2026-01-02','import_completed',NULL,'i1'),
 ('u1','2026-01-02','import_completed',NULL,'i1'),
 ('u2','2026-01-02','import_completed',NULL,'i2'),
 ('u3','2026-01-26','import_completed',NULL,'i3'),
 ('u2','2026-01-02','import_failed',NULL,'failed'),
 ('u1','2026-01-03','analyze_completed','manual','a1'),
 ('u1','2026-01-03','analyze_completed','manual','a1'),
 ('u2','2026-01-03','analyze_completed','scheduled','a2'),
 ('u3','2026-01-24','analyze_completed','manual','before-signup'),
 ('u1','2026-01-08','analyze_completed','scheduled','a3'),
 ('u1','2026-01-09','capture_completed',NULL,'day8-upper-bound'),
 ('u2','2026-01-08','capture_completed',NULL,'day7-lower-bound'),
 ('u2','2026-01-08','capture_completed',NULL,'day7-lower-bound'),
 ('u3','2026-01-26','capture_completed',NULL,'immature');
""")
distinct_imports = db.execute("""
 SELECT count(*) FROM (
   SELECT DISTINCT e.actor,e.outcome FROM events e JOIN accounts a ON a.id=e.actor
   WHERE e.kind='import_completed' AND e.at>=a.signup
 )
""").fetchone()[0]
check("synthetic import replay dedupes and failure excluded", distinct_imports == 3)
link_confirmed = db.execute("SELECT count(*) FROM accounts WHERE verification='link_confirmed'").fetchone()[0]
check("synthetic bypass and unknown excluded from email-link conversion", link_confirmed == 1)
activated = [r[0] for r in db.execute("""
 SELECT a.id FROM accounts a WHERE EXISTS (
   SELECT 1 FROM events c JOIN events e ON e.actor=c.actor
   WHERE c.actor=a.id AND c.kind='import_completed' AND c.at>=a.signup
     AND e.kind='analyze_completed' AND e.mode='manual' AND e.at>=c.at
 ) ORDER BY a.id
""")]
check("synthetic manual activation requires signup/content chronology", activated == ["u1"])
mature = [r[0] for r in db.execute("""
 SELECT id FROM accounts WHERE date(signup,'+8 days')<='2026-01-27' ORDER BY id
""")]
check("synthetic immature D7 cohort excluded", mature == ["u1", "u2"])
retained = [r[0] for r in db.execute("""
 SELECT a.id FROM accounts a
 WHERE date(a.signup,'+8 days')<='2026-01-27' AND EXISTS (
   SELECT 1 FROM events e WHERE e.actor=a.id AND e.kind='capture_completed'
     AND e.at>=date(a.signup,'+7 days') AND e.at<date(a.signup,'+8 days')
 ) ORDER BY a.id
""")]
check("synthetic voluntary D7 excludes automation, dedupes and honors boundaries", retained == ["u2"])
db.close()

paths = set(git("diff", "--name-only", BASE).splitlines())
paths.update(git("ls-files", "--others", "--exclude-standard").splitlines())
check("all task changes confined to declared scope", bool(paths) and all(p.startswith(SCOPE) for p in paths))
subprocess.run(["git", "-C", str(ROOT), "diff", "--check", BASE], check=True)
check("git diff whitespace check", True)

result = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "source_sha": BASE,
    "passed": True,
    "check_count": len(checks),
    "checks": checks,
    "changed_paths_at_check": sorted(paths),
    "synthetic_example_only": {
        "not_production_metrics": True,
        "distinct_published_imports": distinct_imports,
        "explicit_email_link_confirmations": link_confirmed,
        "manual_activation_users": activated,
        "mature_d7_users": mature,
        "voluntary_d7_users": retained,
    },
    "limitations": [
        "No runtime product tests/builds/migrations run: changes are research artifacts only.",
        "No Azure management or authenticated production analytics/database validation.",
        "Synthetic SQL illustrates proposed definitions; not a Flare ingestion implementation test.",
    ],
}
(HERE / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"passed": True, "check_count": len(checks), "output": str(HERE / "validation.json")}))
