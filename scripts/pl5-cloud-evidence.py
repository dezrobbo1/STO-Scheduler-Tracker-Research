#!/usr/bin/env python3
"""Fail-closed, credential-free evidence for disposable PL5 cloud gates."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

SENSITIVE = re.compile(r'("(?:token|passphrase|password|secret|credential_[ab])"\s*:\s*")([^"\n]*)(")', re.I)
BEARER = re.compile(r'(Bearer\s+)([^\s"\\]+)', re.I)

def sanitize(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = SENSITIVE.sub(r'\1[REDACTED]\3', text)
    return BEARER.sub(r'\1[REDACTED]', text)

def scan(directory, secrets):
    for path in directory.rglob('*'):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(secret and secret.encode() in data for secret in secrets):
            raise ValueError(f'credential leakage in {path.name}')
        if path.suffix in ('.txt', '.log', '.json', '.sha256'):
            text = data.decode('utf-8', errors='replace')
            if any(m[1] != '[REDACTED]' for m in SENSITIVE.findall(text)) or any(
                m[1] != '[REDACTED]' for m in BEARER.findall(text)
            ) or 'PRIVATE KEY-----' in text:
                raise ValueError(f'sensitive evidence in {path.name}')

def finalize(raw, output, secrets):
    staging = output.with_name(output.name + '-staging')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for source in raw.rglob('*'):
            if not source.is_file():
                continue
            target = staging / source.relative_to(raw)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix in ('.txt', '.log', '.json', '.sha256'):
                target.write_text(sanitize(source.read_text(errors='replace'), secrets))
            elif source.suffix == '.png':
                shutil.copyfile(source, target)
            else:
                raise ValueError(f'unexpected evidence type: {source.name}')
        scan(staging, secrets)
        shutil.rmtree(output, ignore_errors=True)
        staging.rename(output)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

def ios_screen_ready(lines):
    text = ' '.join(lines).casefold()
    return all(label in text for label in ('sto field', 'connect this device', 'project id', 'device token')) and 'native encrypted storage unavailable' not in text

def ios_wait(udid, evidence, ocr):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        subprocess.run(['xcrun', 'simctl', 'io', udid, 'screenshot', str(evidence / 'launch.png')], check=True, capture_output=True)
        lines = json.loads(subprocess.check_output([ocr, str(evidence / 'launch.png')], text=True))
        (evidence / 'screen-text.json').write_text(json.dumps(lines, indent=2) + '\n')
        if ios_screen_ready(lines):
            container = subprocess.check_output(['xcrun', 'simctl', 'get_app_container', udid, 'au.com.sto.fieldtrial', 'data'], text=True).strip()
            databases = list(Path(container).rglob('sto_field_trialSQLite.db'))
            if len(databases) != 1 or databases[0].stat().st_size < 512:
                raise ValueError('native SQLite database is missing or empty')
            with databases[0].open('rb') as handle:
                if handle.read(16) == b'SQLite format 3\x00':
                    raise ValueError('native SQLite database has an unencrypted header')
            (evidence / 'startup.json').write_text(json.dumps({'rendered_connection_form': True, 'native_store_initialized': True, 'encrypted_database_header': True, 'source_sha': os.environ['STO_BUILD_SHA'], 'recognized_labels': lines}, indent=2) + '\n')
            print('iOS rendered connection form and encrypted native-store startup confirmed')
            return
        if 'native encrypted storage unavailable' in ' '.join(lines).casefold():
            raise ValueError('native storage failed during iOS startup')
        time.sleep(2)
    raise ValueError('iOS rendered store-ready connection form did not appear within 90 seconds')

def verify_android(setup, queued, reopened, reconciled, account_b, feed):
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    for phase in (queued, reopened, reconciled):
        require(phase['project_id'] == setup['project_id'] and phase['actor_user_id'] == setup['actor_a'], 'local account identity changed')
        require(len(phase['execution']) == len(phase['communication']) == 1, 'unexpected outbox records')
    for phase in (queued, reopened):
        require(phase['cursor'] == 0 and phase['canonical_hash'] == setup['baseline_hash'] and phase['version_id'] == setup['baseline_version_id'], 'offline baseline changed')
        require(all(row['local_final_state'] == 'queued' for row in phase['execution'] + phase['communication']), 'offline work not queued')
    for phase in (reopened, reconciled):
        for kind, keys in (('execution', ('operation_id', 'payload', 'activity_uid', 'actor_user_id')), ('communication', ('id', 'text', 'activity_uid', 'actor_user_id'))):
            require(all(phase[kind][0][key] == queued[kind][0][key] for key in keys), 'durable UUID or frozen facts changed')
        require(len(phase['media']) == len(queued['media']), 'media lost across reopen')
        for before, after in zip(queued['media'], phase['media']):
            require(all(before[key] == after[key] for key in ('id', 'message_id', 'activity_uid', 'original_sha256', 'annotations', 'actor_user_id')), 'media identity/original/annotation changed')
    for kind, state in (('execution', 'applied'), ('communication', 'accepted')):
        row = reconciled[kind][0]
        require(row['local_final_state'] == state and not row.get('error_code'), 'local record not reconciled')
    events = feed['events']
    expected = 2 + len(queued['media'])
    require(feed['next_cursor'] == expected and feed['has_more'] is False and len(events) == expected, 'unexpected disposable event feed')
    require(events[0] == reconciled['execution'][0]['receipt'] and events[1] == reconciled['communication'][0]['receipt'], 'feed does not match durable local receipts')
    require(events[0]['operation_id'] == queued['execution'][0]['operation_id'] and events[1]['id'] == queued['communication'][0]['id'], 'feed UUID mismatch')
    require(all(event['project_id'] == setup['project_id'] and (index > 2 or event['actor_user_id'] == setup['actor_a']) and event['server_sequence'] == index for index, event in enumerate(events, 1)), 'unexpected feed provenance/order')
    require(reconciled['canonical_hash'] == events[0]['canonical_hash'] and reconciled['version_id'] == events[0]['result_version_id'], 'local final head differs from accepted execution')
    for media, event in zip(reconciled['media'], events[2:]):
        require(media['local_final_state'] == 'linked' and not media.get('error_code'), 'media not locally reconciled')
        require(event['kind'] == 'trial_media_link' and event['media_id'] == media['id'] and event['message_id'] == queued['communication'][0]['id'], 'media link mismatch')
        require({row['kind'] for row in media['annotations']} == {'arrow', 'circle', 'text'} and any(row.get('text', '').strip() for row in media['annotations']), 'media annotation coverage missing')
        receipt = media['remote_receipt']
        require(receipt['project_id'] == setup['project_id'] and receipt['actor_user_id'] == setup['actor_a'] and receipt['id'] == media['id'] and receipt['activity_uid'] == media['activity_uid'] and receipt['message_id'] == event['message_id'] and receipt['server_sequence'] == event['server_sequence'] and receipt['status'] == 'linked', 'uploaded media provenance/link mismatch')
        normalized = [{key: value for key, value in row.items() if value is not None} for row in receipt['annotations']]
        require(receipt['sha256'] == media['original_sha256'] and normalized == media['annotations'], 'uploaded original/annotation mismatch')
    require(account_b['actor_user_id'] == setup['actor_b'] != setup['actor_a'] and account_b['project_id'] == setup['project_id'], 'account B identity mismatch')
    require(not account_b['execution'] and not account_b['communication'] and not account_b['media'], 'account B sees account A local records')
    require(account_b['cursor'] == reconciled['cursor'] == expected and account_b['canonical_hash'] == reconciled['canonical_hash'], 'final cache/cursor mismatch')

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    safe = sub.add_parser('finalize')
    safe.add_argument('raw', type=Path)
    safe.add_argument('output', type=Path)
    safe.add_argument('--setup', type=Path)
    ios = sub.add_parser('ios-wait')
    ios.add_argument('udid')
    ios.add_argument('evidence', type=Path)
    ios.add_argument('ocr')
    args = parser.parse_args()
    if args.command == 'finalize':
        setup = json.loads(args.setup.read_text()) if args.setup else {}
        secrets = [setup.get('credential_a'), setup.get('credential_b'), os.environ.get('STO_AUTH_MASTER_KEY')]
        finalize(args.raw, args.output, secrets)
    else:
        ios_wait(args.udid, args.evidence, args.ocr)

if __name__ == '__main__':
    main()
