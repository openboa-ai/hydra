"""P14/CP: remote preflight reads release admission so Pause can win before dispatch."""
from contextvars import Context
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from hydra_sdlc.operations import OperatingControl, OperationDenied
from hydra_sdlc.runner import Runner


class DeliveryAdmissionTests(unittest.TestCase):
    def test_pause_can_apply_while_final_source_read_is_still_in_progress(self):
        for profile, effect, hook in [('deliver', 'merge', 'before_delivery'),
                                      ('publish_candidate', 'publish', 'before_publication')]:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                control = OperatingControl(Path(directory) / 'host.lock', ('example/product',))
                control.set_mode('start')
                runner = Runner(None, None, host_alias='fixture', execute=None, capabilities=None,
                                operations=control)
                revision = control.snapshot()['revision']
                applied, workers, errors, writes = Event(), [], [], []
                def pause():
                    try:
                        control.set_mode('pause', 'example/product')
                        applied.set()
                    except BaseException as error:
                        errors.append(error)
                def read(*args):
                    worker = Thread(target=pause, context=Context())
                    workers.append(worker)
                    worker.start()
                    # Event ordering is the oracle. The timeout only bounds a
                    # broken implementation that holds admission during reads.
                    self.assertTrue(applied.wait(2), 'Pause must complete before this source read returns')
                state = {'profile': profile, hook: read, 'before_callback': lambda effect: None}
                token = runner._checkpoint_ceiling.set(('example/product', revision, lambda: None, state))
                try:
                    with patch.object(runner, '_require_policy'):
                        with self.assertRaises(OperationDenied):
                            runner._effect('example/product', lambda: writes.append('sent'),
                                           _checkpoint_effect=effect)
                finally:
                    runner._checkpoint_ceiling.reset(token)
                    for worker in workers:
                        worker.join(5)
                        self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(writes, [])
                self.assertTrue(applied.is_set())

    def test_current_admission_allows_the_supported_effect_once(self):
        with tempfile.TemporaryDirectory() as directory:
            control = OperatingControl(Path(directory) / 'host.lock', ('example/product',))
            control.set_mode('start')
            runner = Runner(None, None, host_alias='fixture', execute=None, capabilities=None,
                            operations=control)
            writes, reads = [], []
            state = {'profile': 'deliver', 'before_delivery': lambda *args: reads.append('observed'),
                     'before_callback': lambda effect: None}
            token = runner._checkpoint_ceiling.set(('example/product', control.snapshot()['revision'], lambda: None, state))
            try:
                with patch.object(runner, '_require_policy'):
                    runner._effect('example/product', lambda: writes.append('sent'), _checkpoint_effect='merge')
            finally:
                runner._checkpoint_ceiling.reset(token)
            self.assertEqual(reads, ['observed'])
            self.assertEqual(writes, ['sent'])

    def test_closed_delivery_profile_rejects_publication_and_retirement_effects(self):
        runner = Runner(None, None, host_alias='fixture', execute=None, capabilities=None)
        state = {'profile': 'deliver'}
        token = runner._checkpoint_ceiling.set(('example/product', 0, lambda: None, state))
        try:
            for effect in ('publish', 'pr', 'review_request', 'checkpoint', 'resource_retirement', None):
                with self.subTest(effect=effect):
                    with self.assertRaises(OperationDenied):
                        runner._effect('example/product',
                            lambda: self.fail('An unrelated effect reached its writer'), _checkpoint_effect=effect)
        finally:
            runner._checkpoint_ceiling.reset(token)
