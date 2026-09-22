"""Real child-process regressions; no GitHub calls or credentials required."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import bounded_process as bp
import github_client as dashboard
import reader_client as reader


class BoundedProcessTests(unittest.TestCase):
    def run_child(self, code, **kwargs):
        options = dict(timeout=2, stdout_limit=65536, stderr_limit=8192)
        options.update(kwargs)
        return bp.run_bounded([sys.executable, '-c', code], **options)

    def assert_stopped(self, code, exception, **kwargs):
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **options):
            child = real_popen(*args, **options)
            children.append(child)
            return child
        start = time.monotonic()
        with patch.object(bp.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaises(exception):
                self.run_child(code, **kwargs)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(len(children), 1)
        child = children[0]
        self.assertIsNotNone(child.returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
        self.assertTrue(child.stdout.closed and child.stderr.closed)
        if child.stdin:
            self.assertTrue(child.stdin.closed)

    def test_exact_byte_limits_and_nonzero_exit(self):
        result = self.run_child("import os; os.write(1,b'x'*65536); os.write(2,b'e'*8192); raise SystemExit(7)")
        self.assertEqual((len(result.stdout), len(result.stderr), result.returncode), (65536, 8192, 7))

    def test_stdout_one_byte_over_limit(self):
        self.assert_stopped("import os; os.write(1,b'x'*65537)", bp.OutputLimitExceeded)

    def test_stderr_one_byte_over_limit(self):
        self.assert_stopped("import os; os.write(2,b'e'*8193)", bp.OutputLimitExceeded)

    def test_unlimited_fast_output_on_each_pipe(self):
        for fd in (1, 2):
            with self.subTest(fd=fd):
                self.assert_stopped(f"import os,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN)\nwhile True: os.write({fd}, b'x'*4096)", bp.OutputLimitExceeded)

    def test_silent_timeout(self):
        self.assert_stopped('import time; time.sleep(30)', subprocess.TimeoutExpired, timeout=.15)

    def test_guard_failure_kills_silent_and_closed_pipe_children(self):
        for close in ('', 'os.close(1); os.close(2);'):
            calls = []
            def guard():
                calls.append(1)
                if len(calls) > 1:
                    raise RuntimeError('workspace budget exceeded')
            with self.subTest(close=close):
                self.assert_stopped('import os,time; ' + close + ' time.sleep(30)', RuntimeError, guard=guard)

    def test_continuous_output_still_obeys_deadline(self):
        self.assert_stopped("import os,time\nwhile True:\n os.write(1,b'x'); time.sleep(.005)", subprocess.TimeoutExpired, timeout=.15)

    def test_closed_pipes_do_not_bypass_deadline(self):
        self.assert_stopped('import os,time; os.close(1); os.close(2); time.sleep(30)', subprocess.TimeoutExpired, timeout=.15)

    def test_bidirectional_input_and_output(self):
        payload = b'p' * (512 * 1024)
        result = self.run_child("import os,sys; os.write(2,b'e'*8192); os.write(1,b'o'*65536); data=sys.stdin.buffer.read(); sys.exit(0 if data==b'p'*524288 else 3)", input=payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'o'*65536)
        self.assertEqual(result.stderr, b'e'*8192)

    def test_child_not_reading_input_cannot_block_overflow(self):
        self.assert_stopped("import os,time; os.write(2,b'e'*8193); time.sleep(30)", bp.OutputLimitExceeded, input=b'x'*524288)

    def test_child_closing_stdin_early(self):
        result = self.run_child("import os; os.close(0); os.write(1,b'ok')", input=b'x'*524288)
        self.assertEqual(result.stdout, b'ok')

    def test_descendant_holding_pipes_is_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            code = ("import subprocess,sys,pathlib; "
                    "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid))")
            self.assert_stopped(code, subprocess.TimeoutExpired, timeout=.5)
            pid = int(pidfile.read_text())
            # Orphan reaping belongs to init; a zombie has stopped executing.
            for _ in range(100):
                stat = Path(f'/proc/{pid}/stat')
                if not stat.exists() or stat.read_text().split()[2] == 'Z':
                    break
                time.sleep(.01)
            else:
                self.fail('descendant remained alive after deadline')

    def test_empty_and_missing_command(self):
        self.assertEqual(self.run_child('pass', stdout_limit=0, stderr_limit=0).stdout, b'')
        with self.assertRaises(FileNotFoundError):
            bp.run_bounded(['/nonexistent/omarchy-test-command'], timeout=1, stdout_limit=1)

    def test_both_clients_enforce_limits_with_real_children(self):
        with tempfile.TemporaryDirectory() as directory:
            gh = Path(directory) / 'gh'
            gh.write_text(f'#!{sys.executable}\nimport os\nos.write(int(os.environ["TEST_FD"]), b"x" * 8193)\n')
            gh.chmod(0o755)
            for fd in (1, 2):
                with self.subTest(fd=fd), patch.dict(os.environ, PATH=directory, TEST_FD=str(fd)), patch.object(dashboard, 'MAX_OUTPUT_BYTES', 8192), patch.object(reader, 'LIMIT', 8192):
                    for call in (lambda: dashboard.run_command(['gh']), lambda: reader.transport([])):
                        with self.assertRaises(dashboard.GhError) as error:
                            call()
                        self.assertEqual(error.exception.kind, 'response-limit')

    def test_clients_preserve_error_mapping(self):
        for module, call in ((dashboard, lambda: dashboard.run_command(['gh'])), (reader, lambda: reader.transport([]))):
            for error, kind in ((FileNotFoundError(), 'missing-gh'), (subprocess.TimeoutExpired('gh', 1), 'timeout')):
                with self.subTest(module=module.__name__, kind=kind), patch.object(module, 'run_bounded', side_effect=error):
                    with self.assertRaises(dashboard.GhError) as caught:
                        call()
                    self.assertEqual(caught.exception.kind, kind)


if __name__ == '__main__':
    unittest.main()
