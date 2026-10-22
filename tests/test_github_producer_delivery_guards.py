"""Independent metadata, credential and resource-boundary oracles."""
import json
import unittest
from unittest.mock import patch

from test_github_producer_delivery import CANARY, SOURCE, Fixture


class ProducerDeliveryGuardTests(unittest.TestCase):
    def test_nested_repository_identifiers_are_integers_without_numeric_coercion(self):
        for path in (['repository', 'id'], ['pr', 'head', 'repo', 'id'], ['pr', 'base', 'repo', 'id']):
            for invalid in (123.0, '123', True, None):
                with self.subTest(path=path, invalid=invalid):
                    client = Fixture()
                    target = client.observed
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = invalid
                    value = client.read()
                    self.assertEqual(value['status'], 'unknown')
                    self.assertIsNone(value['delivery'])

    def test_each_actual_credential_selection_is_checked_including_rotate_back(self):
        client = Fixture()
        original = client._credential_selected
        def rotate_and_return(kind):
            if kind == 'file':
                client._credential_selected(b'fixture-credential-one')
                client._credential_selected(b'fixture-credential-two')
                client._credential_selected(b'fixture-credential-one')
        client.hook = rotate_and_return
        value = client.read()
        self.assertEqual((value['status'], value['reason']), ('changed', 'delivery_credential_changed'))
        self.assertNotIn('_credential_selected', client.__dict__)
        self.assertEqual(client._credential_selected, original)

    def test_existing_owned_credential_hook_is_chained_and_restored(self):
        for should_rotate in (False, True):
            with self.subTest(should_rotate=should_rotate):
                client = Fixture()
                selections = []
                callback = selections.append
                client._credential_selected = callback
                def select(kind):
                    if kind == 'file':
                        client._credential_selected(b'one')
                        if should_rotate:
                            client._credential_selected(b'two')
                client.hook = select
                value = client.read()
                self.assertEqual(value['status'], 'changed' if should_rotate else 'verified')
                self.assertIs(client.__dict__['_credential_selected'], callback)
                self.assertTrue(selections)

    def test_actual_observation_byte_boundary_discards_extra_raw_data(self):
        for overflow in (0, 1):
            with self.subTest(overflow=overflow):
                client = Fixture()
                client.observed['unrequested'] = CANARY
                length = len(json.dumps(client.observed, sort_keys=True, separators=(',', ':'),
                                        ensure_ascii=False, allow_nan=False).encode('utf-8'))
                client.observed['unrequested'] += 'x' * (8_000_000 - length + overflow)
                value = client.read()
                self.assertEqual(value['status'], 'verified' if overflow == 0 else 'unknown')
                self.assertNotIn(CANARY, json.dumps(value))

    def test_last_source_response_after_deadline_never_becomes_verified(self):
        clock = {'now': 100.0}
        client = Fixture()
        count = {'n': 0}
        def delayed(kind):
            if kind == 'observe_commit':
                count['n'] += 1
                if count['n'] == 2:
                    clock['now'] = 146.0
        client.hook = delayed
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock['now']):
            value = client.read()
        self.assertEqual(value['status'], 'unknown')
        self.assertIsNone(value['delivery'])
        self.assertEqual(count['n'], 2)

    def test_foreign_policy_name_or_source_drift_never_changes_the_selected_producer(self):
        client = Fixture()
        calls = {'n': 0}
        def rename(kind):
            if kind == 'repository':
                calls['n'] += 1
                if calls['n'] == 3:
                    client.repo['full_name'] = 'other/product'
        client.hook = rename
        value = client.read()
        self.assertEqual(value['status'], 'unknown')
        self.assertEqual(value['source'], SOURCE)
        self.assertIsNone(value['delivery'])


if __name__ == '__main__':
    unittest.main()
