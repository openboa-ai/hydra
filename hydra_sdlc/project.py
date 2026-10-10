"""Protected project contracts, non-executable intake, and delivery evidence gates."""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from pathlib import PurePosixPath


class ProjectError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ProjectError(message)


def _sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value))


def _path(value, *, glob=False):
    return (isinstance(value, str) and bool(value) and not value.startswith(("/", "~"))
            and "\\" not in value and all(p not in {"", ".", "..", ".git"} for p in value.rstrip("/").split("/"))
            and not any(ord(c) < 32 for c in value) and (glob or not any(c in value for c in "*?[]")))


def matches(path, patterns):
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") if p.endswith("/") else fnmatch.fnmatchcase(path, p) for p in patterns)


def load_project(github, repo):
    identity = github.repository(repo)
    revision = github.ref(repo, identity["default_branch"])
    _require(_sha(revision), "Default branch revision unavailable")
    blob = github.file(repo, ".hydra.toml", revision)
    try:
        config = tomllib.loads(blob["content"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ProjectError("Invalid project TOML") from exc
    keys = {"version", "repository_id", "authorized_actors", "human_reviewers", "spec_directory", "allowed_paths", "protected_paths", "labels", "verification", "required_checks", "review_provider", "delivery", "ui_paths"}
    _require(not set(config) - keys, "Unknown project configuration fields")
    _require(config.get("version") == 1 and type(config.get("version")) is int, "Unknown project version")
    _require(type(config.get("repository_id")) is int and config["repository_id"] == identity["id"], "Repository identity mismatch")
    for name in ["authorized_actors", "human_reviewers"]:
        values = config.get(name)
        _require(isinstance(values, list) and values and all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_-]+", x) for x in values), f"Missing {name}")
    _require("openboa" not in config["human_reviewers"], "Publishing identity cannot provide human approval")
    _require(_path(config.get("spec_directory")), "Invalid spec directory")
    for name in ["allowed_paths", "protected_paths"]:
        values = config.get(name)
        _require(isinstance(values, list) and values and all(_path(x, glob=True) for x in values), f"Invalid {name}")
    ui_paths = config.setdefault("ui_paths", [])
    _require(isinstance(ui_paths, list) and all(_path(p, glob=True) for p in ui_paths), "Invalid UI path policy")
    labels = config.get("labels")
    _require(isinstance(labels, dict) and set(labels) == {"ready", "paused", "decision"} and all(isinstance(x, str) and x.strip() and len(x) < 100 for x in labels.values()) and len(set(labels.values())) == 3, "Invalid intake labels")
    commands = config.get("verification")
    _require(isinstance(commands, list) and commands, "Verification policy is empty")
    for command in commands:
        _require(isinstance(command, dict) and set(command) == {"argv", "cwd", "timeout"}, "Unknown verification command fields")
        _require(isinstance(command["argv"], list) and command["argv"] and all(isinstance(x, str) and x and "\x00" not in x for x in command["argv"]), "Verification argv required")
        _require(command["cwd"] == "." or _path(command["cwd"]), "Verification cwd must be relative")
        _require(type(command["timeout"]) is int and 1 <= command["timeout"] <= 3600, "Verification timeout out of bounds")
    bindings = config.get("required_checks")
    _require(isinstance(bindings, list) and bindings, "Required check policy is empty")
    for binding in bindings:
        _require(isinstance(binding, dict) and not set(binding) - {"workflow_id", "workflow_path", "job", "events", "app_id", "reusable_workflow", "reusable_sha"}, "Unknown check binding fields")
        _require(type(binding.get("workflow_id")) is int and binding["workflow_id"] > 0 and binding.get("app_id") == 15368, "Workflow and Actions identity required")
        _require(_path(binding.get("workflow_path")) and binding["workflow_path"].startswith(".github/workflows/"), "Invalid workflow path")
        _require(isinstance(binding.get("job"), str) and binding["job"], "Required job missing")
        _require(isinstance(binding.get("events"), list) and binding["events"] and all(isinstance(x, str) for x in binding["events"]) and set(binding["events"]) <= {"pull_request", "pull_request_target", "push"}, "Unknown check event")
        _require(any(x in binding["events"] for x in ["pull_request", "pull_request_target"]) and "push" in binding["events"], "PR and post-merge push bindings required")
        if "reusable_workflow" in binding or "reusable_sha" in binding:
            _require(_sha(binding.get("reusable_sha")) and isinstance(binding.get("reusable_workflow"), str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/[^/]+\.ya?ml", binding["reusable_workflow"]), "Reusable workflow must have exact identity and revision")
    _require(len({(b["workflow_id"], b["job"]) for b in bindings}) == len(bindings), "Duplicate check binding")
    provider = config.get("review_provider")
    _require(isinstance(provider, dict) and set(provider) == {"login", "user_id", "app_id", "format"}, "Review provider identity incomplete")
    _require(provider["format"] == "codex_summary_v1" and provider["login"] == "chatgpt-codex-connector[bot]" and type(provider["user_id"]) is int and provider["user_id"] > 0 and type(provider["app_id"]) is int and provider["app_id"] > 0, "Unknown review provider")
    delivery = config.get("delivery", {})
    _require(isinstance(delivery, dict) and not set(delivery) - {"automatic_merge", "production_effect"} and all(type(x) is bool for x in delivery.values()), "Invalid delivery policy")
    config["delivery"] = {"automatic_merge": False, "production_effect": True, **delivery}
    permissions = {}
    for actor in config["authorized_actors"]:
        access = github.api("GET", f"/repos/{repo}/collaborators/{actor}/permission")
        _require(isinstance(access, dict) and (access.get("user") or {}).get("login") == actor and access.get("permission") in {"admin", "write", "maintain"}, "Authorized intake actor is not a repository writer")
        permissions[actor] = access["permission"]
    return {**config, "repository": repo, "default_branch": identity["default_branch"], "revision": revision, "blob_sha": blob["sha"], "actor_permissions": permissions}


def parse_intake(issue, config):
    _require(isinstance(issue, dict) and "pull_request" not in issue and type(issue.get("number")) is int, "Expected a product Issue")
    _require(issue.get("state") == "open", "Issue is closed")
    _require((issue.get("user") or {}).get("login") in config["authorized_actors"] and config.get("actor_permissions", {}).get((issue.get("user") or {}).get("login")) in {"admin", "write", "maintain"}, "Issue author is not an authorized repository writer")
    labels = {x.get("name") if isinstance(x, dict) else x for x in issue.get("labels", [])}
    policy = config["labels"]
    _require(policy["ready"] in labels and not labels.intersection({policy["paused"], policy["decision"]}), "Issue is not ready")
    body = issue.get("body") or ""
    _require(isinstance(issue.get("title"), str) and issue["title"].strip(), "Issue goal title missing")
    blocks = re.findall(r"(?m)^```hydra\s*\n(.*?)^```\s*$", body, re.S)
    _require(len(blocks) == 1, "Exactly one hydra intake block required")
    try:
        intake = tomllib.loads(blocks[0])
    except ValueError as exc:
        raise ProjectError("Invalid intake TOML") from exc
    _require(not set(intake) - {"spec", "spec_revision", "dependencies", "priority"}, "Issue cannot supply execution policy")
    spec = intake.get("spec")
    _require(_path(spec) and spec.startswith(config["spec_directory"].rstrip("/") + "/") and PurePosixPath(spec).name == "spec.md", "Spec must be in the registered directory")
    _require(intake.get("spec_revision") is None or _sha(intake["spec_revision"]), "Invalid spec revision")
    dependencies = intake.get("dependencies", [])
    _require(isinstance(dependencies, list) and len(dependencies) <= 50 and all(isinstance(x, str) for x in dependencies) and len(set(dependencies)) == len(dependencies) and all(isinstance(x, str) and re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*", x) for x in dependencies), "Invalid dependencies")
    _require(f"https://github.com/{config['repository']}/issues/{issue['number']}" not in dependencies, "Issue cannot depend on itself")
    priority = intake.get("priority", 0)
    _require(type(priority) is int and -1000 <= priority <= 1000, "Invalid priority")
    public = re.sub(r"(?ms)^```.*?^```\s*$", "", body)
    for heading in ["Goal", "Scope", "Acceptance"]:
        match = re.search(r"(?ims)^#{1,6}\s+" + heading + r"\s*\n(.*?)(?=^#{1,6}\s|\Z)", public)
        _require(match is not None and bool(match[1].strip()), f"Public {heading.lower()} is missing")
    # A revision identifies content. Independent acceptance must still be observed
    # by the runner; Issue metadata is never its own acceptance receipt.
    return {"issue_number": issue["number"], "spec": spec, "spec_revision": intake.get("spec_revision"), "dependencies": dependencies, "priority": priority}


def _checks(config, observation, sha, *, post_merge):
    blockers = []
    runs, checks = observation.get("runs"), observation.get("checks")
    if not isinstance(runs, list) or not isinstance(checks, list):
        return ["checks_unobserved"]
    raw = observation.get("pr", {})
    for binding in config["required_checks"]:
        label = binding["job"]
        candidates = []
        for run in runs:
            if run.get("workflow_id") != binding["workflow_id"] or run.get("path") != binding["workflow_path"] or run.get("repository", {}).get("id", run.get("repository_id")) != config["repository_id"]:
                continue
            event = run.get("event")
            if event not in binding["events"] or (event == "push") != post_merge:
                continue
            if run.get("head_sha") != sha:
                continue
            if post_merge:
                if run.get("head_branch") != config["default_branch"]:
                    continue
            else:
                if (run.get("head_branch") != raw.get("head", {}).get("ref")
                        or raw.get("head", {}).get("sha") != sha
                        or raw.get("head", {}).get("repo", {}).get("id") != config["repository_id"]
                        or raw.get("base", {}).get("repo", {}).get("id") != config["repository_id"]):
                    continue
                associations = run.get("pull_requests")
                if associations == [] and event == "pull_request_target":
                    # GitHub's observed target-event producer exposes the candidate
                    # head/branch but no PR association. Only a contract-pinned
                    # reusable producer can attest that event's exact candidate.
                    if not _sha(binding.get("reusable_sha")) or not binding.get("reusable_workflow"):
                        continue
                elif not isinstance(associations, list) or len(associations) != 1:
                    continue
                elif not all((associations[0].get("number") == raw.get("number"),
                              associations[0].get("head", {}).get("sha") == sha,
                              associations[0].get("base", {}).get("sha") == observation.get("base_sha"),
                              associations[0].get("head", {}).get("repo", {}).get("id") == config["repository_id"],
                              associations[0].get("base", {}).get("repo", {}).get("id") == config["repository_id"])):
                    continue
            candidates.append(run)
        if not candidates:
            blockers.append(f"check_identity_missing:{label}")
            continue
        run = max(candidates, key=lambda r: (r.get("run_number", 0), r.get("run_attempt", 0), r.get("id", 0)))
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            blockers.append(f"check_not_successful:{label}")
            continue
        if "reusable_sha" in binding:
            expected = {"path": binding["reusable_workflow"] + "@" + binding["reusable_sha"], "sha": binding["reusable_sha"]}
            if not any(all(x.get(k) == v for k, v in expected.items()) for x in run.get("referenced_workflows", [])):
                blockers.append(f"check_reusable_identity_missing:{label}")
                continue
        jobs = [j for j in run.get("jobs", []) if j.get("name") == label]
        if len(jobs) != 1 or jobs[0].get("status") != "completed" or jobs[0].get("conclusion") != "success" or jobs[0].get("head_sha") != run["head_sha"]:
            blockers.append(f"check_job_not_successful:{label}")
            continue
        if jobs[0].get("check_run_url") != f"https://api.github.com/repos/{config['repository']}/check-runs/{jobs[0].get('id')}":
            blockers.append(f"check_job_link_missing:{label}")
            continue
        matching = [c for c in checks if c.get("id") == jobs[0].get("id") and c.get("check_suite", {}).get("id") == run.get("check_suite_id") and c.get("app", {}).get("id") == binding["app_id"] and c.get("head_sha") == run["head_sha"] and c.get("name") == label and c.get("status") == "completed" and c.get("conclusion") == "success"]
        if len(matching) != 1:
            blockers.append(f"check_publisher_missing:{label}")
    return blockers


def gate_checks(config, observation, sha, *, events=None):
    """Check bound PR evidence, or exact default-branch push with events=['push']."""
    if not _sha(sha) or events not in (None, ["push"]):
        return ["check_target_unknown"]
    return _checks(config, observation, sha, post_merge=events == ["push"])


def _provider(config, observation, head):
    provider = config["review_provider"]
    if provider.get("format") != "codex_summary_v1":
        return ["provider_format_unknown"]
    comments = observation.get("provider_comments")
    commits = observation.get("commits")
    raw = observation["pr"]
    if not isinstance(comments, list) or not isinstance(commits, list) or raw.get("commits") != len(commits) or not commits or not all(_sha(c.get("sha")) for c in commits):
        return ["provider_evidence_incomplete"]
    own = [c for c in comments if (c.get("user") or {}).get("id") == provider["user_id"] and (c.get("user") or {}).get("login") == provider["login"] and (c.get("performed_via_github_app") or {}).get("id") == provider["app_id"]]
    summaries = [c for c in own if "<!-- codex-pull-request-review-summary -->" in (c.get("body") or "")]
    if len(summaries) != 1:
        return ["provider_summary_missing_or_ambiguous"]
    body = summaries[0].get("body", "")
    markers = re.findall(r"<!-- codex-security-review:v1 (.*?) -->", body, re.S)
    try:
        if len(markers) != 1:
            raise ValueError()
        marker = json.loads(markers[0])
    except ValueError:
        return ["provider_format_unknown"]
    if not isinstance(marker, dict) or marker.get("repository") != config["repository"] or marker.get("pullRequestNumber") != raw.get("number") or marker.get("headSha") != head or marker.get("status") != "completed":
        return ["provider_head_or_completion_missing"]
    for name in ["Code Review", "Security Review"]:
        rows = [line for line in body.splitlines() if line.startswith("|") and f"**{name}**" in line]
        if len(rows) != 1:
            return ["provider_format_unknown"]
        cells = rows[0].split("|")
        if len(cells) != 6 or not re.fullmatch(r"\s*✅ \*\*Completed\*\*(?: <relative-time datetime=\"[^\"]+\">[^<]+</relative-time>)?\s*", cells[2]):
            return ["provider_review_not_completed"]
        match = re.fullmatch(r"\s*`([0-9a-f]{7,40})`\s*", cells[3])
        if not match:
            return ["provider_format_unknown"]
        resolved = {c["sha"] for c in commits if c["sha"].startswith(match[1])}
        if resolved != {head}:
            return ["provider_revision_ambiguous_or_stale"]
    # Security findings may be issue comments rather than review threads. No
    # free-text claim of resolution is accepted for such an unknown finding form.
    if len(own) != 1:
        return ["provider_additional_comments_require_resolution"]
    if not isinstance(observation.get("inline_comments"), list):
        return ["provider_inline_comments_unobserved"]
    covered = {c.get("databaseId") for t in observation.get("threads", []) if t.get("isResolved") is True for c in t.get("comments", {}).get("nodes", [])}
    if any(c.get("id") not in covered for c in observation["inline_comments"]):
        return ["review_comment_resolution_unobserved"]
    return []


def gate_delivery(config, observation, head, paths):
    blockers = []
    if not config["delivery"]["automatic_merge"]:
        blockers.append("automatic_merge_disabled")
    if config["delivery"]["production_effect"]:
        blockers.append("production_effect_requires_decision")
    pr = observation.get("pr", {})
    if observation.get("repository", {}).get("id") != config["repository_id"] or observation.get("head_sha") != head or pr.get("head", {}).get("sha") != head or not _sha(head):
        blockers.append("head_or_repository_changed")
    if observation.get("base_sha") != config["revision"] or pr.get("base", {}).get("sha") != observation.get("base_sha") or pr.get("base", {}).get("ref") != config["default_branch"]:
        blockers.append("base_or_contract_changed")
    if pr.get("state") != "open" or pr.get("draft") is not False or pr.get("mergeable") is not True or pr.get("mergeable_state") != "clean":
        blockers.append("native_merge_not_ready")
    if pr.get("head", {}).get("repo", {}).get("id") != config["repository_id"] or pr.get("base", {}).get("repo", {}).get("id") != config["repository_id"]:
        blockers.append("foreign_repository_pr")
    if not isinstance(paths, list) or not paths or not all(_path(p) for p in paths):
        blockers.append("changed_paths_unknown")
        paths = []
    actual_files = observation.get("changed_files")
    if not isinstance(actual_files, list) or pr.get("changed_files") != len(actual_files):
        blockers.append("changed_paths_incomplete")
    else:
        actual_paths = {p for f in actual_files for p in [f.get("filename"), f.get("previous_filename")] if p}
        if set(paths) != actual_paths:
            blockers.append("changed_paths_mismatch")
    if any(not matches(p, config["allowed_paths"]) for p in paths):
        blockers.append("outside_allowed_paths")
    rules = observation.get("rules", [])
    sources = observation.get("rule_sources", [])
    if not sources or any(s.get("enforcement") != "active" or s.get("bypass_actors") != [] for s in sources):
        blockers.append("native_protection_not_strict")
    by_type = {}
    for r in rules:
        by_type.setdefault(r.get("type"), []).append(r.get("parameters", {}))
    native_checks = by_type.get("required_status_checks", [])
    if not native_checks or not all(c.get("strict_required_status_checks_policy") is True for c in native_checks):
        blockers.append("strict_integration_missing")
    expected = {(x["job"], x["app_id"]) for x in config["required_checks"]}
    observed = {(x.get("context"), x.get("integration_id")) for c in native_checks for x in c.get("required_status_checks", [])}
    if expected != observed:
        blockers.append("required_check_policy_mismatch")
    pull_rules = by_type.get("pull_request", [])
    if not pull_rules or not all(p.get("dismiss_stale_reviews_on_push") is True and p.get("require_code_owner_review") is True and p.get("required_review_thread_resolution") is True for p in pull_rules) or "non_fast_forward" not in by_type:
        blockers.append("native_review_policy_missing")
    threads, reviews = observation.get("threads"), observation.get("native_reviews")
    if not isinstance(threads, list) or any(t.get("isResolved") is not True for t in threads):
        blockers.append("review_threads_unresolved_or_unknown")
    if not isinstance(reviews, list):
        blockers.append("native_reviews_unobserved")
        reviews = []
    latest = {}
    for review in sorted(reviews, key=lambda r: (r.get("submitted_at") or "", r.get("id", 0))):
        if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            login = (review.get("user") or {}).get("login")
            if not isinstance(login, str) or not login:
                blockers.append("native_review_author_unknown")
                continue
            latest[login] = review
    if any(r.get("state") == "CHANGES_REQUESTED" for r in latest.values()) or observation.get("review_decision") not in {"APPROVED", None}:
        blockers.append("native_review_not_approved")
    protected = [".hydra.toml", ".github/", "AGENTS.md", "SECURITY.md", "CODEOWNERS", "docs/CODEOWNERS"] + config["protected_paths"]
    if any(matches(p, protected) for p in paths):
        humans = [r for login, r in latest.items() if login in config["human_reviewers"] and login != (pr.get("user") or {}).get("login") and (r.get("user") or {}).get("type") == "User" and r.get("state") == "APPROVED" and r.get("commit_id") == head]
        if not humans or observation.get("review_decision") != "APPROVED":
            blockers.append("protected_change_needs_current_human_review")
    required_count = max((p.get("required_approving_review_count", 0) for p in pull_rules), default=0)
    if len([r for r in latest.values() if r.get("state") == "APPROVED" and r.get("commit_id") == head]) < required_count:
        blockers.append("native_approval_count_missing")
    blockers.extend(gate_checks(config, observation, head))
    if "pr" not in observation:
        blockers.append("provider_evidence_incomplete")
    else:
        blockers.extend(_provider(config, observation, head))
    return list(dict.fromkeys(blockers))


def gate_post_merge(config, observation, merge_sha):
    pr = observation.get("pr", {})
    blockers = []
    if pr.get("merged") is not True or pr.get("merge_commit_sha") != merge_sha or observation.get("repository", {}).get("id") != config["repository_id"]:
        blockers.append("merge_not_observed")
    blockers.extend(gate_checks(config, observation, merge_sha, events=["push"]))
    return list(dict.fromkeys(blockers))
