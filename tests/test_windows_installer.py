"""Exercise the Ubuntu installer without network access or system changes."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
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
    if os.environ.get('PW_TEST_REMOTE'):
        if 'fetch' in args:
            args[args.index('origin')] = os.environ['PW_TEST_REMOTE']
        binary = os.environ['PW_TEST_GIT']
        os.execv(binary, [binary, *args])
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
    elif args[2] == 'remote':
        print('wrong-origin' if failure == 'origin' else 'https://github.com/Zhengyi-Yan/plumewatch.git')
    elif args[2] == 'symbolic-ref':
        print('main')
    elif args[2] == 'rev-parse':
        print('a' * 40)
    elif args[2] != 'fetch':
        raise RuntimeError('Unexpected mocked Git command: ' + repr(args))
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


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash') and shutil.which('git'),
                     'requires Unix/WSL with Bash and Git')
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

    def run_setup(self, failure='', answer=''):
        return subprocess.run(['bash', str(ROOT / 'scripts/install_wsl.sh')],
                              env=dict(self.env, PW_TEST_FAILURE=failure),
                              input=answer, capture_output=True, text=True, timeout=15)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def git(self, folder, *args):
        return subprocess.check_output([self.real_git, '-C', str(folder), *args],
                                       env=self.env, text=True, stderr=subprocess.PIPE).strip()

    def make_git_checkout(self):
        """A real old checkout and local upstream; only downloads/system tools are mocked."""
        self.real_git = shutil.which('git')
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.upstream = self.root / 'upstream'
        self.upstream.mkdir()
        self.git(self.upstream, 'init', '-b', 'main')
        self.git(self.upstream, 'config', 'user.name', 'Installer test')
        self.git(self.upstream, 'config', 'user.email', 'installer@example.invalid')
        files = ['app.py', 'requirements.txt', 'experiments/unet/requirements.txt',
                 'data/processed/multiclass_rf_v2_20260930/model.pkl',
                 'data/processed/svm_rbf_20261001/model.pkl',
                 'experiments/unet/outputs/expanded_all_data_20260930/model.pt',
                 'hutt-test/hutt_20210723_full_scene_v1.tif']
        for name in files:
            path = self.upstream / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('old version')
        (self.upstream / '.gitignore').write_text('.venv/\n*.local\n')
        self.git(self.upstream, 'add', '.')
        self.git(self.upstream, 'commit', '-m', 'Old installed version')
        self.remote = self.root / 'remote.git'
        self.git(self.root, 'clone', '--bare', str(self.upstream), str(self.remote))
        self.repo = self.home / 'projects/plumewatch'
        self.git(self.root, 'clone', str(self.remote), str(self.repo))
        self.git(self.repo, 'remote', 'set-url', 'origin', 'https://github.com/Zhengyi-Yan/plumewatch.git')
        self.git(self.repo, 'config', 'user.name', 'Installer test')
        self.git(self.repo, 'config', 'user.email', 'installer@example.invalid')
        self.old_commit = self.git(self.repo, 'rev-parse', 'HEAD')
        for name in ['.venv', 'experiments/unet/.venv']:
            folder = self.repo / name
            (folder / 'bin').mkdir(parents=True)
            (folder / 'bin/python').symlink_to(self.env['PW_TEST_MOCK'])
            (folder / 'keep.local').write_text('existing environment')
        self.env.update(PW_TEST_REMOTE=str(self.remote), PW_TEST_GIT=self.real_git)

    def advance_remote(self, ignored_collision=False):
        (self.upstream / 'app.py').write_text('new version')
        (self.upstream / 'timeline.py').write_text('Time series is available')
        self.git(self.upstream, 'add', '.')
        if ignored_collision:
            (self.upstream / 'data.local').write_text('upstream data')
            self.git(self.upstream, 'add', '-f', 'data.local')
        self.git(self.upstream, 'commit', '-m', 'New version with time series')
        self.git(self.upstream, 'push', str(self.remote), 'main')
        return self.git(self.upstream, 'rev-parse', 'HEAD')

    def assert_no_code_update(self):
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), self.old_commit)
        self.assertFalse(any('merge' in row for row in self.commands()))
        self.assertFalse(any(row[0] == 'uv' for row in self.commands()))

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

    def test_real_git_updates_only_after_yes_and_keeps_environments(self):
        self.make_git_checkout()
        latest = self.advance_remote()
        result = self.run_setup(answer='yes\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), latest)
        self.assertIn('An update is available', result.stdout)
        self.assertEqual((self.repo / 'timeline.py').read_text(), 'Time series is available')
        for name in ['.venv', 'experiments/unet/.venv']:
            self.assertEqual((self.repo / name / 'keep.local').read_text(), 'existing environment')
        self.assertFalse(any('reset' in row or 'stash' in row for row in self.commands()))
        again = self.run_setup()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('already up to date', again.stdout)
        self.assertNotIn('Update the installed code now?', again.stdout)

    def test_real_git_decline_default_and_eof_keep_old_version(self):
        self.make_git_checkout()
        self.advance_remote()
        for answer in ['n\n', '\n', '']:
            with self.subTest(answer=answer):
                result = self.run_setup(answer=answer)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Update declined', result.stdout)
                self.assert_no_code_update()

    def test_real_git_local_edits_and_untracked_files_are_not_overwritten(self):
        self.make_git_checkout()
        self.advance_remote()
        note = self.repo / 'my-notes.txt'
        note.write_text('keep my notes')
        result = self.run_setup(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('local changes or untracked files', result.stderr)
        self.assertEqual(note.read_text(), 'keep my notes')
        self.assert_no_code_update()
        note.unlink()
        (self.repo / 'app.py').write_text('my staged edits')
        self.git(self.repo, 'add', 'app.py')
        result = self.run_setup(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.repo / 'app.py').read_text(), 'my staged edits')
        self.assert_no_code_update()

    def test_real_git_local_commits_and_diverged_history_are_not_merged(self):
        self.make_git_checkout()
        (self.repo / 'local.txt').write_text('my commit')
        self.git(self.repo, 'add', 'local.txt')
        self.git(self.repo, 'commit', '-m', 'Local work')
        self.old_commit = self.git(self.repo, 'rev-parse', 'HEAD')
        for diverged in [False, True]:
            with self.subTest(diverged=diverged):
                if diverged:
                    self.advance_remote()
                result = self.run_setup(answer='y\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('differing history', result.stderr)
                self.assertEqual((self.repo / 'local.txt').read_text(), 'my commit')
                self.assert_no_code_update()

    def test_real_git_other_branch_and_detached_head_are_left_alone(self):
        self.make_git_checkout()
        self.advance_remote()
        self.git(self.repo, 'checkout', '-b', 'my-work')
        for branch in ['my-work', 'HEAD']:
            with self.subTest(branch=branch):
                if branch == 'HEAD':
                    self.git(self.repo, 'checkout', '--detach')
                result = self.run_setup(answer='y\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must be on main', result.stderr)
                self.assertEqual(self.git(self.repo, 'rev-parse', '--abbrev-ref', 'HEAD'), branch)
                self.assert_no_code_update()

    def test_real_git_fetch_failure_stops_without_using_stale_refs(self):
        self.make_git_checkout()
        self.advance_remote()
        self.remote.rename(self.root / 'remote-offline.git')
        result = self.run_setup(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Could not check GitHub', result.stderr)
        self.assert_no_code_update()

    def test_real_git_ignored_file_collision_preserves_local_data(self):
        self.make_git_checkout()
        self.advance_remote(ignored_collision=True)
        data = self.repo / 'data.local'
        data.write_text('valuable local data')
        result = self.run_setup(answer='y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data.read_text(), 'valuable local data')
        self.assertEqual((self.repo / 'app.py').read_text(), 'old version')
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), self.old_commit)

    def test_real_git_changes_while_prompt_is_open_stop_the_update(self):
        self.make_git_checkout()
        self.advance_remote()
        with subprocess.Popen(['bash', str(ROOT / 'scripts/install_wsl.sh')], env=self.env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            output = b''
            deadline = time.monotonic() + 10
            while b'[y/N]' not in output:
                if time.monotonic() > deadline:
                    process.kill()
                    self.fail('Installer did not reach update confirmation')
                if select.select([process.stdout], [], [], .1)[0]:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        self.fail('Installer stopped before confirmation: ' + process.stderr.read().decode())
                    output += chunk
            (self.repo / 'app.py').write_text('edited while waiting')
            _, error = process.communicate(b'y\n', timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('checkout changed while waiting', error.decode())
        self.assertEqual((self.repo / 'app.py').read_text(), 'edited while waiting')
        self.assert_no_code_update()


if __name__ == '__main__':
    unittest.main()
