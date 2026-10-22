"""Connection declarations and public admission facts contain no provider code."""


def declarations(cfg, repos):
    if 'connection_schema' not in cfg:
        if 'project_connections' in cfg:
            raise ValueError('Connection profile required')
        return None
    if type(cfg['connection_schema']) is not int or cfg['connection_schema'] != 1:
        raise ValueError('Unknown connection profile')
    rows = cfg.get('project_connections', {})
    if type(rows) is not dict or len(rows) > len(repos):
        raise ValueError('Invalid connection declarations')
    result = {}
    for repository, row in rows.items():
        if (repository not in repos or type(row) is not dict
                or set(row) - {'desired', 'native_project_id'}
                or row.get('desired') not in {'connected', 'disconnect_requested'}):
            raise ValueError('Invalid connection declaration')
        if 'native_project_id' in row:
            locator = row['native_project_id']
            if (type(locator) is not str or not 1 <= len(locator) <= 256
                    or any(ord(char) < 32 or ord(char) == 127 for char in locator)):
                raise ValueError('Invalid native project locator')
        result[repository] = dict(row)
    return result


def default_project_mode(snapshot):
    return 'stopped' if snapshot.get('version') == 2 else 'running'


def connection_reason(configuration, repository):
    if repository is None or configuration.get('connection_schema') != 1:
        return None
    desired = configuration.get('project_connections', {}).get(repository, {}).get('desired')
    if desired == 'disconnect_requested':
        return 'project_disconnect_requested'
    return None if desired == 'connected' else 'project_connection_unprepared'


def restrictive_connection_change(before, after):
    """Only existing connected declarations may become disconnect requests."""
    if before is None or ({k: v for k, v in before.items() if k != 'project_connections'}
            != {k: v for k, v in after.items() if k != 'project_connections'}):
        return False
    old, current = before.get('project_connections', {}), after.get('project_connections', {})
    if set(old) != set(current):
        return False
    for repo, previous in old.items():
        desired = current[repo]
        if ({k: v for k, v in previous.items() if k != 'desired'}
                != {k: v for k, v in desired.items() if k != 'desired'}):
            return False
        if (previous['desired'] != desired['desired']
                and (previous['desired'], desired['desired']) != ('connected', 'disconnect_requested')):
            return False
    return True


def public_snapshot(snapshot):
    result = {key: snapshot[key] for key in ('version', 'revision', 'global_mode', 'updated_at')}
    result['projects'] = dict(snapshot['projects'])
    if snapshot.get('version') == 2:
        result['default_project_mode'] = 'stopped'
    return result


def admission_value(snapshot, reason):
    value = {'revision': snapshot['revision'], 'global_mode': snapshot['global_mode'],
             'project_overrides': dict(snapshot['projects']), 'gate_reason': reason}
    if snapshot.get('version') == 2:
        value['default_project_mode'] = 'stopped'
    return value
