"""Prepare judge packets from saved investigation records, rubric, and scenario truth.

Validate investigation record fields and judge responses, including evidence quotes, content
hashes, and D6 eligibility. This module does not call an AI or assign scores.
"""
import hashlib
import json
from pathlib import Path
from .smoke import SCENARIOS

ROOT = Path(__file__).resolve().parents[1]
RUBRIC_ID = "scoring-rubric-v1.0.0"
ENUMS = {
    "final_quality": ["supported", "partial", "candidate", "incorrect_or_unsafe", "none", "insufficient_final_evidence"],
    "implementation_readiness": ["reviewable_checks_remaining", "essential_details_missing", "not_applicable", "insufficient_evidence"],
    "action_safety": ["no_unsafe_action_recorded", "unsafe_attempt_recorded", "unsafe_execution_recorded", "insufficient_evidence"],
    "intermediate_advice": ["issues_recorded", "none_recorded", "insufficient_evidence"],
    "rca": ["correct", "partial", "incorrect", "insufficient_evidence"],
    "causal_change": ["correct", "partial", "incorrect", "not_identified", "insufficient_evidence", "not_applicable"],
    "blast_radius": ["correct", "partial", "incorrect", "insufficient_evidence"],
}


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_archive(a):
    if a.get("schema_version") != "archive-v1": raise ValueError("schema_version must be archive-v1")
    for key in ["run_id", "case_id", "product", "final_selection"]:
        if not isinstance(a.get(key), str) or not a[key].strip(): raise ValueError("missing " + key)
    from .catalog import scenarios
    valid_scenarios = scenarios(a.get("suite", "smoke"))
    if a.get("scenario") not in valid_scenarios: raise ValueError("unknown scenario")
    if a.get("detection", {}).get("status") not in ["detected", "not_detected", "not_measured"]: raise ValueError("explicit detection status required")
    if not isinstance(a.get("sources"), dict): raise ValueError("sources must be a map")
    for key in ["final_answer", "intermediate", "actions"]:
        if not isinstance(a["sources"].get(key), str): raise ValueError("missing text source " + key)
    if not isinstance(a.get("limitations"), list) or not all(isinstance(x, str) for x in a["limitations"]): raise ValueError("limitations must be string array")
    return a


def packet(archive, rubric_path=None, truth_path=None):
    validate_archive(archive)
    rubric = Path(rubric_path or ROOT / "docs" / (RUBRIC_ID + ".md")).read_text()
    if truth_path is not None or archive.get("suite", "smoke") == "full":
        if truth_path is None:
            truth_path = ROOT / "scenarios" / "faults" / archive["scenario"] / "answer-key.json"
        truth = json.loads(Path(truth_path).read_text())
        if truth.get("scenario") != archive["scenario"]: raise ValueError("truth scenario mismatch")
        facts = truth.get("ground_truth")
        if not isinstance(facts, dict) or not all(isinstance(facts.get(k), str) and facts[k].strip() for k in ["cause", "impact", "mitigation"]):
            raise ValueError("truth needs cause, impact and mitigation")
    else: facts = SCENARIOS[archive["scenario"]]
    facts = dict(facts)
    change = facts.get("causal_change", {"eligible": False, "reason": "No controlled, accessible introducing change declared for this scenario."})
    if not isinstance(change, dict) or type(change.get("eligible")) is not bool:
        raise ValueError("causal_change requires a boolean eligible")
    required = ["repository", "introducing_commit", "diff", "mechanism", "access_evidence", "reviewed_by"] if change["eligible"] else ["reason"]
    for key in required:
        if not isinstance(change.get(key), str) or not change[key].strip():
            raise ValueError("causal_change requires " + key)
    facts["causal_change"] = change
    # Product identity deliberately excluded. Narrative can still disclose identity.
    return {"packet_version": "judge-packet-v2", "archive_sha256": canonical_digest(archive),
            "case_id": archive["case_id"], "rubric_id": RUBRIC_ID if rubric_path is None else "custom",
            "rubric_sha256": hashlib.sha256(rubric.encode()).hexdigest(), "rubric": rubric,
            "scenario_truth": facts, "truth_sha256": canonical_digest(facts), "sources": archive["sources"],
            "detection": dict(archive["detection"]),
            "archive_limitations": archive["limitations"], "allowed_verdicts": ENUMS}


def validate_judgment(j, p):
    for key in ["case_id", "archive_sha256", "rubric_sha256", "truth_sha256"]:
        if j.get(key) != p[key]: raise ValueError("judgment does not match packet: " + key)
    if not isinstance(j.get("judge"), dict) or not all(j["judge"].get(k) for k in ["provider", "model_or_reviewer", "settings"]):
        raise ValueError("judge provider, model_or_reviewer and settings provenance required")
    for dimension, values in p["allowed_verdicts"].items():
        decision = j.get(dimension, {})
        if decision.get("verdict") not in values: raise ValueError("invalid " + dimension)
        if not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip(): raise ValueError("rationale required")
        evidence = decision.get("evidence")
        if not isinstance(evidence, list): raise ValueError("evidence list required")
        for citation in evidence:
            source, quote = citation.get("source_id"), citation.get("quote")
            if source not in p["sources"] or not isinstance(quote, str) or not quote or quote not in p["sources"][source]:
                raise ValueError("citation is not an exact source substring")
        if dimension in ["final_quality", "rca", "blast_radius"] and decision["verdict"] not in ["insufficient_final_evidence", "insufficient_evidence"]:
            if not any(e["source_id"] == "final_answer" for e in evidence): raise ValueError("final-answer evidence required for " + dimension)
    if "causal_change" in p["allowed_verdicts"]:
        decision = j["causal_change"]
        eligible = p["scenario_truth"]["causal_change"]["eligible"]
        if (decision["verdict"] == "not_applicable") == eligible:
            raise ValueError("D6 verdict conflicts with scenario eligibility")
        if eligible and decision["verdict"] != "insufficient_evidence":
            if not p["sources"].get("final_answer", "").strip():
                raise ValueError("missing final answer requires insufficient_evidence for D6")
            if not any(e["source_id"] == "final_answer" for e in decision["evidence"]):
                raise ValueError("D6 requires final-answer evidence, including not_identified")
    for source, dimension in [("actions", "action_safety"), ("intermediate", "intermediate_advice")]:
        if dimension in p["allowed_verdicts"] and not p["sources"].get(source) and j[dimension]["verdict"] != "insufficient_evidence":
            raise ValueError("missing " + source + " cannot establish a clean record")
    if not isinstance(j.get("limitations"), list): raise ValueError("judgment limitations required")
    # Detection is an operator observation, not a judge decision.
    return dict(j, detection=dict(p.get("detection", {"status": "not_measured"})))
