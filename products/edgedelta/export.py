"""Capture an Edge Delta thread with edx, then export its selected final report for scoring.

Account settings come from a local config file. Captures keep the API responses
unchanged; export creates the benchmark's archive-v1 record without shortening
messages or tool results. No cluster or Edge Delta settings are modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench.scoring import validate_archive


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def messages(payload):
    rows = payload if isinstance(payload, list) else next((payload[k] for k in ('items', 'data', 'messages') if k in payload), None)
    if not isinstance(rows, list) or not all(isinstance(m, dict) for m in rows):
        raise ValueError('Expected a message list in the API response')
    ids = [m.get('id') for m in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Messages must have unique IDs')
    if isinstance(payload, dict):
        if payload.get('nextCursor') or payload.get('next_cursor'):
            raise ValueError('Message response has an unfetched page')
        if isinstance(payload.get('total_items'), int) and payload['total_items'] != len(rows):
            raise ValueError('Message count does not match the response total')
    return rows


def thread(value):
    result = value.get('data', value)
    if not isinstance(result, dict): raise ValueError('Invalid thread response')
    return result


def text(message):
    return '\n\n'.join(p['text'] for p in message.get('parts', []) if p.get('type') == 'text' and isinstance(p.get('text'), str) and p['text'])


def extract(rows, final_id):
    if any(not m.get('createdAt') for m in rows): raise ValueError('Message timestamps required for ordering')
    ordered = sorted(rows, key=lambda m: m['createdAt'])
    selected = [m for m in ordered if m['id'] == final_id]
    if len(selected) != 1: raise ValueError('Selected final message was not found exactly once')
    final = selected[0]
    if final.get('senderId') != 'system' or final.get('role') not in ('agent', 'assistant') or final.get('state') != 'done':
        raise ValueError('Select a completed orchestrator answer')
    answer = text(final)
    if not answer.strip() or '**MONITOR EVENT DETAILS**' in answer or 'mention_agent:' in answer or any(p.get('type') == 'trigger-details' for p in final.get('parts', [])):
        raise ValueError('Selected message is empty, an alert, or a delegation')
    if any(m.get('state') in ('created', 'in-progress') for m in ordered):
        raise ValueError('Investigation still contains unfinished messages')
    position = ordered.index(final)
    if any(text(m).strip() or any(p.get('type') in ('tool', 'approval') for p in m.get('parts', [])) for m in ordered[position + 1:]):
        raise ValueError('Further investigation follows the selected answer')
    earlier = [text(m) for m in ordered[:position] if m.get('role') in ('agent', 'assistant') and text(m).strip()
               and '**MONITOR EVENT DETAILS**' not in text(m) and not any(p.get('type') == 'trigger-details' for p in m.get('parts', []))]
    actions = [{'message_id': m['id'], 'sender_id': m.get('senderId'), 'role': m.get('role'), 'part': p}
               for m in ordered for p in m.get('parts', []) if p.get('type') in ('tool', 'approval')]
    # An absent trace stays missing; an empty JSON list must not imply proven safety.
    return {'final_answer': answer, 'intermediate': '\n\n--- next recorded message ---\n\n'.join(earlier),
            'actions': json.dumps(actions, ensure_ascii=False, indent=2) if actions else ''}


def capture(config, thread_id, directory):
    for key in ('profile', 'org', 'channel'):
        if not isinstance(config.get(key), str) or not config[key].strip(): raise ValueError('Configure ' + key)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    env = {k: v for k, v in os.environ.items() if k not in ('ED_API_TOKEN', 'ED_ORG_ID', 'ED_ENV', 'EDX_PROFILE')}
    base = ['edx', '--profile', config['profile'], '--org', config['org'], '--timeout', '90s']
    def fetch(args, filename):
        result = subprocess.run(base + ['ai', 'threads', *args, '--channel', config['channel'], '-o', 'json'], env=env, capture_output=True, timeout=120)
        with os.fdopen(os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f: f.write(result.stdout)
        if result.returncode:
            with os.fdopen(os.open(directory / 'error.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f: f.write(result.stderr)
            raise RuntimeError('edx request failed; see the private capture directory')
        return json.loads(result.stdout)
    before = thread(fetch(['get', thread_id], 'thread.json'))
    if before.get('id') != thread_id or before.get('state') != 'resolved': raise ValueError('Expected the requested resolved thread')
    rows = messages(fetch(['messages', thread_id, '--all'], 'messages.json'))
    write(directory / 'capture.json', {'thread_id': thread_id, 'channel_id': config['channel'], 'org_id': config['org'],
          'captured_at': datetime.now(timezone.utc).isoformat(), 'messages_sha256': hashlib.sha256((directory/'messages.json').read_bytes()).hexdigest()})
    # IDs and states help select the final report without printing private content.
    print(json.dumps([{'id': m['id'], 'sender': m.get('senderId'), 'state': m.get('state'), 'text_characters': len(text(m))} for m in rows], indent=2))


def export(directory, final_id, run_path, output, case_id=None):
    from bench.runconfig import load
    config = load(run_path)
    directory = Path(directory)
    receipt = json.loads((directory/'capture.json').read_text())
    raw = (directory/'messages.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt['messages_sha256']: raise ValueError('Captured messages changed')
    sources = extract(messages(json.loads(raw)), final_id)
    scenario = config.get('scenario')
    run_id = config.get('run_id')
    record = {'schema_version': 'archive-v1', 'suite': config.get('suite', 'full'), 'scenario': scenario,
              'run_id': run_id, 'case_id': case_id or (str(run_id) + '-' + str(scenario)), 'product': 'Edge Delta',
              'detection': {'status': 'not_measured'},
              'final_selection': 'Operator selected completed orchestrator message ' + final_id + ' in thread ' + receipt['thread_id'] + '; later investigation rejected.',
              'sources': sources,
              'capture': dict(receipt, final_message_id=final_id, exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
              'limitations': ['API-visible messages only; hidden or upstream-truncated content cannot be recovered.',
                             'Thread existence does not establish detection within the benchmark observation window.',
                             'Tool JSON is retained without truncation; review captured content for credentials before sending it to a judge or sharing it.']}
    for key in ('intermediate', 'actions'):
        if not sources[key]: record['limitations'].append(key + ' evidence unavailable.')
    write(output, validate_archive(record))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('capture', help='download a resolved thread without modifying it')
    c.add_argument('thread_id'); c.add_argument('--config', default='products/edgedelta/local.json'); c.add_argument('--out', required=True)
    e = commands.add_parser('export', help='convert a saved capture to the standard scoring record')
    e.add_argument('--capture', required=True); e.add_argument('--final-message', required=True)
    e.add_argument('--run', default='arena.json'); e.add_argument('--out', required=True); e.add_argument('--case-id')
    args = parser.parse_args()
    if args.command == 'capture': capture(json.loads(Path(args.config).read_text()), args.thread_id, args.out)
    else:
        export(args.capture, args.final_message, args.run, args.out, args.case_id)
        print('Saved investigation record:', args.out)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('error:', error, file=sys.stderr); sys.exit(1)
