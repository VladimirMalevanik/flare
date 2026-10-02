"""Offline ARCH-001 design checks. No application imports, credentials or network.

Run from any directory: python3 /absolute/path/to/research_checks.py
Results go beside this file. These are synthetic contract checks and arithmetic,
not measured Groq costs, production concurrency tests, or retrieval benchmarks.
"""
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import math
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE_SHA = "71e26d9cfbfec836770d4e43d4a79fe53bf32686"
SOURCE_PATHS = [
    "backend/app/config.py",
    "backend/app/services/context_selection.py",
    "backend/app/models/analysis_runs.py",
    "backend/migrations/versions/0018_rotate_analysis_context.py",
    "backend/app/services/item_service.py",
    "backend/app/services/import_service.py",
    "backend/app/models/tables.py",
    "backend/app/models/flares.py",
    "backend/app/ai_engine/enrichment_prompts.py",
    "backend/app/ai_engine/prompts/enrichment.md",
    "backend/app/ai_engine/prompts/flare_generation.md",
    "backend/app/ai_engine/groq_structured.py",
    "backend/app/ai_engine/flare_config.py",
    "backend/db/schema.sql",
    "docs/ANALYZE_QUOTA_DECISION.md",
]


def cost(input_tokens, output_tokens, factor=Decimal("1")):
    return ((Decimal(input_tokens) * Decimal("0.075")
             + Decimal(output_tokens) * Decimal("0.30")) / Decimal(1_000_000)) * factor


def split_utf8(text, byte_limit):
    """Toy offset-preserving slice contract, not the proposed semantic chunker."""
    chunks, start, size = [], 0, 0
    for offset, char in enumerate(text):
        n = len(char.encode("utf-8"))
        if n > byte_limit:
            raise ValueError("One code point exceeds bound")
        if size + n > byte_limit:
            chunks.append((start, offset, text[start:offset]))
            start, size = offset, 0
        size += n
    if start < len(text):
        chunks.append((start, len(text), text[start:]))
    return chunks


def check():
    checks = []

    def passed(name, condition):
        assert condition, name
        checks.append(name)

    samples = ["A" * 200_000, ("Цель: выпуск 🚀.\r\n" * 4_000),
               "e\u0301 / \ufeff # Decision\n" * 2_000]
    chunk_results = []
    for i, text in enumerate(samples):
        chunks = split_utf8(text, 4_000)
        passed(f"slice_{i}_reconstructs_exact_text", "".join(c[2] for c in chunks) == text)
        passed(f"slice_{i}_utf8_bound", all(len(c[2].encode("utf-8")) <= 4_000 for c in chunks))
        passed(f"slice_{i}_offset_lineage", all(text[a:b] == c for a, b, c in chunks))
        chunk_results.append({"characters": len(text), "utf8_bytes": len(text.encode("utf-8")),
                              "slices": len(chunks)})

    # Serial simulation of atomic-admission semantics; no claim of DB proof.
    cap, held, spent = Decimal("0.00105"), Decimal("0"), Decimal("0")
    reserve = cost(4_000, 1_024)
    admitted = 0
    for _ in range(10_000):
        if spent + held + reserve <= cap:
            held += reserve
            admitted += 1
    passed("large_import_admits_only_one_reserved_call", admitted == 1)
    spent, held = held, Decimal("0")  # timeout: keep conservative charge
    passed("unknown_timeout_does_not_refund", spent + reserve > cap)
    passed("paid_120b_same_tokens_cost_twice_20b", reserve * 2 == Decimal("0.0012144"))

    # Curated evidence fixture: summaries have no authority; source revalidation
    # removes stale/deleted/cross-workspace candidates before original loading.
    sources = {
        "goal": {"ws": "a", "current": True, "deleted": False,
                 "text": "Our goal is to ship billing. We decided no OAuth in v1."},
        "completion": {"ws": "a", "current": True, "deleted": False,
                       "text": "Billing shipped. The prior blocker is resolved."},
        "stale": {"ws": "a", "current": False, "deleted": False, "text": "Old plan"},
        "deleted": {"ws": "a", "current": True, "deleted": True, "text": "Removed plan"},
        "foreign": {"ws": "b", "current": True, "deleted": False, "text": "Other workspace"},
    }
    valid = [key for key, s in sources.items() if s["ws"] == "a" and s["current"] and not s["deleted"]]
    passed("current_retrieval_filters_workspace_version_deletion", valid == ["goal", "completion"])
    quote = "We decided no OAuth in v1."
    passed("citation_uses_original_substring", quote in sources["goal"]["text"])
    passed("summary_paraphrase_not_valid_original_quote", "Avoid login integrations" not in sources["goal"]["text"])
    # Missing completion makes state unknown. It cannot manufacture unfinished.
    selected = ["goal"]
    state = "completed" if "completion" in selected else "unknown"
    passed("omitted_completion_is_unknown_not_unfinished", state == "unknown")
    passed("paired_goal_and_completion_can_fit_five_source_limit", len(valid) <= 5)

    scenarios = []
    for sections in [100, 1_000, 10_000]:
        scenarios.append({
            "sections": sections,
            "assumed_input_tokens_per_section_including_envelope": 2_000,
            "assumed_total_completion_tokens_per_section": 500,
            "standard_20b_usd_estimate_no_retries": str(cost(2_000, 500) * sections),
            "batch_20b_usd_estimate_if_eligible_no_retries": str(cost(2_000, 500, Decimal("0.5")) * sections),
            "serial_days_at_illustrative_20k_enrichment_tokens_per_day": math.ceil(sections * 2_500 / 20_000),
        })
    inventory = []
    for path in SOURCE_PATHS:
        data = subprocess.check_output(["git", "show", f"{SOURCE_SHA}:{path}"], cwd=ROOT)
        inventory.append({"path": path, "source_sha": SOURCE_SHA,
                          "sha256": hashlib.sha256(data).hexdigest(),
                          "lines": len(data.splitlines())})
    return {"evidence_class": "offline synthetic design checks and estimated arithmetic",
            "provider_calls": 0, "measured_provider_usage": None,
            "production_quality_or_latency_measured": False,
            "source_sha": SOURCE_SHA, "checks_passed": checks,
            "utf8_fixtures": chunk_results,
            "reservation_simulation": {"requests_considered": 10_000, "admitted": admitted,
                                       "illustrative_usd_cap": str(cap), "per_call_upper_reservation": str(reserve)},
            "cost_sensitivity_estimates": scenarios, "source_inventory": inventory}


if __name__ == "__main__":
    result = check()
    output = HERE / "research-results.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checks_passed": len(result["checks_passed"]),
                      "provider_calls": result["provider_calls"], "output": str(output)}))
