"""Current caller, installation and provider binding for bounded workflow commands."""
from pathlib import Path

from . import control_commands as c
from .control import control_from_config, load_host_config
from .operations import OperationDenied
from .runtime_identity import capture_runtime_identity


class WorkflowBinding:
    def __init__(self, config_path, command, context_provider, github, controller,
                 operation, *, native_profile=False, reason='verification_binding_mismatch'):
        self.config_path, self.command = config_path, command
        self.context_provider, self.github, self.controller = context_provider, github, controller
        self.operation, self.native_profile, self.reason = operation, native_profile, reason
        self.runtime, self.epoch = capture_runtime_identity(), None

    def validate(self):
        unavailable = False
        try:
            cfg = load_host_config(self.config_path)
            control = control_from_config(cfg)
            self.runtime = capture_runtime_identity(cfg, control)
        except (OSError, ValueError, TypeError, OperationDenied):
            unavailable = True
            self.runtime = capture_runtime_identity()
        current, reason = c._context(self.context_provider, self.command)
        self.epoch = current.binding_epoch if current else None
        if unavailable:
            raise OperationDenied('host_config_unavailable')
        if reason:
            raise OperationDenied(reason)
        if self.native_profile and current.surface != 'native':
            raise OperationDenied('unsupported_reply_profile')
        expected, target = self.command['expected'], self.command['target']
        if self.operation not in current.operations or target['repository_id'] not in current.repository_ids:
            raise OperationDenied('authority_denied')
        if expected['runtime_key'] is None or expected['admission_revision'] is None:
            raise OperationDenied('precondition_required')
        key = c._runtime_key(self.runtime)
        if (key is None or key != expected['runtime_key'] or current.config_digest is not None
                and current.config_digest != self.runtime['config_digest']):
            raise OperationDenied('runtime_unavailable' if key is None else 'stale_runtime')
        controller, runner = self.controller, self.controller.runner
        loaded = getattr(controller, 'runtime_identity', None)
        providers = ('storage_provider', 'lifecycle_provider')
        if (loaded is not None and (type(loaded) is not dict
                or loaded.get('config_digest') != self.runtime['config_digest'])
                or loaded is None and any(cfg.get(name) is not None
                    or getattr(runner.workspace, name, None) is not None for name in providers)):
            raise OperationDenied(self.reason)
        if (runner.github is not self.github or runner.host != cfg['host_alias']
                or tuple(controller.repos) != tuple(cfg['repos'])
                or Path(controller.lock_path).absolute() != Path(cfg['lock_path'])
                or runner.operations is None
                or runner.operations.control_lock_path != control.control_lock_path
                or runner.operations.repos != control.repos
                or Path(runner.workspace.root).absolute() != Path(cfg['workspace_root'])):
            raise OperationDenied(self.reason)
        return cfg, control, current
