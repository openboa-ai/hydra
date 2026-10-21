"""Exact public decision evidence; observations confer no execution authority.

The caller obtains a public-safe proposal from its qualified source. This module
does not certify free text as safe, publish comments, accept an answer, or resume
work. An empty observation never proves that a previous POST was not dispatched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
import uuid

from .github import GitHubError, _number, _repo

MAX_CONTEXT_BYTES = 16 * 1024
MAX_INTEGER = 9_007_199_254_740_991
_PHASES = {"design", "implementation", "correction", "spec_review", "change_review"}
_KEY_FIELDS = {"repository_id", "issue_number", "source_attempt", "round"}
_BASIS_FIELDS = {"key", "resume_attempt", "origin_phase", "head", "contract_revision",
                 "spec_revision", "intake_digest", "supersedes"}
_INTENT = "<!-- hydra-decision-intent:v1 "
_RECEIPT = "<!-- hydra-decision-receipt:v1 "


class InvalidPublicDecision(ValueError):
    """Invalid data, with no remote content in the diagnostic."""


def _invalid():
    raise InvalidPublicDecision("Invalid public decision evidence")


def _positive(value):
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        _invalid()
    return value


def _uuid(value):
    if not isinstance(value, str):
        _invalid()
    try:
        if str(uuid.UUID(value)) != value:
            _invalid()
    except (ValueError, AttributeError):
        _invalid()
    return value


def _hex(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % size, value):
        _invalid()
    return value


def _object(value, fields):
    if type(value) is not dict or set(value) != fields:
        _invalid()


def _key(value):
    _object(value, _KEY_FIELDS)
    return (_positive(value["repository_id"]), _positive(value["issue_number"]),
            _uuid(value["source_attempt"]), _positive(value["round"]))


def _key_json(key):
    return dict(zip(("repository_id", "issue_number", "source_attempt", "round"), key))


def _pin(value):
    _object(value, {"key", "context_sha256"})
    return _key(value["key"]), _hex(value["context_sha256"], 64)


def _basis(value):
    _object(value, _BASIS_FIELDS)
    key = _key(value["key"])
    if _uuid(value["resume_attempt"]) == key[2]:
        _invalid()
    if not isinstance(value["origin_phase"], str) or value["origin_phase"] not in _PHASES:
        _invalid()
    for field in ("head", "contract_revision"):
        _hex(value[field], 40)
    if value["spec_revision"] is not None:
        _hex(value["spec_revision"], 40)
    _hex(value["intake_digest"], 64)
    if key[3] > 1 and value["supersedes"] is None:
        _invalid()
    if value["supersedes"] is not None:
        previous, _ = _pin(value["supersedes"])
        if previous[:3] != key[:3] or previous[3] != key[3] - 1:
            _invalid()
    return key


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _load(value):
    try:
        return json.loads(value, object_pairs_hook=_unique)
    except (ValueError, TypeError, RecursionError):
        _invalid()


def _wire(body):
    try:
        if isinstance(body, str) and len(body) > MAX_CONTEXT_BYTES:
            _invalid()
        raw = body.encode("utf-8") if isinstance(body, str) else body
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_CONTEXT_BYTES:
            _invalid()
        text = raw.decode("utf-8")
    except UnicodeError:
        _invalid()
    if "\r" in text or not text.endswith("\n") or text.endswith("\n\n"):
        _invalid()
    return raw, text


@dataclass(frozen=True, repr=False)
class PublicContext:
    body: bytes
    key: tuple[int, int, str, int]

    @property
    def sha256(self):
        return hashlib.sha256(self.body).hexdigest()


def prepare_context(public_text, basis):
    """Prepare canonical bytes once; never truncate or change a read-back body."""
    key = _basis(basis)
    if not isinstance(public_text, str):
        _invalid()
    public_text = public_text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not public_text.strip() or "<!-- hydra-decision-" in public_text:
        _invalid()
    try:
        body = (f"hydra: decision {key[2]} context\n{public_text}\n"
                + _INTENT + _json(basis) + " -->\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _invalid()
    return parse_context(body)


def parse_context(body):
    raw, text = _wire(body)
    lines = text.split("\n")
    if len(lines) < 4 or not lines[-2].startswith(_INTENT) or not lines[-2].endswith(" -->"):
        _invalid()
    public_text = "\n".join(lines[1:-2])
    if not public_text.strip() or "<!-- hydra-decision-" in public_text:
        _invalid()
    metadata = lines[-2][len(_INTENT):-4]
    basis = _load(metadata)
    key = _basis(basis)
    if lines[0] != f"hydra: decision {key[2]} context" or metadata != _json(basis):
        _invalid()
    return PublicContext(raw, key)


def receipt_body(context):
    context = parse_context(context.body)
    pin = {"key": _key_json(context.key), "context_sha256": context.sha256}
    return (f"hydra: decision {context.key[2]} resolved\n" + _RECEIPT + _json(pin)
            + " -->\n").encode("utf-8")


def parse_receipt(body):
    _, text = _wire(body)
    lines = text.split("\n")
    if len(lines) != 3 or not lines[1].startswith(_RECEIPT) or not lines[1].endswith(" -->"):
        _invalid()
    metadata = lines[1][len(_RECEIPT):-4]
    pin = _load(metadata)
    key, digest = _pin(pin)
    if lines[0] != f"hydra: decision {key[2]} resolved" or metadata != _json(pin):
        _invalid()
    return key, digest


@dataclass(frozen=True)
class DecisionObservation:
    status: str
    reason: str
    context_id: int | None = None
    receipt_id: int | None = None
    ignored_outsiders: int = 0


def _identity(actor):
    if (not isinstance(actor, dict) or not isinstance(actor.get("login"), str)
            or not actor["login"]):
        _invalid()
    return _positive(actor.get("id")), actor["login"]


def _unedited(row):
    try:
        created, updated = (datetime.fromisoformat(row[field].replace("Z", "+00:00"))
                            for field in ("created_at", "updated_at"))
        return created.tzinfo is not None and updated.tzinfo is not None and created == updated
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def _claims_decision_key(body, expected_key):
    """Recognize relevant or unreadable versioned claims without trusting headers."""
    position = 0
    while True:
        markers = [(body.find(marker, position), marker) for marker in (_INTENT, _RECEIPT)]
        markers = [(start, marker) for start, marker in markers if start >= 0]
        if not markers:
            return False
        start, marker = min(markers)
        end = body.find(" -->", start + len(marker))
        if end < 0 or end - start - len(marker) > MAX_CONTEXT_BYTES:
            return True
        try:
            fragment = body[start + len(marker):end]
            if len(fragment.encode("utf-8")) > MAX_CONTEXT_BYTES:
                _invalid()
            payload = _load(fragment)
            if type(payload) is not dict:
                _invalid()
            key = _key(payload.get("key"))
        except (InvalidPublicDecision, UnicodeError):
            return True
        if key == expected_key:
            return True
        position = end + 4


def observe_comments(rows, service_identity, expected_context, *, coverage_complete):
    """Fold exact service-owned duplicates, without accepting a private decision."""
    expected = parse_context(expected_context.body)
    if coverage_complete is not True or not isinstance(rows, list):
        return DecisionObservation("unknown", "incomplete_coverage")
    try:
        service = _identity(service_identity)
    except InvalidPublicDecision:
        return DecisionObservation("unknown", "service_identity_unavailable")
    contexts, receipts, seen, ignored = [], [], {}, 0
    expected_receipt = receipt_body(expected)
    prefix = f"hydra: decision {expected.key[2]} "
    for row in rows:
        if not isinstance(row, dict):
            return DecisionObservation("unknown", "incomplete_comment")
        try:
            actor = _identity(row.get("user"))
        except InvalidPublicDecision:
            if (isinstance(row.get("body"), str) and not row["body"].startswith(prefix)
                    and not _claims_decision_key(row["body"], expected.key)):
                continue
            return DecisionObservation("unknown", "comment_actor_unavailable")
        if actor != service:
            if isinstance(row.get("body"), str) and row["body"].startswith(prefix):
                ignored += 1
            continue
        body = row.get("body")
        if not isinstance(body, str):
            return DecisionObservation("unknown", "incomplete_comment")
        if ((not body.startswith(prefix) and not _claims_decision_key(body, expected.key))
                or body in (prefix + "resolved", prefix + "resolved\n")):
            continue  # A legacy one-line receipt is not a versioned receipt.
        try:
            comment_id = _positive(row.get("id"))
            raw, _ = _wire(body)
            if raw.startswith((prefix + "context\n").encode()):
                key, kind = parse_context(raw).key, "context"
            else:
                key, _ = parse_receipt(raw)
                kind = "receipt"
        except InvalidPublicDecision:
            return DecisionObservation("unknown", "invalid_service_record")
        if key != expected.key:
            continue
        if not _unedited(row) or comment_id in seen and seen[comment_id] != raw:
            return DecisionObservation("unknown", "changed_service_record")
        seen[comment_id] = raw
        wanted = expected.body if kind == "context" else expected_receipt
        if raw != wanted:
            return DecisionObservation("conflict", "different_service_payload")
        (contexts if kind == "context" else receipts).append(comment_id)
    context_id = min(contexts) if contexts else None
    receipt_id = min(receipts) if receipts else None
    status = ("pair" if contexts and receipts else "context" if contexts else
              "receipt_without_context" if receipts else "not_observed")
    return DecisionObservation(status, "public_observation_only", context_id, receipt_id, ignored)


def read_public_decision(github, repo, issue_number, expected_context, *,
                         known_context_id=None, known_receipt_id=None):
    """Bounded authenticated collection plus direct ref read-back; GET only.

    Known refs are required when recovering a previously observed pair. Without
    them this observation cannot establish whether a historical ref was deleted.
    None of the returned statuses authorizes a POST, PATCH, or continuation.
    """
    expected = parse_context(expected_context.body)
    _repo(repo)
    if ".." in repo or "." in repo.split("/"):
        _invalid()
    _number(issue_number)
    if issue_number != expected.key[1]:
        _invalid()
    for reference in (known_context_id, known_receipt_id):
        if reference is not None:
            _positive(reference)
    try:
        with github.read_budget(seconds=30, requests=32):
            identity = github._identity()
            service = _identity(identity)
            repository = github.repository(repo)
            if repository["id"] != expected.key[0]:
                return DecisionObservation("unknown", "repository_identity_changed")
            canonical = _repo(repository["full_name"])
            github.issue(canonical, issue_number)
            rows = github.comments(canonical, issue_number)
            observation = observe_comments(rows, identity, expected, coverage_complete=True)
            if observation.status in {"unknown", "conflict"}:
                return observation
            context_refs = {value for value in (observation.context_id, known_context_id) if value is not None}
            receipt_refs = {value for value in (observation.receipt_id, known_receipt_id) if value is not None}
            if context_refs & receipt_refs:
                return DecisionObservation("unknown", "pinned_reference_changed")
            refs = context_refs | receipt_refs
            for comment_id in sorted(refs):
                direct = github.api("GET", f"/repos/{canonical}/issues/comments/{comment_id}")
                listed = [row for row in rows if isinstance(row, dict) and row.get("id") == comment_id]
                wanted = expected.body if comment_id in context_refs else receipt_body(expected)
                if (not isinstance(direct, dict) or type(direct.get("id")) is not int
                        or direct["id"] != comment_id or _identity(direct.get("user")) != service
                        or direct.get("issue_url") != f"https://api.github.com/repos/{canonical}/issues/{issue_number}"
                        or not isinstance(direct.get("body"), str)
                        or direct["body"].encode("utf-8") != wanted or not _unedited(direct)
                        or not listed or any(row.get("body") != direct["body"]
                                             or row.get("created_at") != direct.get("created_at")
                                             or row.get("updated_at") != direct.get("updated_at")
                                             for row in listed)):
                    return DecisionObservation("unknown", "pinned_reference_changed")
            if _identity(github._identity()) != service:
                return DecisionObservation("unknown", "service_identity_changed")
            return observation
    except (GitHubError, InvalidPublicDecision, UnicodeError):
        return DecisionObservation("unknown", "source_unavailable")
