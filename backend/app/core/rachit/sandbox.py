"""
RACHIT Sandbox Runtime & Filesystem Containment
Strictly conforms to BRAHMA COS Whitesheet §13.1, §13.3 & §13.4.

Enforces:
- Tenant & Task-scoped disposable filesystem workspace
- Comprehensive path containment (blocking relative traversal, absolute POSIX paths, Windows drive paths, UNC paths)
- Output size capping
- Network policy restrictions
- Disposable workspace cleanup
"""
from typing import Dict, Any, Optional, List, Tuple
import os
import shutil
import tempfile
import json
from pathlib import Path

from app.core.rachit.limits import SandboxStatus, ExecutionQuotas, SandboxExecutionResult
from app.core.rachit.process_manager import ProcessSupervisor
from app.core.chitra.crypto import compute_content_hash


class RachitSandbox:
    """
    Isolated execution environment enforcing filesystem, network, and buffer limits.
    """
    def __init__(
        self,
        tenant_id: str,
        task_id: int,
        quotas: Optional[ExecutionQuotas] = None,
        base_dir: Optional[str] = None
    ):
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Authenticated Tenant ID is required for sandbox initialization.")

        self.tenant_id = tenant_id
        self.task_id = task_id
        self.quotas = quotas or ExecutionQuotas()

        # Create isolated workspace directory (§13.1, §13.4)
        root = base_dir or tempfile.gettempdir()
        self.workspace_dir = Path(root) / "rachit_sandboxes" / str(tenant_id) / f"task_{task_id}"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def validate_path_containment(self, target_path: str) -> bool:
        """
        Validates that a path is strictly contained within the sandbox workspace.
        Rejects:
        - Relative traversal outside workspace ('../')
        - Absolute POSIX paths ('/etc/passwd')
        - Windows drive paths ('C:\\Windows')
        - UNC paths ('\\\\server\\share')
        """
        if not target_path or not isinstance(target_path, str):
            return True

        # Check for obvious UNC or drive-letter patterns
        if target_path.startswith(("\\\\", "//")):
            return False

        try:
            path_obj = Path(target_path)
            if path_obj.is_absolute():
                resolved_target = path_obj.resolve()
            else:
                resolved_target = (self.workspace_dir / target_path).resolve()

            resolved_workspace = self.workspace_dir.resolve()
            return resolved_workspace in resolved_target.parents or resolved_target == resolved_workspace
        except Exception:
            return False

    def check_network_permission(self) -> bool:
        """
        Checks if out-of-band network access is permitted under the active quota (§13.4).
        """
        return self.quotas.allow_network

    def execute_tool(
        self,
        tool_id: str,
        action_name: str,
        handler_fn: Any,
        params: Optional[Dict[str, Any]] = None
    ) -> SandboxExecutionResult:
        """
        Runs a tool handler inside the isolated sandbox and enforces quotas and output capping.
        """
        params = params or {}

        # 1. Check for Path Traversal / Escape in all parameters (§13.4)
        for k, v in params.items():
            if isinstance(v, str):
                is_potential_path = any(s in v for s in ["/", "\\", "..", ":"]) or v.startswith(("/", "\\"))
                if is_potential_path and ("file" in k.lower() or "path" in k.lower() or "dir" in k.lower() or "../" in v or "..\\" in v or v.startswith(("/", "\\")) or (len(v) > 2 and v[1] == ":")):
                    if not self.validate_path_containment(v):
                        return SandboxExecutionResult(
                            status=SandboxStatus.SECURITY_VIOLATION,
                            tool_id=tool_id,
                            action_name=action_name,
                            error=f"Security violation: path escape detected in parameter '{k}' ({v}). Access outside workspace denied.",
                            exit_code=13
                        )

        # 2. Execute via OS Process Supervisor (§13.1, §13.2)
        status, final_output, err, exec_time, exit_code = ProcessSupervisor.execute_with_containment(
            target_fn=handler_fn,
            kwargs=params,
            quotas=self.quotas
        )

        # 3. Compute Cryptographic Output Hash (§13.6, §8.2)
        out_hash = compute_content_hash({
            "tool_id": tool_id,
            "status": status.value,
            "output": final_output,
            "exit_code": exit_code
        })

        return SandboxExecutionResult(
            status=status,
            tool_id=tool_id,
            action_name=action_name,
            output=final_output,
            error=err,
            execution_time_ms=exec_time,
            exit_code=exit_code,
            output_hash=out_hash
        )

    def cleanup(self) -> None:
        """
        Cleans up the temporary sandbox workspace (§13.5).
        """
        try:
            if self.workspace_dir.exists():
                shutil.rmtree(self.workspace_dir, ignore_errors=True)
        except Exception:
            pass
