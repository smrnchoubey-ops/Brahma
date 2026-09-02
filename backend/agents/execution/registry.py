import re
import ast
import operator
from typing import Dict, Any, Callable, Optional, List
from datetime import datetime, timezone

class ExecutionError(Exception):
    """Raised when an approved action fails during execution."""
    pass

class ActionSecurityError(Exception):
    """Raised when an unapproved or disallowed action is attempted."""
    pass

# Safe math operators for the safe calculator tool
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def _eval_safe_math(node):
    """Safely evaluates basic arithmetic expressions via AST."""
    if isinstance(node, ast.Num):  # Python <3.8
        return node.n
    elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ExecutionError(f"Unsupported operator: {op_type.__name__}")
        left = _eval_safe_math(node.left)
        right = _eval_safe_math(node.right)
        if op_type == ast.Div and right == 0:
            raise ExecutionError("Division by zero in calculation")
        return _SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ExecutionError(f"Unsupported operator: {op_type.__name__}")
        return _SAFE_OPERATORS[op_type](_eval_safe_math(node.operand))
    else:
        raise ExecutionError(f"Disallowed expression node: {type(node).__name__}")


# =====================================================================
# Real, Safe Action Handlers
# =====================================================================

def handle_echo(params: Dict[str, Any]) -> Dict[str, Any]:
    """Echoes and formats provided text deterministically."""
    text = str(params.get("text", "")).strip()
    fmt = str(params.get("format", "plain")).lower()
    
    if fmt == "uppercase":
        formatted = text.upper()
    elif fmt == "lowercase":
        formatted = text.lower()
    elif fmt == "bulleted":
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        formatted = "\n".join([f"- {line}" for line in lines])
    else:
        formatted = text
        
    return {
        "output": formatted,
        "length": len(formatted),
        "format": fmt
    }

def handle_system_status(params: Dict[str, Any]) -> Dict[str, Any]:
    """Provides read-only operational health and platform telemetry."""
    scope = params.get("scope", "basic")
    now_utc = datetime.now(timezone.utc).isoformat()
    
    status_info = {
        "engine": "BRAHMA COS Multi-Agent Orchestrator",
        "timestamp": now_utc,
        "status": "OPERATIONAL",
        "governance_mode": "FAIL_CLOSED",
        "database": "PostgreSQL 17 (pgvector)",
        "scope": scope
    }
    return status_info

def handle_calculate(params: Dict[str, Any]) -> Dict[str, Any]:
    """Safely calculates arithmetic expressions without using eval()."""
    expr = params.get("expression") or params.get("expr") or params.get("text")
    if not expr:
        raise ExecutionError("Missing 'expression' parameter for calculate action.")
    
    clean_expr = str(expr).strip()
    # Strip potential non-math characters if a natural phrase was passed (e.g., '15 * 4')
    match = re.search(r"[\d\s\+\-\*\/\(\)\.\%]+", clean_expr)
    if not match:
        raise ExecutionError(f"No valid arithmetic expression found in: '{expr}'")
    
    math_str = match.group(0).strip()
    try:
        parsed = ast.parse(math_str, mode="eval")
        result = _eval_safe_math(parsed.body)
        return {
            "expression": math_str,
            "result": result
        }
    except Exception as e:
        raise ExecutionError(f"Calculation failed for '{math_str}': {str(e)}")

def handle_calendar_lookup(params: Dict[str, Any]) -> Dict[str, Any]:
    """Returns organizational corporate holiday schedule."""
    year = params.get("year", 2026)
    holidays_2026 = [
        {"date": "2026-01-01", "name": "New Year's Day"},
        {"date": "2026-01-26", "name": "Republic Day"},
        {"date": "2026-03-04", "name": "Holi"},
        {"date": "2026-08-15", "name": "Independence Day"},
        {"date": "2026-10-02", "name": "Gandhi Jayanti"},
        {"date": "2026-10-20", "name": "Dussehra"},
        {"date": "2026-11-08", "name": "Diwali"},
        {"date": "2026-12-25", "name": "Christmas"}
    ]
    return {
        "calendar_year": year,
        "total_holidays": len(holidays_2026),
        "holidays": holidays_2026
    }

def handle_policy_lookup(params: Dict[str, Any]) -> Dict[str, Any]:
    """Returns verified company governance policy summaries."""
    topic = str(params.get("topic", "")).lower()
    
    policies = {
        "timesheet": "Timesheets must be finalized and submitted by every Friday before 5:00 PM.",
        "backup": "Project Phoenix and all mission-critical production databases must execute cold-storage backups daily.",
        "deployment": "Production deployments require Maryada governance approval and must pass Murphy risk verification."
    }
    
    matched = {}
    for key, text in policies.items():
        if not topic or key in topic:
            matched[key] = text
            
    if not matched:
        matched["general"] = "Standard company policies apply. Contact HR/Operations for uncataloged inquiries."
        
    return {
        "topic_queried": topic or "all",
        "policies": matched
    }

def handle_deliverable_summary(params: Dict[str, Any]) -> Dict[str, Any]:
    """Compiles a finalized deliverable summary from an approved plan."""
    plan_summary = params.get("plan_summary", "Execution completed as planned.")
    steps = params.get("steps", [])
    
    formatted_steps = []
    for idx, s in enumerate(steps, start=1):
        formatted_steps.append(f"{idx}. {s}")
        
    return {
        "deliverable": plan_summary,
        "steps_executed": formatted_steps,
        "status": "DELIVERED"
    }


# =====================================================================
# Action Registry & Disallowed Tool Blacklist
# =====================================================================

ACTION_REGISTRY: Dict[str, Dict[str, Any]] = {
    "echo": {
        "handler": handle_echo,
        "description": "Formats or echoes structured text output",
        "risk_level": "LOW",
        "read_only": True
    },
    "system_status": {
        "handler": handle_system_status,
        "description": "Checks system operational telemetry and health",
        "risk_level": "LOW",
        "read_only": True
    },
    "calculate": {
        "handler": handle_calculate,
        "description": "Safely computes arithmetic expressions via AST",
        "risk_level": "LOW",
        "read_only": True
    },
    "calendar_lookup": {
        "handler": handle_calendar_lookup,
        "description": "Looks up organization holiday calendar schedule",
        "risk_level": "LOW",
        "read_only": True
    },
    "policy_lookup": {
        "handler": handle_policy_lookup,
        "description": "Retrieves verified corporate governance guidelines",
        "risk_level": "LOW",
        "read_only": True
    },
    "deliverable_summary": {
        "handler": handle_deliverable_summary,
        "description": "Assembles final deliverable from approved plan steps",
        "risk_level": "LOW",
        "read_only": True
    }
}

# Explicitly blocked tool names to guarantee safety
DISALLOWED_TOOL_KEYWORDS = {
    "shell", "sh", "bash", "cmd", "powershell", "ps", "exec", "eval",
    "subprocess", "popen", "spawn", "terminal", "os_system", "os.system",
    "system_call", "system_cmd", "system32", "os_command",
    "rm", "del", "delete", "format_drive", "drop_table", "truncate",
    "curl", "wget", "http_request", "socket", "connect"
}
