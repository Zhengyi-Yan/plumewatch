"""Exercise the Ubuntu installer without network access or system changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''#!PYTHON
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['PW_TEST_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
failure = os.environ.get('PW_TEST_FAILURE', '')
if name == 'id':
    print('0' if failure == 'root' else '1000')
elif name == 'uname':
    print('aarch64' if failure == 'arm' else 'x86_64')
elif name == 'sudo':
    sys.exit(1 if failure == 'apt' else 0)
elif name == 'git':
    if args[0] == 'clone':
        if failure == 'clone': sys.exit(1)
        repo = pathlib.Path(args[-1]); repo.mkdir(parents=True)
        (repo / '.git').mkdir()
        for path in ['app.py', 'requirements.txt', 'experiments/unet/requirements.txt',
                     'data/processed/multiclass_rf_v2_20260930/model.pkl',
                     'data/processed/svm_rbf_20261001/model.pkl',
                     'experiments/unet/outputs/expanded_all_data_20260930/model.pt',
                     'hutt-test/hutt_20210723_full_scene_v1.tif']:
            target = repo / path; target.parent.mkdir(parents=True, exist_ok=True)
            if failure != 'model' or not path.endswith('model.pt'):
                target.write_text('fixture')
    else:
        print('wrong-origin' if failure == 'origin' else 'https://github.com/Zhengyi-Yan/plumewatch.git')
elif name == 'uv':
    if failure == 'packages' and args[:2] == ['pip', 'install']: sys.exit(1)
    if args[0] == 'venv':
        target = pathlib.Path(args[-1]) / 'bin/python'
        target.parent.mkdir(parents=True)
        target.symlink_to(os.environ['PW_TEST_MOCK'])
elif name == 'python':
    if failure == 'verify' and args[0].endswith('test_processing.py'): sys.exit(1)
    if failure == 'version' and 'version_info' in ' '.join(args): sys.exit(1)
elif name == 'curl':
    if failure == 'download': sys.exit(1)
    pathlib.Path(args[-1]).write_text('cp "$PW_TEST_MOCK" "$UV_INSTALL_DIR/uv"\nchmod +x "$UV_INSTALL_DIR/uv"\n')
'''


@unittest.skipUnless(shutil.which('bash'), 'requires bash')
class WindowsUbuntuInstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plumewatch setup ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home with spaces'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.uv = self.home / '.local/bin/uv'
        self.uv.parent.mkdir(parents=True)
        mock = self.bin / 'mock'
        mock.write_text(MOCK.replace('PYTHON', sys.executable, 1))
        mock.chmod(0o755)
        for name in ['id', 'uname', 'sudo', 'git', 'curl']:
            (self.bin / name).symlink_to(mock)
        self.uv.symlink_to(mock)
        self.log = self.root / 'commands.jsonl'
        self.env = dict(os.environ, HOME=str(self.home), PATH=f'{self.bin}:/usr/bin:/bin',
                        PW_TEST_LOG=str(self.log), PW_TEST_MOCK=str(mock))

    def run_setup(self, failure=''):
        return subprocess.run(['bash', str(ROOT / 'scripts/install_wsl.sh')],
                              env=dict(self.env, PW_TEST_FAILURE=failure),
                              capture_output=True, text=True)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_fresh_install_and_retry_keep_files_and_use_cpu(self):
        first = self.run_setup()
        self.assertEqual(first.returncode, 0, first.stderr)
        repo = self.home / 'projects/plumewatch'
        marker = repo / 'user-file'; marker.write_text('keep me')
        second = self.run_setup()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(marker.read_text(), 'keep me')
        commands = self.commands()
        self.assertEqual(sum(row[:2] == ['git', 'clone'] for row in commands), 1)
        self.assertEqual(sum(row[:2] == ['uv', 'venv'] for row in commands), 2)
        self.assertFalse(any('reset' in row or 'pull' in row for row in commands))
        self.assertIn(['uv', 'pip', 'install', '--python', 'experiments/unet/.venv/bin/python',
                       '--torch-backend', 'cpu', '--only-binary', ':all:', '-r',
                       'experiments/unet/requirements.txt'], commands)
        self.assertIn(['python', 'tests/test_processing.py',
                       'TwoModelWorkflowTest.test_real_checkpoints_preserve_grid_and_export_three_classes', '-v'], commands)

    def test_failures_never_report_success(self):
        for failure in ['root', 'arm', 'apt', 'clone', 'packages', 'verify', 'model', 'version']:
            with self.subTest(failure=failure):
                # Give each scenario a genuinely empty target.
                shutil.rmtree(self.home / 'projects', ignore_errors=True)
                result = self.run_setup(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('checks passed', result.stdout)

    def test_download_failure_does_not_run_downloaded_script(self):
        self.uv.unlink()
        result = self.run_setup('download')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.uv.exists())

    def test_existing_other_folder_is_preserved(self):
        repo = self.home / 'projects/plumewatch'
        repo.mkdir(parents=True)
        marker = repo / 'important.txt'; marker.write_text('keep')
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), 'keep')
        self.assertFalse(any(row[:2] == ['git', 'clone'] for row in self.commands()))

    def test_wrong_origin_and_failed_verification_can_be_retried(self):
        self.assertEqual(self.run_setup().returncode, 0)
        self.assertNotEqual(self.run_setup('origin').returncode, 0)
        self.assertNotEqual(self.run_setup('verify').returncode, 0)
        self.assertEqual(self.run_setup().returncode, 0)


if __name__ == '__main__':
    unittest.main()
