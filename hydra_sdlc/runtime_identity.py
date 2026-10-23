"""Bounded observations of package bytes and host binding, never attestations.

Package bytes and the declared version are captured once when this module loads.
The digest describes sources observed then, not proof of which bytes Python loaded
or authority to operate an installation. No provider factories are imported.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from . import __version__
from .native_admission import parse_admission_profile

MAX_SOURCE_FILES = 128
MAX_SOURCE_DIRS = 64
MAX_SOURCE_DEPTH = 8
MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 256
_REPOSITORY = re.compile(r"[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}\Z")
_PROVIDER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*\Z", re.ASCII)
_CONFIG_FIELDS = frozenset({"repos", "host_alias", "workspace_root", "lock_path",
    "lifecycle_provider", "storage_provider", "knowledge_repo", "runtime_python", "project_threads",
    "native_admission_control", "connection_schema", "project_connections"})
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _fingerprint(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _absolute_path(value):
    if not isinstance(value, (str, Path)):
        raise ValueError("invalid path")
    text = str(value)
    path = Path(text)
    if (not text or len(text) > 4096 or not path.is_absolute()
            or ".." in path.parts or any(ord(c) < 32 or ord(c) == 127 for c in text)):
        raise ValueError("invalid path")
    return str(path)


def _digest_sources(root):
    """Hash sorted relative names and file bytes through no-follow directory FDs."""
    root = Path(_absolute_path(root))
    opened = []
    try:
        fd = os.open("/", _DIRECTORY_FLAGS)
        opened.append(fd)
        for component in root.parts[1:]:
            fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=fd)
            opened.append(fd)
        root_fingerprint = _fingerprint(os.fstat(fd))
        digest = hashlib.sha256(b"hydra-package-sources-v1\0")
        counts = {"files": 0, "dirs": 0, "bytes": 0}
        observed = []

        def walk(directory, prefix, depth):
            counts["dirs"] += 1
            if depth > MAX_SOURCE_DEPTH or counts["dirs"] > MAX_SOURCE_DIRS:
                raise ValueError("source bounds")
            before = os.fstat(directory)
            names = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    names.append(entry.name)
                    if len(names) > MAX_DIRECTORY_ENTRIES:
                        raise ValueError("source bounds")
            names.sort()
            for name in names:
                relative = prefix + name
                encoded = relative.encode("utf-8")
                if len(encoded) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in name):
                    raise ValueError("source path")
                entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if stat.S_ISLNK(entry.st_mode):
                    raise ValueError("source symlink")
                if stat.S_ISDIR(entry.st_mode):
                    if name == "__pycache__":
                        continue
                    observed.append((relative, _fingerprint(entry)))
                    child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
                    try:
                        if _fingerprint(entry) != _fingerprint(os.fstat(child)):
                            raise ValueError("source changed")
                        walk(child, relative + "/", depth + 1)
                        if _fingerprint(entry) != _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)):
                            raise ValueError("source changed")
                    finally:
                        os.close(child)
                elif name.endswith(".py"):
                    if not stat.S_ISREG(entry.st_mode) or entry.st_size > MAX_SOURCE_FILE_BYTES:
                        raise ValueError("unsafe source")
                    observed.append((relative, _fingerprint(entry)))
                    counts["files"] += 1
                    counts["bytes"] += entry.st_size
                    if counts["files"] > MAX_SOURCE_FILES or counts["bytes"] > MAX_SOURCE_BYTES:
                        raise ValueError("source bounds")
                    source = os.open(name, _FILE_FLAGS, dir_fd=directory)
                    try:
                        if _fingerprint(entry) != _fingerprint(os.fstat(source)):
                            raise ValueError("source changed")
                        digest.update(len(encoded).to_bytes(4, "big"))
                        digest.update(encoded)
                        digest.update(entry.st_size.to_bytes(8, "big"))
                        remaining = entry.st_size
                        while remaining:
                            chunk = os.read(source, min(remaining, 65536))
                            if not chunk:
                                raise ValueError("source changed")
                            digest.update(chunk)
                            remaining -= len(chunk)
                        if (os.read(source, 1) or _fingerprint(entry) != _fingerprint(os.fstat(source))
                                or _fingerprint(entry) != _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False))):
                            raise ValueError("source changed")
                    finally:
                        os.close(source)
            if _fingerprint(before) != _fingerprint(os.fstat(directory)):
                raise ValueError("source changed")

        walk(fd, "", 0)
        # Verify earlier entries too: a later read may race an earlier file edit.
        for relative, fingerprint in observed:
            parents = []
            try:
                directory = fd
                parts = relative.split("/")
                for part in parts[:-1]:
                    directory = os.open(part, _DIRECTORY_FLAGS, dir_fd=directory)
                    parents.append(directory)
                if fingerprint != _fingerprint(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)):
                    raise ValueError("source changed")
            finally:
                for parent in reversed(parents):
                    os.close(parent)
        # Reopen every root component to reject an ancestor alias/replacement.
        named = os.open("/", _DIRECTORY_FLAGS)
        opened.append(named)
        for component in root.parts[1:]:
            named = os.open(component, _DIRECTORY_FLAGS, dir_fd=named)
            opened.append(named)
        if (not counts["files"] or root_fingerprint != _fingerprint(os.fstat(fd))
                or root_fingerprint != _fingerprint(os.fstat(named))):
            raise ValueError("source changed")
        return digest.hexdigest()
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _capture_code_identity(root, version):
    result = {"version": None, "code_digest": None, "identity_reason": None}
    if isinstance(version, str) and 0 < len(version) <= 128 and all(32 <= ord(c) < 127 for c in version):
        result["version"] = version
    else:
        result["identity_reason"] = "runtime_version_unavailable"
    try:
        result["code_digest"] = _digest_sources(root)
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError):
        result["identity_reason"] = "runtime_source_unavailable"
    return result


def _repository(value):
    if (not isinstance(value, str) or not _REPOSITORY.fullmatch(value)
            or value.split("/")[-1] in {".", ".."}):
        raise ValueError("invalid repository")
    return value


def _configuration(cfg):
    if not isinstance(cfg, dict) or set(cfg) - _CONFIG_FIELDS:
        raise ValueError("invalid configuration")
    repos = cfg.get("repos")
    if not isinstance(repos, list) or not (0 if 'connection_schema' in cfg else 1) <= len(repos) <= 1024:
        raise ValueError("invalid configuration")
    repos = sorted(_repository(repo) for repo in repos)
    if len(set(repos)) != len(repos):
        raise ValueError("invalid configuration")
    host = cfg.get("host_alias")
    if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", host):
        raise ValueError("invalid configuration")
    value = {"repos": repos, "host_alias": host, "workspace_root": _absolute_path(cfg.get("workspace_root"))}
    for key in ("lock_path", "runtime_python"):
        if key in cfg:
            value[key] = _absolute_path(cfg[key])
    for key in ("lifecycle_provider", "storage_provider"):
        if key in cfg:
            provider = cfg[key]
            if not isinstance(provider, str) or len(provider) > 512 or not _PROVIDER.fullmatch(provider):
                raise ValueError("invalid provider")
            value[key] = provider
    if "knowledge_repo" in cfg:
        value["knowledge_repo"] = _repository(cfg["knowledge_repo"])
    threads = cfg.get("project_threads", {})
    if not isinstance(threads, dict) or len(threads) > len(repos):
        raise ValueError("invalid threads")
    for repo, thread in threads.items():
        if repo not in repos or not isinstance(thread, str) or str(uuid.UUID(thread)) != thread:
            raise ValueError("invalid thread")
    value["project_threads"] = dict(threads)
    from .connection_profile import declarations
    connections = declarations(cfg, repos)
    if connections is not None:
        value.update(connection_schema=1, project_connections=connections)
    if "native_admission_control" in cfg:
        value["native_admission_control"] = parse_admission_profile(cfg["native_admission_control"])
    return value


def _semantic_digest(domain, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + data).hexdigest()


_STARTUP_IDENTITY = _capture_code_identity(Path(__file__).absolute().parent, __version__)


def capture_runtime_identity(cfg=None, control=None):
    """Return public metadata; absent config/control stays explicitly unknown."""
    result = {"identity_schema": 1, "package": "openboa-hydra-sdlc",
              **_STARTUP_IDENTITY, "code_digest_scope": "package_sources_at_startup",
              "config_digest": None, "control_binding_digest": None}
    if cfg is not None:
        try:
            result["config_digest"] = _semantic_digest("hydra-host-config-v1", _configuration(cfg))
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            result["identity_reason"] = result["identity_reason"] or "runtime_config_unavailable"
    if control is not None:
        try:
            binding = {"settings_path": _absolute_path(control.settings_path),
                       "control_lock_path": _absolute_path(control.control_lock_path)}
            result["control_binding_digest"] = _semantic_digest("hydra-control-binding-v1", binding)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            result["identity_reason"] = result["identity_reason"] or "runtime_control_binding_unavailable"
    return result
