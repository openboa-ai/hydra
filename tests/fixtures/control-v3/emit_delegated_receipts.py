"""Generate shared wire cases from actual factory/SDK delegated results.

Only the three volatile RuntimeIdentity digests and observation timestamps are
normalized. Tags, outcomes, proofs, references and source identities are retained
verbatim. A pre-change capture may be saved privately with --output; --write is
reserved for the final actual producer corpus. Neither mode adds a positive tag.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from hydra_sdlc.github import GitHubError
from delegated_decision_fixture import ATTEMPT, REPO, InstallationFixture

MATRIX_PATH = Path(__file__).with_name('delegated-source-receipts.json')
PROFILE = 'codex_delegated_v1'
NORMALIZED_RUNTIME = {'code_digest': '1' * 64, 'config_digest': '2' * 64,
                      'control_binding_digest': '3' * 64}
NORMALIZED_TIMESTAMP = '2026-01-01T00:00:00Z'
PRIVATE_CANARY = 'SYNTHETIC_PRIVATE_HANDOFF_MUST_NOT_BE_TRAVERSED'


class Harness(InstallationFixture, unittest.TestCase):
    pass


async def originals():
    """Decision publication and exact late mutable-result read-only recovery."""
    fixture = Harness()
    fixture.setup_installation()
    try:
        fixture.write_profile(True)
        fixture.make_server(new_profile=True)
        decision = fixture.reply(await fixture.invoke())
        fixture.assertEqual(decision['request']['outcome'], 'applied', decision)
        fixture.assertEqual(decision['request']['receipt']['kind'], 'decision')
        fixture.assertEqual([kind for kind, _ in fixture.transport.effects], ['context', 'receipt'])
        fixture.assertEqual(fixture.github.progress(REPO, 4)['attempt_id'], ATTEMPT)
        intended = []
        def lose_resume(body):
            intended.append(body)
            raise GitHubError('Fixture lost resume acknowledgment', uncertain=True)
        fixture.transport.patch_behavior = lose_resume
        first = fixture.reply(await fixture.invoke(fixture.command(
            continuation=True, reply_profile='standard_v1')))
        fixture.assertNotEqual(first['request']['outcome'], 'applied', first)
        fixture.assertEqual(len(intended), 1)
        fixture.assertTrue(fixture.controller.lock_path.read_bytes())
        fixture.transport.rows[0]['body'] = intended[0]
        fixture.transport.direct[1] = copy.deepcopy(fixture.transport.rows[0])
        effects = copy.deepcopy(fixture.transport.effects)
        fixture.make_server(new_profile=True)
        continuation = fixture.reply(await fixture.invoke(fixture.command(
            continuation=True, reply_profile='standard_v1')))
        fixture.assertEqual(continuation['request']['outcome'], 'applied', continuation)
        fixture.assertEqual(continuation['request']['receipt']['kind'], 'continuation')
        fixture.assertEqual(continuation['request']['receipt']['boundary'], 'existing_result_reconciled')
        fixture.assertEqual(fixture.transport.effects, effects, 'Terminal recovery must be read-only')
        fixture.assertEqual(fixture.controller.lock_path.read_bytes(), b'')
        values = {'decision': decision, 'terminal_continuation': continuation}
        for value in values.values():
            fixture.assertNotIn('handoff', value)
            fixture.assertNotIn('reply_profile', value)
            fixture.assertNotIn(str(fixture.root), json.dumps(value))
            fixture.assertNotIn(PRIVATE_CANARY, json.dumps(value))
        return values
    finally:
        fixture.doCleanups()


def normalize(value):
    normalized = copy.deepcopy(value)
    for key, replacement in NORMALIZED_RUNTIME.items():
        if normalized['runtime'][key] is not None:
            normalized['runtime'][key] = replacement
    for observation in normalized['observations']:
        for key in ('observed_at', 'last_attempt_at'):
            if observation[key] is not None:
                observation[key] = NORMALIZED_TIMESTAMP
    return normalized


def progress(value):
    proofs = [item for item in value['observations'] if item['resource']['kind'] == 'progress']
    if len(proofs) != 1:
        raise AssertionError('The actual fixture must emit one progress source before mutation')
    return proofs[0]


def mutate(value, mutation):
    """Named malformed variants; the identity mutation never adds a profile."""
    request, receipt = value['request'], value['request']['receipt']
    if mutation == 'identity':
        return
    if mutation == 'remove_profile':
        receipt.pop('profile', None)
    elif mutation == 'unknown_profile':
        receipt['profile'] = 'unknown_source_v1'
    elif mutation == 'extra_receipt_field':
        receipt['unexpected'] = True
    elif mutation == 'round_two':
        receipt['round'] = 2
    elif mutation == 'same_attempt':
        receipt['resume_attempt'] = receipt['source_attempt']
    elif mutation == 'source_attempt':
        receipt['source_attempt'] = '33333333-3333-4333-8333-333333333333'
    elif mutation == 'intent_mismatch':
        receipt['intent_ref'] = {**receipt['context_ref'], 'id': REPO + '/comments/901'}
    elif mutation == 'same_comment':
        receipt['resolved_ref'] = copy.deepcopy(receipt['context_ref'])
    elif mutation == 'foreign_decision_repository':
        for field in ('intent_ref', 'context_ref', 'resolved_ref'):
            receipt[field]['id'] = receipt[field]['id'].replace(REPO + '/', 'other/project/', 1)
        for reference in request['effect_refs']:
            reference['id'] = reference['id'].replace(REPO + '/', 'other/project/', 1)
    elif mutation == 'noncanonical_comment':
        receipt['context_ref']['id'] = REPO + '/comments/0100'
        receipt['intent_ref'] = copy.deepcopy(receipt['context_ref'])
    elif mutation in {'missing_context_effect', 'missing_receipt_effect'}:
        selected = receipt['context_ref' if mutation == 'missing_context_effect' else 'resolved_ref']
        request['effect_refs'] = [item for item in request['effect_refs'] if item != selected]
    elif mutation in {'target_repository', 'target_issue'}:
        request['target']['repository_id' if mutation == 'target_repository' else 'issue_number'] += 1
    elif mutation == 'missing_progress':
        value['observations'] = [item for item in value['observations']
                                 if item['resource']['kind'] != 'progress']
    elif mutation == 'unreferenced_progress':
        key = progress(value)['key']
        request['observed_refs'] = [item for item in request['observed_refs']
                                    if item['observation_key'] != key]
    elif mutation == 'duplicate_progress':
        additional = copy.deepcopy(progress(value))
        additional['key'] += ':duplicate'
        additional['coverage']['scope'] += ':duplicate'
        value['observations'].append(additional)
        request['observed_refs'].append({'observation_key': additional['key'],
                                         'revision': copy.deepcopy(additional['revision'])})
    elif mutation == 'partial_progress':
        progress(value)['coverage'].update(state='partial', total_count=2,
                                           next_cursor='fixture-next', reason='more_pages')
    elif mutation == 'stale_progress':
        progress(value)['availability'] = 'stale'
    elif mutation == 'progress_attempt':
        progress(value)['value']['attempt_id'] = '33333333-3333-4333-8333-333333333333'
    elif mutation == 'progress_target':
        progress(value)['value']['issue_ref']['id'] = '123:5'
    elif mutation == 'progress_repository':
        progress(value)['resource']['id'] = 'other/project/comments/1'
    elif mutation in {'progress_head', 'progress_contract'}:
        progress(value)['value']['head' if mutation == 'progress_head' else 'contract_revision'] = 'f' * 40
    elif mutation == 'continuation_attempt':
        receipt['attempt_id'] = '33333333-3333-4333-8333-333333333333'
    elif mutation == 'private_handoff':
        value['reply_profile'] = 'native_handoff_v1'
        value['handoff'] = {'untrusted_private_payload': PRIVATE_CANARY}
    else:
        raise AssertionError('Unknown frozen wire mutation: ' + mutation)


def vectors(bases=None):
    matrix = json.loads(MATRIX_PATH.read_text())
    descriptors = matrix['vectors']
    if not (matrix['fixture_version'] == 1 and 0 < len(descriptors) <= 128):
        raise AssertionError('Invalid wire fixture manifest')
    bases = asyncio.run(originals()) if bases is None else bases
    result = []
    for descriptor in descriptors:
        value = normalize(bases[descriptor['base']])
        mutate(value, descriptor['mutation'])
        result.append({'name': descriptor['name'],
            'wire': json.dumps(value, ensure_ascii=False, separators=(',', ':')),
            'schema_accepted': descriptor['schema_accepted'],
            'standard_reason': descriptor['standard_reason']})
    return result


def main():
    parser = argparse.ArgumentParser()
    outputs = parser.add_mutually_exclusive_group()
    outputs.add_argument('--output', type=Path)
    outputs.add_argument('--write', action='store_true')
    args = parser.parse_args()
    rows = vectors()
    if args.write:
        matrix = json.loads(MATRIX_PATH.read_text())
        matrix['cases'] = rows
        MATRIX_PATH.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + '\n')
    elif args.output:
        with args.output.open('x') as stream:
            json.dump(rows, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    else:
        print(json.dumps(rows, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
