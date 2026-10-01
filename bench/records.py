"""Record what the benchmark ran, when it ran, and whether it succeeded.

Wrap an operation such as fault injection or reset and save its settings, source
hashes, start/end times, and outcome under the case's operations/ directory. Each
operation also gets a cluster snapshot from evidence.py, including after failure,
so a broken setup can be distinguished from a product investigation failure.
These files support run review; they do not assign scores to the product.
"""
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(value, f, indent=2); f.write('\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprints(scenario):
    paths = list((ROOT / 'bench').glob('*.py')) + list((ROOT / 'scenarios/shop').rglob('*'))
    if scenario:
        # Composite scenarios can use other faults; include all definitions.
        paths += list((ROOT / 'scenarios/faults').rglob('*.yaml'))
        paths += list((ROOT / 'scenarios/faults').rglob('run.sh'))
        paths += list((ROOT / 'scenarios/faults').rglob('Dockerfile'))
        paths += list((ROOT / 'scenarios/faults').rglob('answer-key.json'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.is_file()}


@contextmanager
def operation(args, config):
    """Save started.json before execution, then evidence.json and finished.json.

    A completed operation means its command succeeded, not that the product
    diagnosed or fixed the incident. Exceptions still propagate to the caller.
    """
    directory = Path(args.case_directory) / 'operations' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + args.cmd + '-' + uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    args.operation_directory = directory
    record = {'operation': args.cmd, 'started_at': now(), 'context': args.context, 'suite': args.suite,
              'scenario': args.scenario, 'run_id': args.run_id, 'product': args.product,
              'configuration': {k: config[k] for k in ['registry', 'tag', 'image', 'suite', 'scenario', 'context'] if k in config},
              'source_sha256': fingerprints(args.scenario)}
    write(directory / 'started.json', record)
    try:
        yield
        record['status'] = 'completed'
    except BaseException as error:
        record['status'] = 'failed'; record['error_type'] = type(error).__name__
        raise
    finally:
        record['finished_at'] = now()
        # Capture a partial state even after an unsuccessful deployment/reset.
        try:
            from .evidence import capture
            snapshot = getattr(args, 'captured_evidence', None)
            if snapshot is None: snapshot = capture(args.context, args.suite)
            write(directory / 'evidence.json', snapshot)
        except Exception as error:
            record['evidence_error'] = type(error).__name__
        write(directory / 'finished.json', record)
