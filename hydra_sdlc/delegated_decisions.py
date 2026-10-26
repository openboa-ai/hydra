"""GitHub-backed delegated dialogue effects, without native-history claims.

The public pair is semantic state. The existing host inode owns bounded physical
dispatches; it never stores a question, answer, or intended progress payload.
"""
import copy
import hashlib
import json
import uuid

from .coordinator import (HostBusy, claim_decision_owner, coordinator_lock,
    current_decision_owner, operation_scope, resume_new, retire_decision_owner,
    retire_undispatched_decision, spend_publication)
from .decision_coordinator import DecisionEffectResult
from .github import GitHubError
from .operations import OperationDenied
from .project import load_project
from .public_delegated_decisions import (delegated_context_basis, delegated_decision_root,
    delegated_receipt_body, find_delegated_public_decision, read_delegated_public_decision)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()


def effect_scope(context, record=None, progress_ref=None):
    identity = {'profile': 'codex_delegated_v1', 'root': delegated_decision_root(context)}
    if record is not None:
        if progress_ref is None:
            raise OperationDenied('decision_checkpoint_missing')
        identity['resumed_record_sha256'] = _digest(record)
        identity['progress_ref'] = progress_ref
    return _digest(identity)


def _waiting(record, context):
    basis = delegated_context_basis(context)
    if (record.get('attempt_id') != context.key[2] or record.get('native_step')
            or record.get('pending_action') is not None or record.get('wait_reason') != 'product_decision'
            or record.get('next_action') != 'operator_decision'
            or record.get('phase') in {'executing', 'completed', 'merging'}
            or record.get('branch') != f'hydra/issue-{context.key[1]}'
            or record.get('resume_phase') != basis['origin_phase']
            or any(record.get(key) != basis[key] for key in
                   ('head', 'contract_revision', 'spec_revision', 'intake_digest'))):
        raise OperationDenied('stale_decision')


def resumed_record(record, context):
    """Compute the complete intended record before claiming mutable ownership."""
    _waiting(record, context)
    basis = delegated_context_basis(context)
    return {**copy.deepcopy(record), 'attempt_id': basis['resume_attempt'],
        'phase': 'implementation_done' if basis['origin_phase'] in {'correction', 'change_review'} else 'ready',
        'wait_reason': None, 'pending_action': None, 'resume_phase': basis['origin_phase'],
        'next_action': 'decision_context_' + context.key[2]}


def _consumed(source, context):
    basis = delegated_context_basis(context)
    return (source['native_root'] == delegated_decision_root(context)
        and source['record'].get('attempt_id') == basis['resume_attempt']
        and source['decision_context'] == {'source_attempt': context.key[2],
                                          'resume_attempt': basis['resume_attempt']})


def observe_work(runner, repository, number, record, *, timeout=15):
    """Return v2 facts or explicit absence; malformed claims never fall back."""
    reader = runner.github.read_client()
    if not callable(getattr(reader, '_identity', None)) or record is None:
        return None
    with reader.read_budget(seconds=timeout, requests=64):
        source = reader.decision_progress_source(repository, number)
        if source is None or source['record'] != record:
            raise OperationDenied('decision_source_changed')
        root = source['native_root']
        linked = source['decision_context']
        attempt = (root['decision']['key']['source_attempt'] if root is not None else
                   linked['source_attempt'] if linked is not None else record['attempt_id'])
        context, public = find_delegated_public_decision(reader, repository, number, attempt,
                                                        expected_root=root)
        if context is None and public.status == 'not_observed':
            return None
        if context is None or public.status != 'pair':
            raise OperationDenied(public.reason or 'decision_pair_missing')
        if (record.get('host_alias') != runner.host or record.get('execution_mode') != 'native'
                or record.get('repository_id') != context.key[0]
                or record.get('issue_number') != number or record.get('branch') != f'hydra/issue-{number}'):
            raise OperationDenied('decision_binding_mismatch')
        if not _consumed(source, context):
            if root is not None or linked is not None:
                raise OperationDenied('decision_source_changed')
            _waiting(record, context)
        return context, source, public


def continuation_scopes(runner, repository, number, record):
    observed = observe_work(runner, repository, number, record)
    if observed is None:
        return frozenset()
    context, source, _ = observed
    intended = source['record'] if _consumed(source, context) else resumed_record(source['record'], context)
    return frozenset({('publication', effect_scope(context)),
        ('resume', effect_scope(context, intended, source['resource']))})


