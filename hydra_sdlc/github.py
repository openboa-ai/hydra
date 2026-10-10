"""Bounded GitHub observations and service-owned writes through per-call gh auth."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import uuid
from urllib.parse import quote, urlencode

ACTIVE_LABEL = "hydra:active"
MAX_COLLECTION_BYTES = 8_000_000


class GitHubError(RuntimeError):
    def __init__(self, reason, *, status=None, uncertain=False):
        super().__init__(reason)
        self.status = status
        self.uncertain = uncertain


def _repo(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise GitHubError("Invalid repository")
    return value


def _number(value):
    if type(value) is not int or value < 1:
        raise GitHubError("Invalid issue or PR number")
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise GitHubError("Missing or invalid commit SHA")
    return value


def _marker(body, name):
    prefix = f"<!-- {name}:v1 "
    if prefix not in (body or ""):
        return None
    matches = re.findall(re.escape(prefix) + r"(.*?) -->", body, re.S)
    if len(matches) != 1 or body.count(prefix) != 1:
        raise GitHubError("Ambiguous service marker")
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate marker field")
            value[key] = item
        return value

    try:
        value = json.loads(matches[0], object_pairs_hook=unique_keys)
    except (ValueError, TypeError) as exc:
        raise GitHubError("Malformed service marker") from exc
    if not isinstance(value, dict):
        raise GitHubError("Malformed service marker")
    return value


class GitHub:
    """The injected transport has signature (method, path, payload) -> JSON value.

    Errors do not echo commands, credentials, payloads or remote diagnostics. A
    failed write is uncertain; the runner must read actual state before retrying.
    """

    def __init__(self, user="openboa", transport=None):
        if user != "openboa":
            raise GitHubError("Runtime identity must be openboa")
        self.user = user
        self.transport = transport or self._gh
        self._authenticated_fingerprint = None

    def _gh(self, method, path, payload):
        try:
            token = subprocess.run(
                ["gh", "auth", "token", "--hostname", "github.com", "--user", self.user],
                capture_output=True, text=True, timeout=15, check=True,
            ).stdout.strip()
            if not token:
                raise GitHubError("GitHub authentication unavailable")
            env = {**os.environ, "GH_TOKEN": token, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"}
            fingerprint = hashlib.sha256(token.encode()).digest()
            # Select credentials each call, but avoid doubling every polling API
            # request with the same credential's immutable account identity.
            if self._authenticated_fingerprint != fingerprint:
                identity = subprocess.run(
                    ["gh", "api", "--hostname", "github.com", "user"],
                    env=env, capture_output=True, text=True, timeout=30, check=True,
                )
                if json.loads(identity.stdout).get("login") != self.user:
                    raise GitHubError("GitHub identity mismatch")
                self._authenticated_fingerprint = fingerprint
            argv = ["gh", "api", "--hostname", "github.com", "--method", method,
                    "-H", "Accept: application/vnd.github+json", path.lstrip("/")]
            if payload is not None:
                argv += ["--input", "-"]
            result = subprocess.run(argv, input=json.dumps(payload) if payload is not None else None,
                                    env=env, capture_output=True, text=True, timeout=45)
            if result.returncode:
                match = re.search(r"HTTP (\d{3})", result.stderr)
                raise GitHubError("GitHub request failed", status=int(match[1]) if match else None,
                                  uncertain=method != "GET")
            if len(result.stdout) > 8_000_000:
                raise GitHubError("GitHub response exceeds bound", uncertain=method != "GET")
            return json.loads(result.stdout) if result.stdout.strip() else None
        except GitHubError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise GitHubError("GitHub transport unavailable", uncertain=method != "GET") from exc

    def api(self, method, path, payload=None):
        if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"} or not isinstance(path, str) or not path.startswith("/") or ".." in path or "://" in path:
            raise GitHubError("Invalid GitHub API request")
        return self.transport(method, path, payload)

    def _pages(self, path, key=None):
        result = []
        retained_bytes = 0
        for page in range(1, 101):
            data = self.api("GET", path + ("&" if "?" in path else "?") + urlencode({"per_page": 100, "page": page}))
            rows = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise GitHubError("Incomplete GitHub collection")
            try:
                retained_bytes += len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            except (ValueError, TypeError) as exc:
                raise GitHubError("Incomplete GitHub collection") from exc
            if retained_bytes > MAX_COLLECTION_BYTES:
                raise GitHubError("GitHub collection exceeds bound")
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise GitHubError("GitHub pagination exceeds bound")

    def _identity(self):
        user = self.api("GET", "/user")
        if not isinstance(user, dict) or user.get("login") != self.user or type(user.get("id")) is not int:
            raise GitHubError("GitHub identity mismatch")
        return user

    def repository(self, repo):
        data = self.api("GET", f"/repos/{_repo(repo)}")
        if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] < 1 or data.get("full_name", "").lower() != repo.lower() or not data.get("default_branch"):
            raise GitHubError("Incomplete repository identity")
        return data

    def file(self, repo, path, ref):
        _sha(ref)
        if not isinstance(path, str) or path.startswith("/") or any(x in {"", ".", ".."} for x in path.split("/")):
            raise GitHubError("Invalid repository file path")
        value = self.api("GET", f"/repos/{_repo(repo)}/contents/{quote(path, safe='/')}?ref={ref}")
        if not isinstance(value, dict) or value.get("type") != "file" or value.get("encoding") != "base64":
            raise GitHubError("Expected a regular repository file")
        try:
            content = base64.b64decode(value["content"].replace("\n", ""), validate=True).decode("utf-8")
        except (KeyError, ValueError, UnicodeError) as exc:
            raise GitHubError("Invalid repository file content") from exc
        return {"content": content, "sha": _sha(value.get("sha"))}

    def issues(self, repo):
        result = []
        prefix = f"/repos/{_repo(repo)}/issues"
        for issue in self._pages(prefix + "?state=open&sort=created&direction=asc"):
            if not isinstance(issue, dict) or issue.get("state") != "open":
                raise GitHubError("Incomplete Issue state")
            if "pull_request" not in issue:
                result.append(issue)
        for issue in self._pages(prefix + "?" + urlencode({"state": "closed", "labels": ACTIVE_LABEL,
                                                          "sort": "created", "direction": "asc"})):
            if not isinstance(issue, dict) or issue.get("state") != "closed":
                raise GitHubError("Incomplete recovery Issue state")
            if "pull_request" not in issue and ACTIVE_LABEL in self._labels(issue) and issue.get("comments") != 0:
                # A label narrows discovery; only authenticated progress admits recovery.
                record = self.progress(repo, _number(issue.get("number")))
                if record and (record.get("pending_action") == "close_issue" or record.get("phase") == "completed"):
                    result.append(issue)
        return result

    @staticmethod
    def _labels(issue):
        labels = issue.get("labels")
        if not isinstance(labels, list) or any(not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in labels):
            raise GitHubError("Incomplete Issue labels")
        return {x["name"].casefold() for x in labels}

    def _active(self, repo, n, active):
        prefix = f"/repos/{_repo(repo)}"
        present = ACTIVE_LABEL in self._labels(self.issue(repo, n))
        if present == active:
            return
        if active:
            label = prefix + "/labels/" + quote(ACTIVE_LABEL, safe="")
            try:
                self.api("GET", label)
            except GitHubError as exc:
                if exc.status != 404:
                    raise
                self.api("POST", prefix + "/labels", {"name": ACTIVE_LABEL, "color": "1d76db",
                                                       "description": "Hydra work or completion reconciliation in progress"})
            self.api("POST", f"{prefix}/issues/{n}/labels", {"labels": [ACTIVE_LABEL]})
        else:
            try:
                self.api("DELETE", f"{prefix}/issues/{n}/labels/" + quote(ACTIVE_LABEL, safe=""))
            except GitHubError as exc:
                if exc.status != 404:
                    raise
        if (ACTIVE_LABEL in self._labels(self.issue(repo, n))) != active:
            raise GitHubError("Active label result unconfirmed")

    def issue(self, repo, n):
        value = self.api("GET", f"/repos/{_repo(repo)}/issues/{_number(n)}")
        if not isinstance(value, dict) or value.get("number") != n or "pull_request" in value:
            raise GitHubError("Expected a product Issue")
        return value

    def comments(self, repo, n):
        return self._pages(f"/repos/{_repo(repo)}/issues/{_number(n)}/comments")

    def _progress_comment(self, repo, n):
        identity = self._identity()
        own = [c for c in self.comments(repo, n) if (c.get("user") or {}).get("id") == identity["id"] and (c.get("user") or {}).get("login") == identity["login"] and "<!-- hydra-progress:v1 " in (c.get("body") or "")]
        if len(own) > 1:
            raise GitHubError("Duplicate service progress comments")
        return own[0] if own else None

    def progress(self, repo, n):
        comment = self._progress_comment(repo, n)
        if comment is None:
            return None
        value = _marker(comment.get("body"), "hydra-progress")
        if value.get("repository_id") != self.repository(repo)["id"] or value.get("issue_number") != n or value.get("version") != 1:
            raise GitHubError("Progress identity mismatch")
        self._validate_record(value, metadata=True)
        return value

    @staticmethod
    def _validate_record(record, *, metadata=False):
        allowed = {"attempt_id", "host_alias", "contract_revision", "spec_revision", "phase", "branch", "head", "published_head", "pr_number", "pending_action", "pending_thread", "checkpoint", "wait_reason", "next_action", "expected_head", "expected_base", "action_attempt", "review_requested_head", "delivery_action", "delivery_attempt", "delivery_head", "review_requested_security_head", "pending_review_kind", "intake_digest", "correction_reason", "correction_attempt", "resume_phase"}
        if metadata:
            allowed |= {"repository_id", "issue_number", "version"}
        allowed |= {"execution_mode", "native_step", "native_phase", "native_head", "native_outcome", "native_spec_digest", "native_origin_phase", "native_resume_phase", "native_correction"}
        if not isinstance(record, dict) or set(record) - allowed:
            raise GitHubError("Unknown progress fields")
        for key, value in record.items():
            if value is None:
                continue
            if key in {"intake_digest", "native_spec_digest"}:
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise GitHubError("Invalid delegated intake digest")
            elif key in {"contract_revision", "spec_revision", "head", "published_head", "expected_head", "expected_base", "review_requested_head", "delivery_head", "review_requested_security_head", "native_head"}:
                _sha(value)
            elif key in {"attempt_id", "native_step"}:
                try:
                    if str(uuid.UUID(value)) != value:
                        raise ValueError()
                except (ValueError, AttributeError, TypeError) as exc:
                    raise GitHubError("Invalid attempt UUID") from exc
            elif key == "pending_thread":
                if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                    raise GitHubError("Invalid pending review thread ID")
            elif key == "pending_review_kind":
                if value not in {"code", "security"}:
                    raise GitHubError("Invalid pending review kind")
            elif key == "execution_mode":
                if value != "native":
                    raise GitHubError("Invalid execution mode")
            elif key == "native_phase":
                if value not in {"design", "spec_review", "implementation", "correction", "change_review"}:
                    raise GitHubError("Invalid native phase")
            elif key == "native_outcome":
                if value not in {"candidate_ready", "failed", "needs_decision", "stopped"}:
                    raise GitHubError("Invalid native outcome")
            elif key in {"action_attempt", "delivery_attempt", "correction_attempt"}:
                if type(value) is not int or not 1 <= value <= 3:
                    raise GitHubError("Service action retry bound exceeded")
            elif key in {"pr_number", "repository_id", "issue_number", "version"}:
                _number(value)
            elif key == "branch":
                if not re.fullmatch(r"hydra/issue-[1-9][0-9]*", value):
                    raise GitHubError("Invalid owned branch")
            elif not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", value):
                raise GitHubError("Progress requires public codes, not raw text")

    def record(self, repo, n, record):
        self._validate_record(record)
        metadata = {**record, "version": 1, "repository_id": self.repository(repo)["id"], "issue_number": _number(n)}
        if metadata.get("branch") not in {None, f"hydra/issue-{n}"}:
            raise GitHubError("Progress branch mismatch")
        previous = self._progress_comment(repo, n)
        if previous:
            old = _marker(previous.get("body"), "hydra-progress")
            if old.get("repository_id") != metadata["repository_id"] or old.get("issue_number") != n or old.get("version") != 1:
                raise GitHubError("Existing progress identity mismatch")
            self._validate_record(old, metadata=True)
        completed = (metadata.get("phase") == "completed" and metadata.get("pending_action") is None
                     and metadata.get("wait_reason") is None)
        if not completed:
            self._active(repo, n, True)
        if previous and old == metadata:
            if completed:
                self._active(repo, n, False)
            return previous
        human = ["## Hydra progress", ""]
        human += [f"- {key.replace('_', ' ').capitalize()}: `{value}`" for key, value in metadata.items() if value is not None and key not in {"version", "repository_id", "issue_number"}]
        body = "\n".join(human) + "\n\n<!-- hydra-progress:v1 " + json.dumps(metadata, sort_keys=True, separators=(",", ":")) + " -->"
        if previous:
            result = self.api("PATCH", f"/repos/{_repo(repo)}/issues/comments/{_number(previous['id'])}", {"body": body})
        else:
            result = self.api("POST", f"/repos/{_repo(repo)}/issues/{n}/comments", {"body": body})
        if completed:
            self._active(repo, n, False)
        return result

    def ref(self, repo, branch):
        try:
            data = self.api("GET", f"/repos/{_repo(repo)}/git/ref/heads/{quote(branch, safe='')}")
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        return _sha(data.get("object", {}).get("sha")) if isinstance(data, dict) else _sha(None)

    def pulls(self, repo, branch):
        owner = _repo(repo).split("/")[0]
        return self._pages(f"/repos/{repo}/pulls?" + urlencode({"state": "all", "head": f"{owner}:{branch}"}))

    def _threads(self, repo, n):
        owner, name = _repo(repo).split("/")
        _number(n)
        cursor = None
        pr_id = None
        threads = []
        thread_ids, comment_ids, outer_cursors = set(), set(), set()
        requests = 0
        query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){id reviewDecision reviewThreads(first:100,after:$cursor){nodes{id isResolved isOutdated comments(first:100){nodes{databaseId author{login}}pageInfo{hasNextPage endCursor}}}pageInfo{hasNextPage endCursor}}}}}"""
        comment_query = """query($thread:ID!,$cursor:String){node(id:$thread){... on PullRequestReviewThread{id pullRequest{id} comments(first:100,after:$cursor){nodes{databaseId author{login}}pageInfo{hasNextPage endCursor}}}}}"""

        def fetch(query, variables):
            nonlocal requests
            if requests >= 100:
                raise GitHubError("Review thread pagination exceeds bound")
            requests += 1
            data = self.api("POST", "/graphql", {"query": query, "variables": variables})
            if not isinstance(data, dict) or data.get("errors"):
                raise GitHubError("Review thread observation incomplete")
            return data["data"]

        def page(collection, cursors):
            nodes, info = collection["nodes"], collection["pageInfo"]
            if (not isinstance(nodes, list) or len(nodes) > 100
                    or any(not isinstance(node, dict) for node in nodes)
                    or not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool):
                raise KeyError()
            if not info["hasNextPage"]:
                return nodes, None
            following = info.get("endCursor")
            if not isinstance(following, str) or not following or following in cursors:
                raise KeyError()
            cursors.add(following)
            return nodes, following

        while True:
            try:
                data = fetch(query, {"owner": owner, "name": name, "number": n, "cursor": cursor})
                pr = data["repository"]["pullRequest"]
                if not isinstance(pr["id"], str) or not pr["id"] or pr_id not in {None, pr["id"]}:
                    raise KeyError()
                pr_id = pr["id"]
                current, cursor = page(pr["reviewThreads"], outer_cursors)
                for thread in current:
                    tid = thread.get("id")
                    if (not isinstance(tid, str) or not tid or tid in thread_ids
                            or type(thread.get("isResolved")) is not bool
                            or type(thread.get("isOutdated")) is not bool):
                        raise KeyError()
                    thread_ids.add(tid)
                    collection = thread["comments"]
                    comments, comment_cursors = [], set()
                    while True:
                        nodes, next_cursor = page(collection, comment_cursors)
                        for node in nodes:
                            cid = node.get("databaseId")
                            if type(cid) is not int or cid < 1 or cid in comment_ids:
                                raise KeyError()
                            comment_ids.add(cid)
                        comments.extend(nodes)
                        if next_cursor is None:
                            break
                        detail = fetch(comment_query, {"thread": tid, "cursor": next_cursor})["node"]
                        if detail["id"] != tid or detail["pullRequest"]["id"] != pr_id:
                            raise KeyError()
                        collection = detail["comments"]
                    threads.append({**thread, "comments": {"nodes": comments, "pageInfo": collection["pageInfo"]}})
                if cursor is None:
                    return threads, pr["reviewDecision"]
            except (KeyError, TypeError) as exc:
                raise GitHubError("Review thread observation incomplete") from exc

    def observe(self, repo, pr):
        info = self.repository(repo)
        raw = self.api("GET", f"/repos/{repo}/pulls/{_number(pr)}")
        head = _sha(raw.get("head", {}).get("sha"))
        base = self.ref(repo, info["default_branch"])
        if base is None:
            raise GitHubError("Default branch missing")
        checks, runs = [], []
        targets = [head, base]
        if raw.get("merged") is True:
            targets.append(_sha(raw.get("merge_commit_sha")))
        for commit in dict.fromkeys(targets):
            checks.extend(self._pages(f"/repos/{repo}/commits/{commit}/check-runs?filter=latest", "check_runs"))
            runs.extend(self._pages(f"/repos/{repo}/actions/runs?head_sha={commit}", "workflow_runs"))
        # Fetch each run itself: the list response alone can omit reusable workflow identity.
        expanded = self._expand_runs(repo, runs)
        threads, decision = self._threads(repo, pr)
        files = self._pages(f"/repos/{repo}/pulls/{pr}/files")
        if raw.get("changed_files") != len(files):
            raise GitHubError("Changed file observation incomplete")
        rules = self.api("GET", f"/repos/{repo}/rules/branches/{quote(info['default_branch'], safe='')}")
        if not isinstance(rules, list):
            raise GitHubError("Protection observation incomplete")
        sources = []
        for rid, source, kind in sorted({(r.get("ruleset_id"), r.get("ruleset_source"), r.get("ruleset_source_type")) for r in rules}, key=str):
            if type(rid) is not int or not source or kind not in {"Repository", "Organization"}:
                raise GitHubError("Unknown protection source")
            prefix = f"/repos/{_repo(source)}" if kind == "Repository" else f"/orgs/{quote(source, safe='')}"
            sources.append(self.api("GET", f"{prefix}/rulesets/{rid}"))
        commits = {}
        if raw.get("merged") is True:
            # Immutable Git objects bind the historical result, independent of
            # the current default branch advancing after the merge.
            commits = {"head_commit": self.commit(repo, head),
                       "merge_commit": self.commit(repo, raw["merge_commit_sha"])}
        return {"repository": info, "pr": raw, "checks": checks, "runs": expanded,
                "native_reviews": self._pages(f"/repos/{repo}/pulls/{pr}/reviews"),
                "threads": threads, "review_decision": decision, "provider_comments": self.comments(repo, pr),
                "base_sha": base, "head_sha": head, "rules": rules, "rule_sources": sources,
                "changed_files": files,
                "commits": self._pages(f"/repos/{repo}/pulls/{pr}/commits"),
                "inline_comments": self._pages(f"/repos/{repo}/pulls/{pr}/comments"), **commits}

    def commit(self, repo, sha):
        """Read immutable Git data; completion gates validate the returned shape."""
        return self.api("GET", f"/repos/{_repo(repo)}/git/commits/{_sha(sha)}")

    def observe_commit(self, repo, sha):
        _sha(sha)
        info = self.repository(repo)
        checks = self._pages(f"/repos/{repo}/commits/{sha}/check-runs?filter=latest", "check_runs")
        runs = self._pages(f"/repos/{repo}/actions/runs?head_sha={sha}", "workflow_runs")
        expanded = self._expand_runs(repo, runs)
        return {"repository": info, "head_sha": sha, "checks": checks, "runs": expanded}

    def _expand_runs(self, repo, runs):
        ids = []
        for run in runs:
            if not isinstance(run, dict):
                raise GitHubError("Workflow run observation incomplete")
            ids.append(_number(run.get("id")))
        expanded = []
        for rid in dict.fromkeys(ids):
            detail = self.api("GET", f"/repos/{repo}/actions/runs/{rid}")
            if not isinstance(detail, dict) or type(detail.get("id")) is not int or detail["id"] != rid:
                raise GitHubError("Workflow run observation incomplete")
            jobs = self._pages(f"/repos/{repo}/actions/runs/{rid}/jobs?filter=latest", "jobs")
            expanded.append({**detail, "jobs": jobs})
        return expanded

    def owns_pr(self, repo, n, pr):
        """One ownership predicate for publication and runner reconciliation."""
        _number(n)
        info, identity = self.repository(repo), self._identity()
        if not isinstance(pr, dict) or not isinstance(pr.get("body"), str):
            return False
        try:
            marker = _marker(pr["body"], "hydra-pr")
        except GitHubError:
            return False
        author, head, base = pr.get("user"), pr.get("head"), pr.get("base")
        if not all(isinstance(x, dict) for x in [author, head, base]):
            return False
        if not all(isinstance(x.get("repo"), dict) for x in [head, base]):
            return False
        return (isinstance(marker, dict) and set(marker) == {"repository_id", "issue_number"}
                and type(marker["repository_id"]) is int and marker["repository_id"] == info["id"]
                and type(marker["issue_number"]) is int and marker["issue_number"] == n
                and author.get("id") == identity["id"] and author.get("login") == identity["login"]
                and head["repo"].get("id") == info["id"] and base["repo"].get("id") == info["id"]
                and head.get("ref") == f"hydra/issue-{n}"
                and base.get("ref") == info["default_branch"])

    def _owned_pr_issue(self, repo, pr, expected_issue):
        _number(expected_issue)
        head = pr.get("head") if isinstance(pr, dict) else None
        branch = head.get("ref") if isinstance(head, dict) else None
        match = re.fullmatch(r"hydra/issue-([1-9][0-9]*)", branch) if isinstance(branch, str) else None
        try:
            issue = int(match[1]) if match else None
        except ValueError as exc:
            raise GitHubError("Foreign branch or PR ownership") from exc
        if issue != expected_issue or not self.owns_pr(repo, expected_issue, pr):
            raise GitHubError("Foreign branch or PR ownership")
        return issue

    def ensure_pr(self, repo, n, branch, head, title, body):
        _number(n); _sha(head)
        if branch != f"hydra/issue-{n}":
            raise GitHubError("Only the owned issue branch can be published")
        info = self.repository(repo)
        self._identity()
        marker = {"repository_id": info["id"], "issue_number": n}
        existing = self.pulls(repo, branch)
        if len(existing) > 1:
            raise GitHubError("Multiple matching PRs")
        if existing:
            value = existing[0]
            if not self.owns_pr(repo, n, value):
                raise GitHubError("Foreign branch or PR ownership")
            if value.get("head", {}).get("repo", {}).get("id") != info["id"] or value.get("head", {}).get("ref") != branch or value.get("head", {}).get("sha") != head or value.get("base", {}).get("ref") != info["default_branch"]:
                raise GitHubError("Existing PR revision mismatch")
            if value.get("state") != "open":
                if value.get("merged_at"):
                    return value
                raise GitHubError("Owned PR closed without merge")
            return value
        if self.ref(repo, branch) != head:
            raise GitHubError("Published branch revision mismatch")
        if not isinstance(title, str) or not 1 <= len(title) <= 240 or not isinstance(body, str) or len(body) > 6000:
            raise GitHubError("Invalid public PR description")
        # PR bodies are supplied by the trusted runner, never raw provider output.
        if re.search(r"(?im)\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:#\d|https://github.com/)", body):
            raise GitHubError("Issue closure must follow post-merge observation")
        body += f"\n\nRelated issue: #{n}\n\n<!-- hydra-pr:v1 " + json.dumps(marker, sort_keys=True, separators=(",", ":")) + " -->"
        return self.api("POST", f"/repos/{repo}/pulls", {"head": branch, "base": info["default_branch"], "title": title, "body": body})

    def request_review(self, repo, pr, kind="code", head=None, *, issue_number):
        _number(issue_number)
        if kind not in {"code", "security"}:
            raise GitHubError("Unknown review kind")
        raw = self.api("GET", f"/repos/{_repo(repo)}/pulls/{_number(pr)}")
        issue = self._owned_pr_issue(repo, raw, issue_number)
        current = _sha(raw.get("head", {}).get("sha"))
        if head is None:
            head = current
        if _sha(head) != current or raw.get("state") != "open":
            raise GitHubError("Review request head changed or PR closed")
        identity = self._identity()
        marker = f"<!-- hydra-review-request:v1 head={head} kind={kind} -->"

        def current_owned():
            latest = self.api("GET", f"/repos/{repo}/pulls/{pr}")
            self._owned_pr_issue(repo, latest, issue)
            if latest.get("state") != "open" or latest["head"].get("sha") != head:
                raise GitHubError("Review request head changed or PR closed")

        def find():
            own = [c for c in self.comments(repo, pr) if c.get("user", {}).get("id") == identity["id"] and marker in (c.get("body") or "")]
            if len(own) > 1:
                raise GitHubError("Duplicate review requests")
            return own[0] if own else None

        existing = find()
        current_owned()
        if existing:
            return existing
        body = ("@codex review" if kind == "code" else "@codex security review") + "\n\n" + marker
        try:
            return self.api("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})
        except GitHubError:
            # A missing response is not permission to publish another request.
            try:
                recovered = find()
                current_owned()
            except GitHubError as exc:
                raise GitHubError("Review request read-back unavailable", uncertain=True) from exc
            if recovered:
                return recovered
            raise

    def resolve_thread(self, repo, pr, thread_id, expected_head, provider, *, issue_number):
        """Resolve only an observed outdated provider-only thread after runner review.

        GitHub has no head-conditioned thread mutation. Recheck the head before
        and after; a concurrent change remains uncertain, never delivery evidence.
        """
        _repo(repo); _number(pr); _sha(expected_head); _number(issue_number)
        if (not isinstance(thread_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", thread_id)
                or not isinstance(provider, dict) or provider.get("login") != "chatgpt-codex-connector[bot]"
                or type(provider.get("user_id")) is not int or provider["user_id"] < 1
                or type(provider.get("app_id")) is not int or provider["app_id"] < 1):
            raise GitHubError("Unknown review thread or provider identity")

        def head_current():
            raw = self.api("GET", f"/repos/{repo}/pulls/{pr}")
            self._owned_pr_issue(repo, raw, issue_number)
            return raw.get("state") == "open" and raw.get("head", {}).get("sha") == expected_head

        if not head_current():
            raise GitHubError("PR head changed before thread resolution")
        threads, _ = self._threads(repo, pr)
        selected = [t for t in threads if t.get("id") == thread_id]
        if len(selected) != 1 or selected[0].get("isOutdated") is not True:
            raise GitHubError("Thread is not an outdated member of this PR")
        comment_ids = [c.get("databaseId") for c in selected[0].get("comments", {}).get("nodes", [])]
        comments = self._pages(f"/repos/{repo}/pulls/{pr}/comments")
        if not comment_ids or any(type(cid) is not int for cid in comment_ids) or len(set(comment_ids)) != len(comment_ids):
            raise GitHubError("Thread comment ownership unobserved")
        for cid in comment_ids:
            matching = [c for c in comments if isinstance(c, dict) and c.get("id") == cid]
            if len(matching) != 1:
                raise GitHubError("Thread comment ownership unobserved")
            author, app = matching[0].get("user"), matching[0].get("performed_via_github_app")
            if (not isinstance(author, dict) or type(author.get("id")) is not int
                    or author["id"] != provider["user_id"] or author.get("login") != provider["login"]
                    or author.get("type") != "Bot"
                    or (app is not None and (not isinstance(app, dict)
                        or type(app.get("id")) is not int or app["id"] != provider["app_id"]))):
                raise GitHubError("Human or unknown review comment must be preserved")
        if selected[0].get("isResolved") is True:
            if not head_current():
                raise GitHubError("Review thread state changed")
            return selected[0]
        if selected[0].get("isResolved") is not False or not head_current():
            raise GitHubError("Review thread state changed")
        query = "mutation($thread:ID!){resolveReviewThread(input:{threadId:$thread}){thread{id isResolved}}}"
        try:
            result = self.api("POST", "/graphql", {"query": query, "variables": {"thread": thread_id}})
            if not isinstance(result, dict) or result.get("errors"):
                raise GitHubError("Review thread mutation outcome unknown", uncertain=True)
        except GitHubError as exc:
            failure = exc
        else:
            failure = None
        try:
            actual, _ = self._threads(repo, pr)
            current_head_matches = head_current()
        except GitHubError as exc:
            raise GitHubError("Thread resolution read-back unavailable", uncertain=True) from exc
        actual = [t for t in actual if t.get("id") == thread_id]
        if (len(actual) == 1 and actual[0].get("isResolved") is True
                and actual[0].get("isOutdated") is True
                and actual[0].get("comments", {}).get("nodes") == selected[0]["comments"]["nodes"]
                and current_head_matches):
            return actual[0]
        raise GitHubError("Thread resolution requires reconciliation", uncertain=True) from failure

    def merge(self, repo, pr, head, *, commit_message, issue_number):
        _sha(head); _number(issue_number)
        if not isinstance(commit_message, str) or not re.fullmatch(r"Hydra-Squash-v1: [0-9a-f]{64}", commit_message):
            raise GitHubError("Squash correlation message missing")
        raw = self.api("GET", f"/repos/{_repo(repo)}/pulls/{_number(pr)}")
        self._owned_pr_issue(repo, raw, issue_number)
        if not isinstance(raw, dict) or not isinstance(raw.get("head"), dict) or raw["head"].get("sha") != head:
            raise GitHubError("PR head changed before merge")
        if raw.get("merged") is True:
            raise GitHubError("Merged PR requires squash receipt reconciliation", uncertain=True)
        if raw.get("state") != "open" or raw.get("draft") is not False or raw.get("mergeable") is not True or raw.get("mergeable_state") != "clean":
            raise GitHubError("Native merge requirements are not satisfied")
        result = self.api("PUT", f"/repos/{repo}/pulls/{pr}/merge", {
            "sha": head, "merge_method": "squash", "commit_message": commit_message})
        if (not isinstance(result, dict) or result.get("merged") is not True
                or not isinstance(result.get("sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", result["sha"])):
            raise GitHubError("Squash response requires reconciliation", uncertain=True)
        try:
            actual = self.api("GET", f"/repos/{repo}/pulls/{pr}")
            self._owned_pr_issue(repo, actual, issue_number)
        except GitHubError as exc:
            raise GitHubError("Merge read-back unavailable", uncertain=True) from exc
        if (not isinstance(actual, dict) or actual.get("merged") is not True or actual.get("state") != "closed"
                or not isinstance(actual.get("head"), dict) or actual["head"].get("sha") != head
                or actual.get("merge_commit_sha") != result["sha"]):
            raise GitHubError("Merge outcome requires reconciliation", uncertain=True)
        return actual

    def close_issue(self, repo, n):
        # The runner supplies the post-merge observation gate before invoking this.
        return self.api("PATCH", f"/repos/{_repo(repo)}/issues/{_number(n)}", {"state": "closed", "state_reason": "completed"})
