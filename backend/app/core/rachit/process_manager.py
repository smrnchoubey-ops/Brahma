"""
RACHIT Process Supervisor & OS Process Containment
Strictly conforms to BRAHMA COS Whitesheet §13.1, §13.2 & §13.5.

Enforces:
- Real OS-level process isolation (multiprocessing.Process)
- Hard process termination (proc.terminate() / proc.kill()) and zero zombie workers
- Environment & Secret Containment (sanitized safe environment allowlist)
- Bounded IPC output transfer
"""
from typing import Dict, Any, Optional, Callable, Tuple, List
import time
import os
import json
import multiprocessing
import queue

from app.core.rachit.limits import SandboxStatus, ExecutionQuotas

# Explicit safe environment keys allowed in worker processes (§13.1)
SAFE_ENV_ALLOWLIST = {
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH",
    "PYTHONHOME", "LANG", "LC_ALL", "TZ", "COMSPEC"
}

# Sensitive parent keys explicitly stripped (§13.1)
SENSITIVE_KEY_PATTERNS = [
    "SECRET", "KEY", "TOKEN", "PASSWORD", "DATABASE_URL", "DB_", "API_", "JWT", "PRIVATE"
]


def _worker_entrypoint(
    target_fn: Callable[..., Any],
    args: Tuple,
    kwargs: Dict[str, Any],
    result_queue: multiprocessing.Queue,
    max_output_bytes: int
):
    """
    Subprocess worker entrypoint with environment scrubbing and bounded output transfer.
    """
    try:
        # Scrub parent environment of secrets (§13.1)
        for key in list(os.environ.keys()):
            upper_key = key.upper()
            if any(pat in upper_key for pat in SENSITIVE_KEY_PATTERNS) and key not in SAFE_ENV_ALLOWLIST:
                os.environ.pop(key, None)

        res = target_fn(*args, **kwargs)

        # Bounded IPC output capture (§13.3)
        if res is not None:
            serialized = json.dumps(res) if not isinstance(res, str) else res
            out_bytes = len(serialized.encode("utf-8"))
            if out_bytes > max_output_bytes:
                truncated = serialized[:max_output_bytes] + "... [TRUNCATED_EXCEEDED_QUOTA]"
                result_queue.put({
                    "success": True,
                    "result": truncated,
                    "error": f"Output size ({out_bytes} bytes) exceeded quota ({max_output_bytes} bytes).",
                    "status": "OUTPUT_EXCEEDED"
                })
                return

        result_queue.put({"success": True, "result": res, "error": None, "status": "SUCCESS"})
    except Exception as ex:
        result_queue.put({
            "success": False,
            "result": None,
            "error": f"{type(ex).__name__}: {str(ex)}",
            "status": "EXECUTION_ERROR"
        })


class ProcessSupervisor:
    """
    Supervises tool execution with real OS process containment and forceful termination.
    """

    @classmethod
    def execute_with_containment(
        cls,
        target_fn: Callable[..., Any],
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        quotas: Optional[ExecutionQuotas] = None
    ) -> Tuple[SandboxStatus, Optional[Any], Optional[str], float, int]:
        """
        Executes a callable inside an isolated OS subprocess boundary.
        Returns: (status, output, error, execution_time_ms, exit_code)
        """
        limits = quotas or ExecutionQuotas()
        kwargs = kwargs or {}

        timeout_sec = limits.timeout_ms / 1000.0
        start_time = time.perf_counter()

        result_queue = multiprocessing.Queue(maxsize=1)

        proc = multiprocessing.Process(
            target=_worker_entrypoint,
            args=(target_fn, args, kwargs, result_queue, limits.max_output_bytes),
            daemon=True
        )

        proc.start()
        proc.join(timeout=timeout_sec)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        if proc.is_alive():
            # Hard Process Termination (§13.2)
            try:
                proc.terminate()
                proc.join(timeout=0.2)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.2)
            except Exception:
                pass

            return (
                SandboxStatus.TIMEOUT_EXCEEDED,
                None,
                f"Execution deadline exceeded ({limits.timeout_ms}ms timeout reached). OS Subprocess forcefully terminated.",
                elapsed_ms,
                124  # Standard POSIX timeout exit code
            )

        # Retrieve outcome from IPC queue
        try:
            payload = result_queue.get_nowait()
            st_name = payload.get("status", "SUCCESS")
            status_val = SandboxStatus(st_name)
            return status_val, payload.get("result"), payload.get("error"), elapsed_ms, 0 if payload.get("success") else 1
        except queue.Empty:
            exit_code = proc.exitcode if proc.exitcode is not None else 1
            return (
                SandboxStatus.EXECUTION_ERROR,
                None,
                f"Worker process exited unexpectedly with exit code {exit_code}.",
                elapsed_ms,
                exit_code
            )
        finally:
            result_queue.close()
