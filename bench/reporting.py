"""Summarize detection observations and scoring verdicts with explicit denominators."""
import json
from collections import Counter
from .scoring import ENUMS

SUCCESS = {
    "detection": "detected", "rca": "correct", "blast_radius": "correct",
    "causal_change": "correct", "final_quality": "supported",
    "implementation_readiness": "reviewable_checks_remaining",
    "action_safety": "no_unsafe_action_recorded", "intermediate_advice": "none_recorded",
}


def summary(judgments, records=None):
    if len({j["rubric_sha256"] for j in judgments}) > 1:
        raise ValueError("summary requires one rubric hash")
    if len({json.dumps(j.get("judge"), sort_keys=True) for j in judgments}) > 1:
        raise ValueError("summary requires matching judge identity and settings")
    identities = [j["archive_sha256"] for j in judgments]
    if len(identities) != len(set(identities)):
        raise ValueError("summary contains repeated judgments for the same investigation record")
    for dimension, success in SUCCESS.items():
        source = records if dimension == "detection" and records is not None else judgments
        if dimension == "detection":
            values = [row.get("detection", {}).get("status", "not_measured") for row in source]
            allowed = ["detected", "not_detected", "not_measured"]
        else:
            values = [row.get(dimension, {}).get("verdict", "unscored") for row in source]
            allowed = ENUMS[dimension] + ["unscored"]
        if any(value not in allowed for value in values):
            raise ValueError("unknown verdict in summary: " + dimension)
        counts = Counter(values)
        excluded = sum(counts[value] for value in ["not_applicable", "not_measured", "unscored"])
        eligible = len(source) - excluded
        yield [dimension, "provided_records" if dimension == "detection" and records is not None else "judged_records",
               len(source), eligible, success, counts[success],
               round(100 * counts[success] / eligible, 1) if eligible else "",
               counts["not_applicable"], counts["not_measured"], counts["unscored"],
               counts["insufficient_evidence"] + counts["insufficient_final_evidence"],
               json.dumps(dict(sorted(counts.items())), sort_keys=True)]


SUMMARY_COLUMNS = ["dimension", "scope", "total", "eligible", "success_verdict", "success_count", "success_percent",
                   "not_applicable", "not_measured", "unscored", "insufficient_evidence", "verdict_counts"]

LABELS = {
    "detection": "Detection", "rca": "Root cause analysis", "blast_radius": "Blast radius",
    "causal_change": "Causal change identification", "final_quality": "Final mitigation",
    "implementation_readiness": "Implementation readiness", "action_safety": "No unsafe action recorded",
    "intermediate_advice": "No incorrect intermediate advice recorded",
}


def comparison(judgments, records=None, details=False):
    from .scoring import canonical_digest
    # Validate common policy, judge settings, duplicates and verdicts before grouping.
    list(summary(judgments, records))
    record_by_hash = {canonical_digest(r): r for r in records or []}
    keys = [(r['run_id'], r['case_id'], r['product']) for r in records or []]
    if len(keys) != len(set(keys)): raise ValueError('duplicate investigation records')
    groups = {}
    for r in records or []:
        groups.setdefault(r['product'], {'judgments': [], 'records': []})['records'].append(r)
    for j in judgments:
        record = record_by_hash.get(j['archive_sha256'])
        if records is not None and record is None:
            raise ValueError('matching investigation record missing for ' + j['case_id'])
        product = record['product'] if record else 'Unspecified product'
        groups.setdefault(product, {'judgments': [], 'records': []})['judgments'].append(j)
    if details:
        rows = [['Product', 'Run', 'Case', 'Scenario', 'Metric', 'Result', 'Included in denominator']]
        for product, group in sorted(groups.items()):
            by_hash = {j['archive_sha256']: j for j in group['judgments']}
            pairs = [(r, by_hash.get(canonical_digest(r))) for r in group['records']] if records is not None else [(None, j) for j in group['judgments']]
            for record, judgment in pairs:
                for dimension, label in LABELS.items():
                    if dimension == 'detection':
                        verdict = (record or judgment).get('detection', {}).get('status', 'not_measured')
                    else:
                        verdict = (judgment or {}).get(dimension, {}).get('verdict', 'unscored')
                    rows.append([product, (record or {}).get('run_id', ''), (record or judgment)['case_id'],
                                 (record or {}).get('scenario', ''), label, verdict,
                                 verdict not in ['not_applicable', 'not_measured', 'unscored']])
        return rows
    products = sorted(groups)
    counts = {product: {row[0]: dict(zip(SUMMARY_COLUMNS, row)) for row in summary(
        groups[product]['judgments'], groups[product]['records'] if records is not None else None)} for product in products}
    rows = [['Metric', *products]]
    for dimension, label in LABELS.items():
        cells = []
        for product in products:
            result = counts[product][dimension]
            n, total = result['success_count'], result['eligible']
            cells.append(f"{n}/{total} ({result['success_percent']:.1f}%)" if total else '—')
        rows.append([label, *cells])
    return rows
