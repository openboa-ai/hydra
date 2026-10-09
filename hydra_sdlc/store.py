"""Transactional execution ownership. No worker can mark delivery complete."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class StateError(ValueError):
    pass


def encoded(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise StateError('Value is not valid finite JSON') from exc


def now():
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise StateError('State must not be a symbolic link')
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        try:
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def _initialize(self):
        with self.tx():
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise StateError('Unsupported state schema version')
            if version == 0:
                if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise StateError('Unversioned existing database cannot be adopted')
                for statement in (
                    '''CREATE TABLE work(work_id TEXT PRIMARY KEY, repository_id INTEGER NOT NULL,
                       assignment TEXT NOT NULL, input_digest TEXT NOT NULL, priority INTEGER NOT NULL,
                       status TEXT NOT NULL, wait_reason TEXT, current_run_id TEXT, generation INTEGER NOT NULL DEFAULT 0,
                       reserved INTEGER NOT NULL DEFAULT 0, stop_requested TEXT,
                       created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
                    '''CREATE TABLE runs(id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES work(work_id),
                       generation INTEGER NOT NULL, status TEXT NOT NULL, thread_id TEXT, turn_id TEXT,
                       process_identity TEXT, detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                       UNIQUE(work_id,generation))''',
                    '''CREATE TABLE events(run_id TEXT NOT NULL REFERENCES runs(id), event_id TEXT NOT NULL,
                       payload TEXT NOT NULL, stale INTEGER NOT NULL, created_at TEXT NOT NULL,
                       PRIMARY KEY(run_id,event_id))''',
                    '''CREATE TABLE audit(id INTEGER PRIMARY KEY, work_id TEXT NOT NULL,
                       action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)''',
                    '''CREATE UNIQUE INDEX one_reserved_repository ON work(repository_id) WHERE reserved=1''',
                ):
                    self.db.execute(statement)
                self.db.execute('PRAGMA user_version=1')
            required = {
                'work': {'work_id', 'repository_id', 'assignment', 'input_digest', 'priority', 'status', 'wait_reason', 'current_run_id', 'generation', 'reserved', 'stop_requested', 'created_at', 'updated_at'},
                'runs': {'id', 'work_id', 'generation', 'status', 'thread_id', 'turn_id', 'process_identity', 'detail', 'created_at', 'updated_at'},
                'events': {'run_id', 'event_id', 'payload', 'stale', 'created_at'},
                'audit': {'id', 'work_id', 'action', 'detail', 'created_at'},
            }
            for table, fields in required.items():
                columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
                if not fields.issubset(columns):
                    raise StateError('State schema is incomplete or corrupt: ' + table)
            if not self.db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='one_reserved_repository'").fetchone():
                raise StateError('State ownership index is missing')

    @contextmanager
    def tx(self):
        try:
            self.db.execute('BEGIN IMMEDIATE')
        except sqlite3.Error as exc:
            raise StateError('Cannot acquire state transaction') from exc
        try:
            yield
            self.db.execute('COMMIT')
        except sqlite3.Error as exc:
            self.db.execute('ROLLBACK')
            raise StateError('State database operation failed') from exc
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _audit(self, work_id, action, detail):
        self.db.execute('INSERT INTO audit(work_id,action,detail,created_at) VALUES(?,?,?,?)',
                        (work_id, action, encoded(detail), now()))

    @staticmethod
    def _work(row):
        if row is None:
            raise StateError('Unknown work ID')
        result = dict(row)
        result['assignment'] = json.loads(result['assignment'])
        return result

    def get_work(self, work_id):
        return self._work(self.db.execute('SELECT * FROM work WHERE work_id=?', (work_id,)).fetchone())

    def list_work(self):
        return [self._work(row) for row in self.db.execute('SELECT * FROM work ORDER BY created_at,work_id')]

    def _run(self, run_id):
        row = self.db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise StateError('Unknown run ID')
        result = dict(row)
        for field in ('detail', 'process_identity'):
            if result[field] is not None:
                result[field] = json.loads(result[field])
        result['assignment'] = self.get_work(result['work_id'])['assignment']
        return result

    def list_runs(self, work_id=None):
        query, params = ('SELECT id FROM runs ORDER BY created_at,id', ()) if work_id is None else (
            'SELECT id FROM runs WHERE work_id=? ORDER BY created_at,id', (work_id,))
        return [self._run(row[0]) for row in self.db.execute(query, params)]

    def events(self, run_id):
        self._run(run_id)
        return [{**dict(row), 'payload': json.loads(row['payload'])}
                for row in self.db.execute('SELECT * FROM events WHERE run_id=? ORDER BY created_at,event_id', (run_id,))]

    def add_work(self, assignment):
        if not isinstance(assignment, dict):
            raise StateError('Assignment must be an object')
        a = dict(assignment)
        for key in ('work_id', 'goal_ref', 'goal_revision', 'spec_ref', 'spec_revision', 'cwd', 'task'):
            if not isinstance(a.get(key), str) or not a[key].strip():
                raise StateError('Missing or invalid assignment field: ' + key)
        if type(a.get('repository_id')) is not int or not 0 < a['repository_id'] < 2**63:
            raise StateError('Repository identity must be a positive integer')
        cwd = Path(a['cwd'])
        if not cwd.is_absolute() or not cwd.is_dir():
            raise StateError('Cwd must be an existing absolute directory')
        a.setdefault('role', 'implement')
        a.setdefault('priority', 0)
        a.setdefault('dependencies', [])
        if a['role'] not in ('plan', 'implement', 'review', 'diagnose') or type(a['priority']) is not int or not -(2**63) < a['priority'] < 2**63:
            raise StateError('Invalid role or priority')
        deps = a['dependencies']
        if not isinstance(deps, list) or any(not isinstance(x, str) or not x for x in deps) or len(set(deps)) != len(deps):
            raise StateError('Invalid dependencies')
        if a['work_id'] in deps:
            raise StateError('Work cannot depend on itself')
        data = encoded(a)
        digest = hashlib.sha256(data.encode()).hexdigest()
        with self.tx():
            existing = self.db.execute('SELECT input_digest FROM work WHERE work_id=?', (a['work_id'],)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise StateError('Work ID already has different immutable input')
                return self.get_work(a['work_id'])
            for dependency in deps:
                self.get_work(dependency)  # Existing immutable nodes cannot introduce a cycle.
            stamp = now()
            self.db.execute('''INSERT INTO work(work_id,repository_id,assignment,input_digest,priority,
                               status,created_at,updated_at) VALUES(?,?,?,?,?,'ready',?,?)''',
                            (a['work_id'], a['repository_id'], data, digest, a['priority'], stamp, stamp))
            self._audit(a['work_id'], 'registered', {'input_digest': digest})
        return self.get_work(a['work_id'])

    def claim_next(self):
        with self.tx():
            count = self.db.execute('SELECT count(*) FROM work WHERE reserved=1').fetchone()[0]
            for row in self.db.execute("SELECT * FROM work WHERE status='ready' ORDER BY priority DESC,created_at,work_id").fetchall():
                work = self._work(row)
                # S1 has no externally proven completion transition: dependencies stay unmet.
                if work['assignment']['dependencies'] or (not work['reserved'] and count >= 2):
                    continue
                other = self.db.execute('SELECT work_id FROM work WHERE repository_id=? AND reserved=1 AND work_id!=?',
                                        (work['repository_id'], work['work_id'])).fetchone()
                if other or work['current_run_id']:
                    continue
                run_id, generation, stamp = str(uuid.uuid4()), work['generation'] + 1, now()
                self.db.execute('''INSERT INTO runs(id,work_id,generation,status,created_at,updated_at)
                                   VALUES(?,?,?,'running',?,?)''', (run_id, work['work_id'], generation, stamp, stamp))
                self.db.execute("""UPDATE work SET status='running',reserved=1,current_run_id=?,generation=?,
                                   wait_reason=NULL,stop_requested=NULL,updated_at=? WHERE work_id=?""",
                                (run_id, generation, stamp, work['work_id']))
                self._audit(work['work_id'], 'claimed', {'run_id': run_id, 'generation': generation})
                run = self._run(run_id)
                previous = self.db.execute('SELECT thread_id FROM runs WHERE work_id=? AND id!=? AND thread_id IS NOT NULL ORDER BY generation DESC LIMIT 1',
                                           (work['work_id'], run_id)).fetchone()
                run['resume_thread_id'] = previous[0] if previous else None
                return run
            return None

    def _owned(self, run_id, generation):
        run = self._run(run_id)
        work = self.get_work(run['work_id'])
        if type(generation) is not int or run['generation'] != generation or work['generation'] != generation or work['current_run_id'] != run_id:
            raise StateError('Stale run ownership')
        if run['status'] not in ('running', 'transport_unknown'):
            raise StateError('Run is no longer active')
        return run, work

    def set_identity(self, run_id, generation, thread_id=None, turn_id=None, process_identity=None):
        with self.tx():
            run, work = self._owned(run_id, generation)
            for field, value in (('thread_id', thread_id), ('turn_id', turn_id), ('process_identity', process_identity)):
                if value is None:
                    continue
                if field != 'process_identity' and (not isinstance(value, str) or not value):
                    raise StateError('Invalid runner identity')
                if run[field] is not None and run[field] != value:
                    raise StateError('Cannot replace an existing runner identity')
                value = encoded(value) if field == 'process_identity' else value
                self.db.execute(f'UPDATE runs SET {field}=?,updated_at=? WHERE id=?', (value, now(), run_id))
            self._audit(work['work_id'], 'identity_bound', {'run_id': run_id})
        return self._run(run_id)

    def record_event(self, run_id, generation, event_id, payload):
        if not isinstance(event_id, str) or not event_id:
            raise StateError('Invalid event ID')
        data = encoded(payload)
        with self.tx():
            run = self._run(run_id)
            if type(generation) is not int or run['generation'] != generation:
                raise StateError('Wrong run generation')
            work = self.get_work(run['work_id'])
            stale = work['current_run_id'] != run_id or work['generation'] != generation or work['stop_requested'] == 'cancel'
            old = self.db.execute('SELECT * FROM events WHERE run_id=? AND event_id=?', (run_id, event_id)).fetchone()
            if old:
                if old['payload'] != data:
                    raise StateError('Conflicting duplicate event')
                return {**dict(old), 'payload': payload}
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (run_id, event_id, data, int(stale), now()))
        return {'run_id': run_id, 'event_id': event_id, 'payload': payload, 'stale': bool(stale)}

    def finish_run(self, run_id, generation, outcome, detail):
        if outcome not in ('completed', 'failed', 'interrupted', 'transport_unknown'):
            raise StateError('Invalid provider terminal outcome')
        with self.tx():
            run, work = self._owned(run_id, generation)
            self.db.execute('UPDATE runs SET status=?,detail=?,updated_at=? WHERE id=?', (outcome, encoded(detail), now(), run_id))
            stop = work['stop_requested']
            if outcome == 'transport_unknown':
                status, reason, current, reserved = ('cancel_requested' if stop == 'cancel' else 'pause_requested' if stop == 'pause' else 'waiting'), 'recovery', run_id, 1
            elif stop == 'cancel':
                status, reason, current, reserved = 'cancelled', None, None, 0
            elif stop == 'pause' or outcome == 'interrupted':
                status, reason, current, reserved = 'paused', 'interrupted', None, 1
            else:
                nested = detail.get('detail') if isinstance(detail, dict) else None
                result = nested.get('result') if isinstance(nested, dict) else None
                decision = isinstance(result, dict) and result.get('outcome') == 'needs_decision'
                status, reason, current, reserved = 'waiting', ('decision' if decision else 'verification' if outcome == 'completed' else 'diagnosis'), None, 1
            self.db.execute('UPDATE work SET status=?,wait_reason=?,current_run_id=?,reserved=?,updated_at=? WHERE work_id=?',
                            (status, reason, current, reserved, now(), work['work_id']))
            self._audit(work['work_id'], 'run_terminal', {'run_id': run_id, 'outcome': outcome, 'status': status})
        return self.get_work(work['work_id'])

    def _stop(self, work_id, action):
        with self.tx():
            work = self.get_work(work_id)
            if work['status'] == 'cancelled' or work['stop_requested'] == 'cancel':
                return work
            if work['current_run_id']:
                status, reason, reserved = ('cancel_requested' if action == 'cancel' else 'pause_requested'), 'stop_confirmation', 1
            else:
                status, reason, reserved = ('cancelled' if action == 'cancel' else 'paused'), None, (0 if action == 'cancel' else work['reserved'])
            self.db.execute('UPDATE work SET status=?,wait_reason=?,stop_requested=?,reserved=?,updated_at=? WHERE work_id=?',
                            (status, reason, action, reserved, now(), work_id))
            self._audit(work_id, action + '_requested', {})
        return self.get_work(work_id)

    def pause(self, work_id):
        return self._stop(work_id, 'pause')

    def request_cancel(self, work_id):
        return self._stop(work_id, 'cancel')

    def resume(self, work_id):
        with self.tx():
            work = self.get_work(work_id)
            if work['status'] != 'paused' or work['current_run_id'] or work['stop_requested'] == 'cancel':
                raise StateError('Only paused work with no unresolved run can resume')
            self.db.execute("UPDATE work SET status='ready',wait_reason=NULL,stop_requested=NULL,updated_at=? WHERE work_id=?", (now(), work_id))
            self._audit(work_id, 'resumed', {})
        return self.get_work(work_id)

    def recover_run(self, run_id, confirmed_stopped, reason):
        if confirmed_stopped is not True or not isinstance(reason, str) or not reason.strip():
            raise StateError('Recovery needs confirmed termination and its observation')
        with self.tx():
            run = self._run(run_id)
            _, work = self._owned(run_id, run['generation'])
            status = 'cancelled' if work['stop_requested'] == 'cancel' else 'paused'
            self.db.execute("UPDATE runs SET status='interrupted',detail=?,updated_at=? WHERE id=?", (encoded({'recovery_observation': reason, 'previous_detail': run['detail']}), now(), run_id))
            self.db.execute('UPDATE work SET status=?,wait_reason=?,current_run_id=NULL,reserved=?,updated_at=? WHERE work_id=?',
                            (status, 'recovered', 0 if status == 'cancelled' else 1, now(), work['work_id']))
            self._audit(work['work_id'], 'confirmed_recovery', {'run_id': run_id, 'reason': reason})
        return self.get_work(work['work_id'])
