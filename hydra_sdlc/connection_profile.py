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


def admission_value(snapshot, reason):
    value = {'revision': snapshot['revision'], 'global_mode': snapshot['global_mode'],
             'project_overrides': dict(snapshot['projects']), 'gate_reason': reason}
    if snapshot.get('version') == 2:
        value['default_project_mode'] = 'stopped'
    return value
