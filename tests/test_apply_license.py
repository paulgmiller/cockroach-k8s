import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('license_helper', Path(__file__).resolve().parents[1] / 'scripts/apply-license.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
KEY = 'crl-0-example+license/key'
PODS = json.dumps({'items': [{'metadata': {'name': 'db-pod'}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]})


class LicenseTests(unittest.TestCase):
    def invoke(self, replies):
        output = io.StringIO()
        with patch.object(helper.sys, 'argv', ['apply-license.py', '--store']), patch.object(helper.sys, 'stdin', io.StringIO(KEY)), patch.object(helper, 'run', side_effect=replies) as run, contextlib.redirect_stdout(output):
            helper.main()
        self.assertNotIn(KEY, output.getvalue())
        for call in run.call_args_list:
            self.assertNotIn(KEY, ' '.join(call.args[0]))
        return run

    def test_save_only_after_database_acceptance_and_readback(self):
        run = self.invoke([PODS, '', 'enterprise.license\n' + KEY + '\n', ''])
        self.assertIn('SET CLUSTER SETTING', run.call_args_list[1].kwargs['input'])
        self.assertIn('--server-side', run.call_args_list[3].args[0])
        secret = json.loads(run.call_args_list[3].kwargs['input'])
        self.assertEqual(secret['stringData']['license'], KEY)

    def test_rejected_license_does_not_replace_secret(self):
        with patch.object(helper.sys, 'argv', ['apply-license.py', '--store']), patch.object(helper.sys, 'stdin', io.StringIO(KEY)), patch.object(helper, 'run', side_effect=[PODS, RuntimeError('rejected')]) as run:
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                helper.main()
        self.assertEqual(run.call_count, 2)

    def test_missing_optional_secret_skips_sql(self):
        with patch.object(helper.sys, 'argv', ['apply-license.py', '--if-present']), patch.object(helper, 'run', return_value='') as run, contextlib.redirect_stdout(io.StringIO()):
            helper.main()
        self.assertEqual(run.call_count, 1)

    def test_errors_redact_license(self):
        result = SimpleNamespace(returncode=1, stderr='ERROR: invalid license ' + KEY)
        with patch.object(helper.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as error:
                helper.run(['kubectl'])
        self.assertNotIn(KEY, str(error.exception))
        self.assertIn('[REDACTED]', str(error.exception))


if __name__ == '__main__':
    unittest.main()
