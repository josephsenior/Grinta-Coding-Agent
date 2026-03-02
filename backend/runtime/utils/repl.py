"""Stateful REPL implementation for runtime code execution validation.

Provides a persistent Python REPL environment that allows agents to execute
code snippets and maintain state across multiple calls.
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
import queue
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger
from backend.events.observation import Observation, ErrorObservation
from backend.events.observation.commands import CmdOutputMetadata, CmdOutputObservation

if TYPE_CHECKING:
    from backend.runtime.utils.unified_shell import UnifiedShellSession

class PythonREPL:
    """A stateful Python REPL environment.
    
    This REPL runs as a persistent subprocess, allowing state (variables, 
    imports, functions) to be maintained across multiple execution calls.
    """

    def __init__(self, work_dir: str, timeout: int = 30):
        self.work_dir = work_dir
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self.output_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._initialized = False

    def start(self):
        """Start the Python REPL subprocess."""
        if self._initialized:
            return

        # Start python in unbuffered mode with a simple prompt
        # We use a unique sentinel to detect end of output
        self.sentinel = f"REPL_END_{os.urandom(8).hex()}"
        
        # Command to start python REPL
        cmd = [
            sys.executable,
            "-u",  # Unbuffered
            "-i",  # Interactive
            "-q",  # Quiet
        ]

        self.process = subprocess.Popen(
            cmd,
            cwd=self.work_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
        )

        # Start output reader thread
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

        # Set up the REPL environment
        self._setup_env()
        self._initialized = True
        logger.info("Python REPL started in %s", self.work_dir)

    def _setup_env(self):
        """Initial setup of the REPL environment."""
        setup_code = [
            "import sys",
            "import os",
            f"os.chdir(r'{self.work_dir}')",
            "sys.path.insert(0, os.getcwd())",
            "print('REPL_READY')"
        ]
        for line in setup_code:
            self.execute_raw(line)
        
        # Wait for ready signal
        self._wait_for_sentinel("REPL_READY")

    def _read_output(self):
        """Read output from the subprocess and put into queue."""
        if not self.process or not self.process.stdout:
            return

        while not self._stop_event.is_set():
            line = self.process.stdout.readline()
            if not line:
                break
            self.output_queue.put(line)

    def execute_raw(self, code: str):
        """Send raw code to the REPL stdin."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("REPL process not started")
        
        self.process.stdin.write(code + "\n")
        self.process.stdin.flush()

    def _wait_for_sentinel(self, sentinel: str, timeout: int | None = None) -> str:
        """Wait for a specific sentinel string in the output."""
        output: list[str] = []
        start_time = time.time()
        effective_timeout = timeout or self.timeout

        while True:
            if time.time() - start_time > effective_timeout:
                return "".join(output) + f"\n[Timeout waiting for {sentinel}]"
            
            try:
                line = self.output_queue.get(timeout=0.1)
                if sentinel in line:
                    # Found it, but might have more output before it in the same line
                    # or the line itself might be the sentinel
                    break
                output.append(line)
            except queue.Empty:
                continue
        
        return "".join(output)

    def run_code(self, code: str) -> str:
        """Run a block of code and return the output."""
        if not self._initialized:
            self.start()

        # Wrap code to ensure we get a sentinel back
        # We use a multi-line string and exec() to handle complex blocks
        sentinel_id = os.urandom(4).hex()
        start_sentinel = f"START_{sentinel_id}"
        end_sentinel = f"END_{sentinel_id}"
        
        # We use print statements to mark boundaries
        full_code = f"print('{start_sentinel}')\n{code}\nprint('{end_sentinel}')"
        
        self.execute_raw(full_code)
        
        # First wait for start sentinel to clear previous junk
        self._wait_for_sentinel(start_sentinel)
        
        # Then capture everything until end sentinel
        return self._wait_for_sentinel(end_sentinel).strip()

    def stop(self):
        """Stop the REPL process."""
        self._stop_event.set()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._initialized = False

class REPLManager:
    """Manages REPL sessions for different working directories."""
    
    def __init__(self):
        self._repls: dict[str, PythonREPL] = {}

    def get_repl(self, work_dir: str) -> PythonREPL:
        if work_dir not in self._repls:
            self._repls[work_dir] = PythonREPL(work_dir)
            self._repls[work_dir].start()
        return self._repls[work_dir]

    def close_all(self):
        for repl in self._repls.values():
            repl.stop()
        self._repls.clear()

# Global REPL manager
repl_manager = REPLManager()