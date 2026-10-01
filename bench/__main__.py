"""Deploy faults and score investigations using arena.json run settings."""
import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from .smoke import IMAGE, NAMESPACE, SCENARIOS, resources
from .scoring import ENUMS, packet, validate_archive, validate_judgment


def save(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(value, f, indent=2)
        f.write("\n")


def command(argv, stdin=None, timeout=180):
    result = subprocess.run(argv, input=stdin, text=True, capture_output=True, timeout=timeout)
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def kubectl(context, *args):
    return command(["kubectl", "--context", context, *args])


def guard(context):
    if not context: raise ValueError("--context must name a disposable cluster explicitly")
    raw = kubectl(context, "get", "namespace", NAMESPACE, "--ignore-not-found", "-o", "json")
    if raw.strip() and json.loads(raw)["metadata"].get("labels", {}).get("benchmark.fixture") != "portable-v1":
        raise ValueError("namespace already exists without fixture ownership label")


def main(argv=None):
    from .runconfig import load, resolve
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="run configuration JSON (defaults to arena.json when present)")
    parser.add_argument("--case", help="case/artifact directory override for a repeated attempt")
    subs = parser.add_subparsers(dest="cmd", required=True)
    subs.add_parser("init", help="write an editable arena.json run configuration")
    subs.add_parser("catalog", help="list scenarios in the configured suite")
    cluster = subs.add_parser("cluster", help="create/delete a local kind cluster; requires Docker and kind")
    cluster.add_argument("operation", choices=["create", "delete"])
    cluster.add_argument("--name", default="incident-bench")
    cluster.add_argument("--confirm-delete", action="store_true")
    for action in ["render", "deploy", "fault", "reset"]:
        p = subs.add_parser(action)
        if action in ["render", "fault"]: p.add_argument("--scenario", help="scenario from the configured suite")
        p.add_argument("--image", help="override baseline with a public image digest for reproducibility")
        if action != "render": p.add_argument("--context", help="override the context in arena.json")
        if action == "reset": p.add_argument("--confirm-disposable", action="store_true")
    verify = subs.add_parser("verify", help="confirm a full-suite fault actually manifests")
    verify.add_argument("--context", help="override the context in arena.json")
    verify.add_argument("--scenario")
    verify.add_argument("--timeout", type=int, default=120)
    evidence = subs.add_parser("evidence")
    evidence.add_argument("--context", help="override the context in arena.json")
    evidence.add_argument("--out")
    archive = subs.add_parser("archive", help="import an explicitly selected final answer")
    for name in ["run-id", "case-id", "product", "final", "out"]: archive.add_argument("--" + name)
    archive.add_argument("--scenario")
    archive.add_argument("--suite", choices=["smoke", "full"], default=None)
    archive.add_argument("--detection", choices=["detected", "not_detected", "not_measured"], default="not_measured")
    archive.add_argument("--intermediate")
    archive.add_argument("--actions")
    adapter = subs.add_parser("adapter", help="run a user-supplied product exporter: request JSON stdin -> investigation record JSON stdout")
    adapter.add_argument("--request", required=True)
    adapter.add_argument("--out", required=True)
    adapter.add_argument("command", nargs=argparse.REMAINDER)
    prep = subs.add_parser("packet")
    prep.add_argument("--archive")
    prep.add_argument("--rubric")
    prep.add_argument("--truth", help="override the bundled scenario answer key with reviewed ground truth JSON")
    prep.add_argument("--out")
    judge = subs.add_parser("judge", help="validate a manual judgment or run any external judge command")
    judge.add_argument("--packet")
    choice = judge.add_mutually_exclusive_group()
    choice.add_argument("--manual", help="path to completed judgment JSON")
    choice.add_argument("--command", nargs=argparse.REMAINDER, help="executable and arguments; packet on stdin, judgment on stdout")
    judge.add_argument("--out")
    report = subs.add_parser("report")
    report.add_argument("judgments", nargs="*")
    report_view = report.add_mutually_exclusive_group()
    report_view.add_argument("--details", action="store_true", help="scenario results and inclusion in each denominator")
    report_view.add_argument("--summary", action="store_true", help="summarize detection and every scoring dimension")
    report.add_argument("--records", nargs="+", help="investigation record JSON files, including undetected cases, for detection totals")
    args = parser.parse_args(argv)
    if args.cmd == "init":
        from .runconfig import TEMPLATE
        save(args.run or "arena.json", TEMPLATE)
        print("Created run configuration; edit product, scenario and image settings before use.")
        return
    config = load(args.run)
    args = resolve(args, config)
    if args.cmd in ["deploy", "fault", "reset", "verify", "evidence"]:
        from .records import operation
        with operation(args, config):
            return execute(args, config)
    return execute(args, config)


