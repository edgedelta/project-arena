"""Run defaults; paths are relative to the configuration, never a personal profile."""
import json
import re
from pathlib import Path
from .catalog import scenarios
from .smoke import IMAGE

TEMPLATE = {
    "run_id": "demo", "product": "my-product", "suite": "full",
    "scenario": "oom", "output_dir": "runs/demo", "image": IMAGE,
    "registry": "fixture.local", "tag": "v1", "truths": {},
    "judge_command": [], "judge": {"provider": "openai", "model": "", "max_output_tokens": 8192}, "context": "",
}
KEYS = set(TEMPLATE) | {"rubric"}


def load(path=None):
    target = Path(path or "arena.json")
    if not target.exists() and path is None: return {}
    config = json.loads(target.read_text())
    if not isinstance(config, dict): raise ValueError("run configuration must be an object")
    unknown = set(config) - KEYS
    if unknown: raise ValueError("unknown run settings: " + ", ".join(sorted(unknown)))
    for key, value in config.items():
        if key == "judge":
            if not isinstance(value, dict): raise ValueError("judge must be an object")
        elif key == "truths":
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in value.items()):
                raise ValueError("truths must map scenarios to reviewed truth file paths")
        elif key == "judge_command":
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise ValueError("judge_command must be an argument array")
        elif not isinstance(value, str) or (not value and key != "context"): raise ValueError(key + " must be a nonempty string")
    base = target.resolve().parent
    for key in ["output_dir", "rubric"]:
        if key in config: config[key] = str(base / config[key])
    config["truths"] = {k: str(base / v) for k, v in config.get("truths", {}).items()}
    return config


def resolve(args, config):
    for key, default in [("suite", "smoke"), ("scenario", None), ("run_id", None), ("product", None), ("image", IMAGE), ("rubric", None)]:
        if not getattr(args, key, None): setattr(args, key, config.get(key, default))
    if args.cmd in ["deploy", "fault", "reset", "verify", "evidence"]:
        args.context = args.context or config.get("context")
        if not args.context:
            raise ValueError("set context in arena.json or supply --context")
    catalog = scenarios(args.suite)
    if args.scenario and args.scenario not in catalog and not (args.cmd == "verify" and args.scenario == "healthy"):
        raise ValueError("unknown scenario for " + args.suite + ": " + args.scenario)
    if args.cmd in ["fault", "verify", "archive"] or (args.cmd == "render" and args.suite == "full"):
        if not args.scenario: raise ValueError("select a scenario in the run file or with --scenario")
    case = args.case or getattr(args, "case_id", None) or args.scenario
    if case and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", case):
        raise ValueError("case must be a simple directory name")
    directory = Path(config.get("output_dir", "runs")) / (case or "unselected")
    args.case_directory = str(directory)
    filenames = {"archive": "archive.json", "packet": "packet.json", "judge": "judgment.json", "evidence": "evidence.json"}
    if args.cmd in filenames:
        if not args.out:
            if not case: raise ValueError("select --case or configure a scenario for default artifact paths")
            directory.mkdir(parents=True, exist_ok=True)
            args.out = str(directory / filenames[args.cmd])
    if args.cmd == "archive":
        if not args.final:
            args.final = str(directory / "final.txt")
        for name in ["intermediate", "actions"]:
            path = directory / (name + ".txt")
            if not getattr(args, name) and path.is_file(): setattr(args, name, str(path))
        args.case_id = getattr(args, "case_id", None) or (args.run_id + "-" + case if args.run_id else None)
        for key in ["run_id", "product", "case_id", "final"]:
            if not getattr(args, key, None): raise ValueError("archive requires " + key.replace("_", "-") + " in configuration or arguments")
    if args.cmd == "packet":
        args.archive = args.archive or str(directory / "archive.json")
        # Select truth from the saved investigation record, not a possibly changed run scenario.
        archive = json.loads(Path(args.archive).read_text())
        args.truth = args.truth or config.get("truths", {}).get(archive["scenario"])
    if args.cmd == "judge":
        args.packet = args.packet or str(directory / "packet.json")
        args.command = args.command or config.get("judge_command")
        if not args.manual and not args.command and not config.get("judge"):
            raise ValueError("configure judge.provider and judge.model, or supply judge_command")
    if args.cmd == "report" and not args.judgments:
        args.judgments = [str(p) for p in sorted(Path(config.get("output_dir", "runs")).glob("*/judgment.json"))]
        if not args.judgments and not ((args.summary or args.details) and (args.records or list(Path(config.get("output_dir", "runs")).glob("*/archive.json")))): raise ValueError("no judgments found in this run")
    return args
