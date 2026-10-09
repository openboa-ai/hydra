import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hydra_sdlc.cli import main


class CliFailureTests(unittest.TestCase):
    def check_structured_database_error(self, path, expected_error):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--state', str(path), 'status'])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), '')
        error = json.loads(err.getvalue())
        self.assertEqual(error['error'], expected_error)
        self.assertNotIn(str(path), err.getvalue())
        self.assertNotIn('Traceback', err.getvalue())

    def test_directory_is_not_a_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'not-a-database'
            path.mkdir()
            self.check_structured_database_error(path, 'OperationalError')

    def test_unreadable_database_format_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite3'
            path.write_bytes(b'not a sqlite database')
            self.check_structured_database_error(path, 'StateError')


if __name__ == '__main__':
    unittest.main()
