"""Normalize explicit adopted or exact-reference inputs without granting authority.

The read adapter owns repository/commit/path identity. This parser neither accepts
a design nor interprets prose, evaluates dependencies, persists data or dispatches.
"""
from dataclasses import dataclass
import hashlib

from .work_records import (WorkRecordError, _canonical, _input_contract,
                           _json_object, _object, _require, validate_binding)


MAX_REFERENCE_BYTES = 65_536


@dataclass(frozen=True)
class InputConditions:
    document: str

    @property
    def value(self):
        return _json_object(self.document)

    @property
    def digest(self):
        return hashlib.sha256(self.document.encode('utf-8')).hexdigest()


def _contract(binding, spec_directory):
    value = validate_binding(binding, spec_directory=spec_directory).value
    issue = {key: value[key] for key in ('repository_id', 'issue_number')}
    _require(value['input_contract'] is not None, 'accepted_meaning_unavailable')
    return value['input_contract'], issue


def input_reference(binding, *, spec_directory):
    """Return the explicit validated reference, or None for adopted conditions."""
    contract, _ = _contract(binding, spec_directory)
    return contract['ref'] if contract['kind'] == 'reference' else None


def _heading_text(token):
    return ''.join(child.content if child.type in {'text', 'code_inline'}
                   else ' ' if child.type in {'softbreak', 'hardbreak'} else ''
                   for child in (token.children or [])).strip()


def _reference_payload(content, selector):
    _require(type(content) is str, 'invalid_reference')
    try:
        size = len(content.encode('utf-8'))
    except UnicodeError as exc:
        raise WorkRecordError('invalid_reference') from exc
    _require(size <= MAX_REFERENCE_BYTES, 'reference_limit')
    _require('\x00' not in content, 'invalid_reference')
    # Parse syntax only. Never render, fetch links or load document extensions.
    from markdown_it import MarkdownIt
    try:
        tokens = MarkdownIt('commonmark').parse(content)
    except (ValueError, RecursionError) as exc:
        raise WorkRecordError('invalid_reference') from exc
    headings = [(i, int(token.tag[1:]), _heading_text(tokens[i + 1]))
                for i, token in enumerate(tokens)
                if token.type == 'heading_open' and token.level == 0]
    selected = [(i, level) for i, level, title in headings if title == selector
                or title.split(maxsplit=1)[:1] in ([selector], [selector + ':'])]
    _require(bool(selected), 'accepted_meaning_unavailable')
    _require(len(selected) == 1, 'invalid_reference')
    start, depth = selected[0]
    end = next((i for i, level, _ in headings if i > start and level <= depth), len(tokens))
    candidates = []
    for i in range(start + 3, end):
        token = tokens[i]
        if token.type == 'fence':
            if token.level != 0:
                continue
            language = token.info.split(maxsplit=1)[:1]
            if language and language[0].lower() not in {'json', 'application/json'}:
                if token.content.lstrip().startswith('{'):
                    candidates.append(None)
                continue
            if language or token.content.lstrip().startswith('{'):
                candidates.append(token.content)
        elif (token.type == 'code_block' and token.level == 0) or (
                token.type == 'inline' and tokens[i - 1].type == 'paragraph_open'
                and tokens[i - 1].level == 0):
            if token.content.lstrip().startswith('{'):
                candidates.append(token.content)
    _require(bool(candidates), 'accepted_meaning_unavailable')
    _require(len(candidates) == 1, 'invalid_reference')
    _require(candidates[0] is not None, 'accepted_meaning_unavailable')
    return _json_object(candidates[0])


def input_conditions(binding, *, spec_directory, content=None):
    """Resolve one fixed input payload; supplied content must be the exact read.

    Supported reference sections use a unique top-level CommonMark heading's
    literal title or leading requirement ID, and one standalone JSON object.
    Unsupported/missing meaning stays unavailable; adopted prose is never inferred.
    The returned canonical payload does not establish acceptance or delegation.
    """
    contract, issue = _contract(binding, spec_directory)
    if contract['kind'] == 'adopted':
        payload = {'clauses': contract['clauses']}
    else:
        _require(content is not None, 'accepted_meaning_unavailable')
        payload = _reference_payload(content, contract['ref']['selector'])
    _object(payload, {'clauses'})
    _input_contract({'kind': 'adopted', **payload}, issue)
    return InputConditions(_canonical(payload))
