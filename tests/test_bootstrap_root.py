import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap', Path(__file__).resolve().parents[1] / 'scripts/bootstrap-root.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def reply(value=None, code=0):
    return SimpleNamespace(returncode=code, stdout=json.dumps(value) if value is not None else '')


class RootSecretTests(unittest.TestCase):
    def invoke(self, replies):
        capture = io.StringIO()
        with patch.object(bootstrap.subprocess, 'run', side_effect=replies) as run, contextlib.redirect_stdout(capture):
            password = bootstrap.ensure_root_secret('test')
        self.assertNotIn(password, capture.getvalue())
        return password, run

    def test_new_password_is_stored_with_matching_sql(self):
        password, run = self.invoke([reply(), reply(), reply()])
        obj = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(obj['stringData']['password'], password)
        self.assertEqual(obj['stringData']['init.sql'], "ALTER USER root WITH PASSWORD '" + password + "';\n")
        self.assertGreaterEqual(len(password), 64)
        self.assertNotIn(password, ' '.join(run.call_args.args[0]))

    def test_existing_password_is_reused_without_writing(self):
        password = 'existing-secret-value'
        sql = "ALTER USER root WITH PASSWORD '" + password + "';\n"
        stored = {'data': {key: base64.b64encode(value.encode()).decode() for key, value in {'password': password, 'init.sql': sql}.items()}}
        actual, run = self.invoke([reply(stored)])
        self.assertEqual(password, actual)
        self.assertEqual(run.call_count, 1)

    def test_missing_secret_on_initialized_cluster_does_not_rotate(self):
        cluster = {'status': {'conditions': [{'type': 'Initialized', 'status': 'True'}]}}
        with patch.object(bootstrap.subprocess, 'run', side_effect=[reply(), reply(cluster)]) as run:
            with self.assertRaisesRegex(RuntimeError, 'restore it'):
                bootstrap.ensure_root_secret('test')
        self.assertEqual(run.call_count, 2)

    def test_inconsistent_existing_secret_is_not_overwritten(self):
        stored = {'data': {'password': base64.b64encode(b'existing-password').decode(), 'init.sql': base64.b64encode(b'wrong SQL').decode()}}
        with patch.object(bootstrap.subprocess, 'run', return_value=reply(stored)) as run:
            with self.assertRaisesRegex(RuntimeError, 'refusing to replace'):
                bootstrap.ensure_root_secret('test')
        self.assertEqual(run.call_count, 1)

    def test_read_failure_does_not_generate_password(self):
        with patch.object(bootstrap.subprocess, 'run', return_value=reply(code=1)) as run:
            with self.assertRaisesRegex(RuntimeError, 'Cannot read'):
                bootstrap.ensure_root_secret('test')
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
