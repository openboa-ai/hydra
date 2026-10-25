"""Synthetic original-call/effect observations, never native qualification."""
from dataclasses import replace


class CreationHistoryFixture:
    def __init__(self, wire):
        self.wire = wire
        self.records = []
        self.current = None
        self.caller_binding = 'synthetic-caller-binding'
        self.first_execution = True
        self.transform = lambda value: value
        self.before_owner = lambda: None
        self.replay_next = False

    def begin(self):
        if self.replay_next:
            self.replay_next = False
            return
        number = len(self.records) + 1
        self.current = {'invocation_id': 'fixture-call-' + str(number),
            'execution_id': 'fixture-execution-' + str(number),
            'scope': (self.wire.repo['id'], self.wire.draft['outcome_key']),
            'intent_digest': None, 'writes': 0, 'state': 'not_dispatched'}
        self.records.append(self.current)

    def dispatch(self):
        if self.current is not None:
            self.current['writes'] += 1
            self.current['state'] = 'unconfirmed'

    def current_creation_owner(self, intent):
        from hydra_sdlc.creation_history import CreationOwner
        self.before_owner()
        if self.current is None:
            self.begin()
        return CreationOwner(self.current['invocation_id'], self.current['execution_id'],
                             self.caller_binding, intent.digest)

    def read_work_creation_history(self, intent, *, known_calls, timeout):
        from hydra_sdlc.creation_history import CreationHistory, CreationOwner, CreationPriorCall
        if self.current is None:
            self.begin()
        self.current['intent_digest'] = intent.digest
        owner = CreationOwner(self.current['invocation_id'], self.current['execution_id'],
                              self.caller_binding, intent.digest)
        prior = tuple(CreationPriorCall(**{k: r[k] for k in
            ('invocation_id', 'execution_id', 'intent_digest', 'writes', 'state')})
            for r in self.records if r is not self.current and r['scope'] == intent.scope)
        value = CreationHistory(intent.scope, intent.digest, owner, self.first_execution, True, prior)
        return self.transform(value)


def changed(value, **fields):
    return replace(value, **fields)
