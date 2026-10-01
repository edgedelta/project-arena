"""Sample records shared by scoring tests."""

def archive():
    return {"schema_version": "archive-v1", "run_id": "r", "case_id": "c", "product": "private-label",
            "scenario": "crashloop", "detection": {"status": "not_measured"}, "final_selection": "final report",
            "sources": {"final_answer": "Restore healthy mode. API is down.", "intermediate": "", "actions": ""}, "limitations": []}


def judgment(p):
    j = {k: p[k] for k in ["case_id", "archive_sha256", "rubric_sha256", "truth_sha256"]}
    j["judge"] = {"provider": "manual", "model_or_reviewer": "test", "settings": "manual"}
    for k in p["allowed_verdicts"]:
        j[k] = {"verdict": "insufficient_evidence" if k != "final_quality" else "supported", "rationale": "test rationale", "evidence": []}
    j["final_quality"]["evidence"] = [{"source_id": "final_answer", "quote": "Restore healthy mode."}]
    if "causal_change" in p["allowed_verdicts"]:
        j["causal_change"]["verdict"] = "not_applicable" if not p["scenario_truth"]["causal_change"]["eligible"] else "insufficient_evidence"
    j["detection"] = dict(p.get("detection", {"status": "not_measured"}))
    j["limitations"] = []
    return j