def recover_resume_owner(continuation):
    """Retire a positively observed old PATCH, without entering a new lifecycle step."""
    owner = current_decision_owner()
    if owner is None or owner[0] != 'resume':
        return False
    runner, repository, number = continuation.runner, continuation.repository, continuation.number
    observed = observe_work(runner, repository, number, continuation.expected)
    if observed is None:
        raise OperationDenied('decision_resume_unknown')
    context, source, _ = observed
    if not _consumed(source, context) or owner[1] != effect_scope(context, source['record'], source['resource']):
        raise OperationDenied('decision_resume_unknown')
    reader = runner.github.read_client()
    with reader.read_budget(seconds=30, requests=128):
        _current_policy(runner, reader, repository, number, source['record'], context.key[0])
    # Recheck the exact public root after policy reads, before local retirement.
    fresh = observe_work(runner, repository, number, source['record'])
    if fresh is None or fresh[0] != context or fresh[1] != source:
        raise OperationDenied('decision_source_changed')
    with continuation.guard(repository):
        # The final progress read inside the guard must still identify the
        # original mutable source, not a byte-identical replacement comment.
        if (continuation.source is None or any(continuation.source.get(key) != source[key]
                                              for key in ('record', 'resource'))):
            raise OperationDenied('decision_source_changed')
        handle = claim_decision_owner('resume', owner[1], continuation.command['request_id'])
        retire_decision_owner(handle)
    if source['resource'] not in continuation.confirmed_refs:
        continuation.confirmed_refs.append(copy.deepcopy(source['resource']))
    return True


def _current_policy(runner, reader, repository, number, record, repository_id):
    config = load_project(reader, repository)
    pinned = load_project(reader, repository, revision=record['contract_revision'])
    if config['repository_id'] != repository_id or pinned['blob_sha'] != config['blob_sha']:
        raise OperationDenied('policy_changed')
    reason = runner._latest(repository, number, {**config, 'intake_digest': record['intake_digest']}, github=reader)
    if reason:
        raise OperationDenied(reason)


def _target(controller, repository, number, context):
    runner = controller.runner
    reader = runner.github.read_client()
    with reader.read_budget(seconds=30, requests=128):
        source = reader.decision_progress_source(repository, number)
        if source is None:
            raise OperationDenied('decision_checkpoint_missing')
        record = source['record']
        if (record.get('repository_id') != context.key[0] or record.get('issue_number') != number
                or record.get('host_alias') != runner.host or record.get('execution_mode') != 'native'
                or source['native_root'] is not None or source['decision_context'] is not None):
            raise OperationDenied('decision_binding_mismatch')
        _waiting(record, context)
        _current_policy(runner, reader, repository, number, record, context.key[0])
        return source


