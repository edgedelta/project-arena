"""CLI for the 21-scenario suite: list scenarios, render manifests, and build images.

Deploy, start, verify, and reset use the main runner and save operation records.
Run `python3 -m bench.scenarios --help` for available commands.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from .__main__ import command

ROOT = Path(__file__).resolve().parents[1] / "scenarios"


def catalog():
    return json.loads((ROOT / "scenarios.json").read_text())


def render(scenario, registry="fixture.local", tag="v1"):
    if scenario not in catalog(): raise ValueError("unknown full-suite scenario")
    from .app_manifests import FLAG_FAULTS, flag_config
    if scenario in FLAG_FAULTS:
        return json.dumps(flag_config(scenario)) + "\n"
    entry = catalog()[scenario]
    if not entry.get("path"): raise ValueError("scenario manifest path missing: " + scenario)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]*", registry) or not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*", tag):
        raise ValueError("invalid image registry/tag")
    # Preserve kustomize composition; remap only image references, not narrative evidence.
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for path in (ROOT / "faults").rglob("*.yaml"):
            target = base / path.relative_to(ROOT / "faults")
            target.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text()
            text = re.sub(r"fixture\.local/([\w-]+):v1", lambda m: registry + "/" + m[1] + ":" + tag, text)
            text = text.replace("fixture.local/asset-syncer:missing-hotfix", registry + "/asset-syncer:missing-hotfix")
            target.write_text(text)
        return command(["kubectl", "kustomize", str(base / scenario / "manifests")])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    render_p = sub.add_parser("render")
    render_p.add_argument("scenario", choices=sorted(catalog()))
    render_p.add_argument("--registry", default="fixture.local")
    render_p.add_argument("--tag", default="v1")
    build = sub.add_parser("build-images")
    build.add_argument("--registry", default="fixture.local")
    build.add_argument("--tag", default="v1")
    build.add_argument("--platform", help="worker platform: linux/arm64 or linux/amd64; defaults to the Docker builder platform")
    build.add_argument("--push", action="store_true", help="explicitly publish to YOUR registry")
    build.add_argument("--kind-name", help="load built images into this local kind cluster")
    deploy_p = sub.add_parser("deploy", help="deploy original full-suite dependencies with generated disposable credentials")
    deploy_p.add_argument("--context", required=True)
    deploy_p.add_argument("--registry", default="fixture.local")
    deploy_p.add_argument("--tag", default="v1")
    for op in ["start", "verify"]:
        child = sub.add_parser(op)
        child.add_argument("scenario", choices=sorted(catalog()) + (["healthy"] if op == "verify" else []))
        child.add_argument("--context", required=True)
        if op == "verify": child.add_argument("--timeout", type=int, default=120)
    reset_p = sub.add_parser("reset", help="replace owned fixture namespaces/data and regenerate credentials")
    reset_p.add_argument("--context", required=True)
    reset_p.add_argument("--confirm-disposable", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "catalog": print(json.dumps(catalog(), indent=2))
    elif args.cmd == "render": print(render(args.scenario, args.registry, args.tag), end="")
    elif args.cmd in ["deploy", "start", "verify", "reset"]:
        from .__main__ import execute
        from .records import operation
        from .runconfig import load, resolve
        config = load()
        if args.cmd == "deploy": config.update(registry=args.registry, tag=args.tag)
        args.cmd = "fault" if args.cmd == "start" else args.cmd
        args.suite = "full"
        args.case = None
        args = resolve(args, config)
        with operation(args, config):
            execute(args, config)
    else:
        images = [(entry["image"], ROOT / "faults" / name) for name, entry in catalog().items() if "image" in entry]
        for name, image in images:
            ref = f"{args.registry}/{name}:{args.tag}"
            print(command(["docker", "build", *(["--platform", args.platform] if args.platform else []), "-t", ref, str(image)], timeout=900))
            if args.push: print(command(["docker", "push", ref], timeout=900))
            if args.kind_name: print(command(["kind", "load", "docker-image", ref, "--name", args.kind_name], timeout=300))
        print("Do not publish/build the missing-hotfix tag: image-pull intentionally references it.")


if __name__ == "__main__":
    try: sys.exit(main() or 0)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        print("error:", e, file=sys.stderr)
        sys.exit(1)