def execute(args, config):
    if args.cmd == "catalog":
        from .catalog import scenarios
        print("\n".join(sorted(scenarios(args.suite))))
        return
    if args.suite == "full" and args.cmd in ["render", "deploy", "fault", "reset", "verify", "evidence"]:
        from . import scenarios, cluster_ops
        if args.cmd == "render":
            print(scenarios.render(args.scenario, config.get("registry", "fixture.local"), config.get("tag", "v1")), end="")
            return
        if args.cmd == "deploy": result = cluster_ops.deploy(args.context, config.get("registry", "fixture.local"), config.get("tag", "v1"))
        elif args.cmd == "fault": result = cluster_ops.start(args.context, args.scenario)
        elif args.cmd == "reset": result = cluster_ops.reset(args.context, args.confirm_disposable)
        elif args.cmd == "verify": result = cluster_ops.verify(args.context, args.scenario, args.timeout)
        else:
            cluster_ops.guard(args.context)
            from .evidence import capture
            result = args.captured_evidence = capture(args.context, args.suite)
            save(args.out, result)
            save(args.operation_directory / "result.json", {"evidence_path": args.out})
            return
        save(args.operation_directory / "result.json", result)
        print(json.dumps(result, indent=2))
        if args.cmd == "verify" and not result["observed"]: raise ValueError("Expected fault was not observed")
        return
    if args.cmd == "verify": raise ValueError("verify currently supports full; inspect smoke evidence manually")
    if args.cmd == "cluster":
        if args.operation == "delete" and not args.confirm_delete: raise ValueError("cluster deletion needs --confirm-delete")
        print(command(["kind", args.operation, "cluster", "--name", args.name], timeout=600))
    elif args.cmd in ["render", "deploy", "fault", "reset"]:
        manifest = resources(args.scenario if args.cmd in ["fault", "render"] else None, args.image)
        if args.cmd == "render": print(json.dumps(manifest, indent=2)); return
        guard(args.context)
        print(command(["kubectl", "--context", args.context, "apply", "-f", "-"], json.dumps(manifest)))
        if args.cmd != "fault":
            print(kubectl(args.context, "-n", NAMESPACE, "rollout", "status", "deployment/api", "--timeout=120s"))
        print("Reset restores the workload; retained PVCs are not deleted automatically.")
    elif args.cmd == "evidence":
        guard(args.context)
        from .evidence import capture
        data = args.captured_evidence = capture(args.context, args.suite)
        save(args.out, data)
    elif args.cmd == "archive":
        a = {"schema_version": "archive-v1", "run_id": args.run_id, "case_id": args.case_id, "product": args.product,
             "scenario": args.scenario, "suite": args.suite, "detection": {"status": args.detection},
             "final_selection": "operator-selected final delivered answer, imported without rewriting",
             "sources": {"final_answer": Path(args.final).read_text(), "intermediate": Path(args.intermediate).read_text() if args.intermediate else "", "actions": Path(args.actions).read_text() if args.actions else ""},
             "limitations": ["Operator-selected final answer; selection must be independently reviewed."]}
        if not args.actions: a["limitations"].append("Operational action trace not provided.")
        if not args.intermediate: a["limitations"].append("Intermediate advice not provided.")
        save(args.out, validate_archive(a))
    elif args.cmd == "adapter":
        cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not cmd: raise ValueError("adapter executable required")
        save(args.out, validate_archive(json.loads(command(cmd, Path(args.request).read_text(), timeout=600))))
    elif args.cmd == "packet":
        save(args.out, packet(json.loads(Path(args.archive).read_text()), args.rubric, args.truth))
    elif args.cmd == "judge":
        if Path(args.out).exists(): raise FileExistsError("judgment output already exists: " + args.out)
        p = json.loads(Path(args.packet).read_text())
        if not args.manual and not args.command:
            from .judge import run
            run(p, config["judge"], args.out)
            print("Saved judgment:", args.out)
            return
        j = json.loads(Path(args.manual).read_text()) if args.manual else json.loads(command(args.command, json.dumps(p), timeout=600))
        save(args.out, validate_judgment(j, p))
    elif args.cmd == "report":
        writer = csv.writer(sys.stdout)
        rows = [json.loads(Path(path).read_text()) for path in args.judgments]
        if args.records and not (args.summary or args.details):
            raise ValueError("--records requires --summary or --details")
        if args.summary or args.details:
            from .reporting import comparison
            record_paths = args.records
            if record_paths is None:
                candidates = set(Path(config.get("output_dir", "runs")).glob("*/archive.json"))
                candidates.update(Path(path).parent / "archive.json" for path in args.judgments)
                record_paths = sorted(p for p in candidates if p.is_file())
            records = [validate_archive(json.loads(Path(path).read_text())) for path in record_paths] if record_paths else None
            writer.writerows(comparison(rows, records, args.details))
            return
        writer.writerow(["case_id", "archive_sha256", "rubric_sha256", "truth_sha256", "detection", "d6_eligible", *ENUMS])
        for j in rows:
            d6 = j.get("causal_change", {}).get("verdict")
            writer.writerow([j["case_id"], j["archive_sha256"], j["rubric_sha256"], j["truth_sha256"], j.get("detection", {}).get("status", "not_measured"),
                             "" if d6 is None else d6 != "not_applicable",
                             *[j.get(k, {}).get("verdict", "") for k in ENUMS]])


if __name__ == "__main__":
    try: main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("error:", error, file=sys.stderr)
        sys.exit(1)