def publish(controller, repository, number, context, request_id, *, binding, cancel):
    runner, refs, source, handle = controller.runner, {}, None, None
    scope = effect_scope(context)
    reader = runner.github.read_client()
    known = {'context': None, 'receipt': None}

    def observe():
        public = read_delegated_public_decision(reader, repository, number, context,
            known_context_id=known['context'], known_receipt_id=known['receipt'])
        if public.status in {'context', 'pair'}:
            for kind, identifier in (('context', public.context_id), ('receipt', public.receipt_id)):
                if identifier is not None:
                    if known[kind] is None:
                        known[kind] = identifier
                    refs.setdefault(kind, {'source': 'github', 'kind': 'issue_comment',
                                           'id': repository + '/comments/' + str(known[kind])})
        return public

    def result(outcome, reason, receipt=None):
        return DecisionEffectResult(outcome, reason, receipt, source, tuple(copy.deepcopy(list(refs.values()))))

    try:
        if (runner._checkpoint_ceiling.get() is not None or runner._verification_scope.get() is not None
                or runner._continuation_scope.get() is not None):
            raise OperationDenied('effect_not_allowed')
        with coordinator_lock(controller.lock_path, decision_scopes=frozenset({('publication', scope)})), \
                operation_scope(runner.operations, repository), reader.read_budget(seconds=90, requests=256):
            try:
                source = _target(controller, repository, number, context)
                public = observe()
                if public.status not in {'not_observed', 'context', 'pair'}:
                    return result('waiting', public.reason)
                handle = claim_decision_owner('publication', scope, request_id)
                for kind in ('context', 'receipt'):
                    if public.status == 'pair':
                        break
                    if kind == 'context' and public.status == 'context':
                        continue
                    if kind == 'receipt' and public.status != 'context':
                        return result('unknown', 'decision_post_unknown')
                    if cancel.is_set():
                        raise OperationDenied('decision_cancelled')
                    source = _target(controller, repository, number, context)
                    # Reconcile before every dispatch, including a fresh invocation.
                    public = observe()
                    if public.status == 'pair' or kind == 'context' and public.status == 'context':
                        continue
                    expected = 'not_observed' if kind == 'context' else 'context'
                    if public.status != expected:
                        return result('waiting', public.reason)
                    _, control, _ = binding.validate()
                    body = context.body if kind == 'context' else delegated_receipt_body(context)
                    with control.guard(repository, expected_revision=binding.command['expected']['admission_revision']):
                        if cancel.is_set():
                            raise OperationDenied('decision_cancelled')
                        spend_publication(handle, kind)
                        try:
                            reader.api('POST', f'/repos/{repository}/issues/{number}/comments',
                                       {'body': body.decode('utf-8')})
                        except GitHubError:
                            pass
                    public = observe()
                    if (kind == 'context' and public.status not in {'context', 'pair'}
                            or kind == 'receipt' and public.status != 'pair'):
                        return result('unknown', 'decision_post_unknown')
                if public.status != 'pair':
                    return result('unknown', 'decision_post_unknown')
                retire_decision_owner(handle)
                basis = delegated_context_basis(context)
                receipt = {'kind': 'decision', 'profile': 'codex_delegated_v1',
                    'source_attempt': context.key[2], 'round': 1,
                    'intent_ref': refs['context'], 'context_ref': refs['context'],
                    'resolved_ref': refs['receipt'], 'resume_attempt': basis['resume_attempt']}
                return result('applied', 'decision_confirmed', receipt)
            except (OperationDenied, OSError, RuntimeError, ValueError, TypeError):
                if handle is not None:
                    try:
                        retire_undispatched_decision(handle)
                    except (HostBusy, OSError):
                        pass
                raise
    except OperationDenied as exc:
        return result('waiting', exc.reason)
    except (OSError, RuntimeError, ValueError, TypeError):
        return result('unknown', 'decision_unconfirmed')


def reconcile(frame, observed, *, allow_resume):
    """Consume a public pair under the actual bounded continuation authority."""
    context, source, _ = observed
    runner, repository, number = frame.runner, frame.repository, frame.number
    continuation = runner._continuation_scope.get()
    owner = current_decision_owner()
    if owner is not None and owner[0] == 'publication':
        if owner[1] != effect_scope(context):
            raise OperationDenied('decision_effect_pending')
        handle = claim_decision_owner('publication', owner[1], str(uuid.uuid4()))
        retire_decision_owner(handle)  # observed contains an authenticated exact pair.
        owner = None
    if _consumed(source, context):
        if owner is not None:
            if owner != ('resume', effect_scope(context, source['record'], source['resource'])):
                raise OperationDenied('decision_resume_unknown')
            handle = claim_decision_owner('resume', owner[1], str(uuid.uuid4()))
            retire_decision_owner(handle)
        return source
    if not allow_resume or continuation is None:
        raise OperationDenied('decision_not_consumed')
    intended = resumed_record(source['record'], context)
    scope = effect_scope(context, intended, source['resource'])
    frame._prepare_resume('resume')
    # The original pair and full caller-pinned progress must survive policy IO.
    fresh = observe_work(runner, repository, number, source['record'])
    if fresh is None or fresh[0] != context or fresh[1] != source:
        raise OperationDenied('decision_source_changed')
    with frame._resume_guard('resume'):
        handle = claim_decision_owner('resume', scope, continuation.command['request_id'])
        if not handle.created_here:
            raise OperationDenied('decision_resume_unknown')
        resume_new(handle)
        values = {key: value for key, value in intended.items()
                  if key not in {'version', 'repository_id', 'issue_number'}}
        try:
            runner.github.record_checkpoint(repository, number, values,
                native_decision_root=delegated_decision_root(context), expected_progress_source=source)
        except GitHubError:
            pass
    reader = runner.github.read_client()
    with reader.read_budget(seconds=15, requests=64):
        actual = reader.decision_progress_source(repository, number)
        public = read_delegated_public_decision(reader, repository, number, context)
    if (actual is None or actual['record'] != intended or not _consumed(actual, context)
            or public.status != 'pair' or effect_scope(context, actual['record'], actual['resource']) != scope):
        raise OperationDenied('decision_resume_unknown')
    retire_decision_owner(handle)
    continuation.recorded(actual['record'])
    return actual
