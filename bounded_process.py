"""Bounded POSIX subprocess I/O for GitHub CLI requests."""
import os
import selectors
import signal
import subprocess
import time


class OutputLimitExceeded(RuntimeError):
    pass


def run_bounded(command, *, timeout, stdout_limit, stderr_limit=8192,
                input=None, env=None):
    """Drain both pipes fairly; never retain output beyond either byte ceiling.

    Stdin participates in the same nonblocking loop so a child producing output
    before reading a large request cannot deadlock. The deadline also covers a
    child that closes its pipes but keeps running, or descendants holding pipes.
    """
    if timeout <= 0 or stdout_limit < 0 or stderr_limit < 0:
        raise ValueError('Invalid process limits')
    deadline = time.monotonic() + timeout
    result = {'stdout': bytearray(), 'stderr': bytearray()}
    limits = {'stdout': stdout_limit, 'stderr': stderr_limit}
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               bufsize=0, start_new_session=True, env=env)
    try:
        with selectors.DefaultSelector() as selector:
            for name in result:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            offset = 0
            if input:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                for key, _ in selector.select(remaining):
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(command, timeout)
                    pipe, name = key.fileobj, key.data
                    if name == 'stdin':
                        try:
                            offset += os.write(pipe.fileno(), input[offset:offset + 65536])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            offset = len(input)
                        if offset == len(input):
                            selector.unregister(pipe)
                            pipe.close()
                        continue
                    # One extra byte detects overflow without allocating a full
                    # untrusted chunk once the buffer reaches its ceiling.
                    available = limits[name] - len(result[name])
                    try:
                        chunk = os.read(pipe.fileno(), min(65536, available + 1))
                    except BlockingIOError:
                        continue
                    if len(chunk) > available:
                        raise OutputLimitExceeded(name)
                    if chunk:
                        result[name].extend(chunk)
                    else:
                        selector.unregister(pipe)
                        pipe.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            process.wait(timeout=remaining)
        return subprocess.CompletedProcess(command, process.returncode,
                                           bytes(result['stdout']), bytes(result['stderr']))
    finally:
        # The fresh session isolates this request's process group. SIGKILL also
        # handles children ignoring SIGTERM and descendants keeping pipes open.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            process.wait()
