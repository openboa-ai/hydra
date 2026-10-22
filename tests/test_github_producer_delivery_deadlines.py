"""Verified delivery cannot be normalized beyond an effective read deadline."""
import unittest
from unittest.mock import patch
from hydra_sdlc import github_producer_delivery as delivery
from test_github_producer_delivery import Fixture


class ProducerDeliveryDeadlineTests(unittest.TestCase):
    def check_late_normalization(self, outer_seconds=None):
        client=Fixture()
        clock={'now':100.0}
        original=delivery._canonical
        normalized=[]
        def slow(value):
            text=original(value)
            if type(value) is dict and value.get('status')=='verified':
                normalized.append(value['delivery']['merge_sha'])
                clock['now']=146.0 if outer_seconds is None else 104.0
            return text
        with patch('hydra_sdlc.github.time.monotonic',side_effect=lambda:clock['now']), \
             patch.object(delivery,'_canonical',side_effect=slow):
            if outer_seconds is None:
                value=client.read()
            else:
                with client.read_budget(seconds=outer_seconds,requests=128):
                    value=client.read()
        self.assertEqual(len(normalized),1)
        self.assertNotIn('_credential_selected',client.__dict__)
        self.assertEqual((value['status'],value['reason'],value['delivery']),
                         ('unknown','delivery_source_unavailable',None))

    def test_normalization_after_the_reader_deadline_cannot_return_verified(self):
        self.check_late_normalization()

    def test_normalization_after_the_shorter_outer_deadline_cannot_return_verified(self):
        self.check_late_normalization(outer_seconds=3)
