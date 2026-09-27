"""
INDEPENDENT CALCULATOR VERIFIER (Whitesheet §17.1)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Clean-room independent mathematical ground truth verifier.
Evaluates arithmetic expressions and returns deterministic binary outcome score (1.0 or 0.0).
Inherits from BaseDomainVerifier.
"""
import re
import math
import decimal
from decimal import Decimal, InvalidOperation, DivisionByZero
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timezone

from app.core.learning.verifiers.base import BaseDomainVerifier, VerifierOutcome


class IndependentCalculatorVerifier(BaseDomainVerifier):
    """
    Independent mathematical ground truth verifier for deterministic arithmetic tasks.
    Uses clean-room tokenization and recursive-descent parsing with Decimal arithmetic.
    """
    VERIFIER_ID: str = "verifier:calculator:v1.0.0:independent_math"
    VERIFIER_VERSION: str = "1.0.0"

    # Strict token regex: numbers and operators only
    _TOKEN_REGEX = re.compile(r'\s*(\d+(?:\.\d+)?|\+|\-|\*|\/|\%|\(|\))\s*')

    @classmethod
    def _extract_expression(cls, raw: str) -> Optional[str]:
        """Extracts the arithmetic substring from prompt or input text."""
        if not raw or not isinstance(raw, str):
            return None
        clean = raw.strip()
        # Look for expression patterns like "calculate 25 * 4" or "30 * 3"
        match = re.search(r'[\d\s\+\-\*\/\(\)\.\%]+', clean)
        if not match:
            return None
        expr = match.group(0).strip()
        # Ensure it contains at least one digit
        if not re.search(r'\d', expr):
            return None
        return expr

    @classmethod
    def _tokenize(cls, expr: str) -> Optional[List[str]]:
        """Tokenizes expression into standard arithmetic tokens."""
        tokens = []
        pos = 0
        while pos < len(expr):
            match = cls._TOKEN_REGEX.match(expr, pos)
            if not match:
                return None
            tok = match.group(1)
            tokens.append(tok)
            pos = match.end()
        return tokens

    @classmethod
    def _parse_and_eval(cls, tokens: List[str]) -> Decimal:
        """
        Recursive-descent arithmetic parser:
        expr   := term (('+' | '-') term)*
        term   := factor (('*' | '/' | '%') factor)*
        factor := ('+' | '-')? (NUMBER | '(' expr ')')
        """
        idx = 0

        def peek() -> Optional[str]:
            nonlocal idx
            return tokens[idx] if idx < len(tokens) else None

        def consume() -> str:
            nonlocal idx
            t = tokens[idx]
            idx += 1
            return t

        def parse_expr() -> Decimal:
            val = parse_term()
            while peek() in ('+', '-'):
                op = consume()
                right = parse_term()
                if op == '+':
                    val = val + right
                elif op == '-':
                    val = val - right
            return val

        def parse_term() -> Decimal:
            val = parse_factor()
            while peek() in ('*', '/', '%'):
                op = consume()
                right = parse_factor()
                if op == '*':
                    val = val * right
                elif op == '/':
                    if right == 0:
                        raise DivisionByZero("Division by zero in independent verifier")
                    val = val / right
                elif op == '%':
                    if right == 0:
                        raise DivisionByZero("Modulo by zero in independent verifier")
                    val = val % right
            return val

        def parse_factor() -> Decimal:
            p = peek()
            if p in ('+', '-'):
                sign = consume()
                f = parse_factor()
                return f if sign == '+' else -f

            if p == '(':
                consume()  # '('
                val = parse_expr()
                if peek() != ')':
                    raise ValueError("Mismatched parentheses in expression")
                consume()  # ')'
                return val

            if p is not None and re.match(r'^\d+(?:\.\d+)?$', p):
                num_str = consume()
                try:
                    return Decimal(num_str)
                except InvalidOperation:
                    raise ValueError(f"Invalid decimal literal: {num_str}")

            raise ValueError(f"Unexpected token in arithmetic expression: '{p}'")

        res = parse_expr()
        if idx < len(tokens):
            raise ValueError(f"Unparsed trailing tokens in expression: {tokens[idx:]}")
        return res

    @classmethod
    def compute_ground_truth(cls, raw_expression: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Independently calculates expected mathematical ground truth for a given string expression.
        Returns (result_float, error_message).
        """
        expr = cls._extract_expression(raw_expression)
        if not expr:
            return None, "NO_VALID_ARITHMETIC_EXPRESSION"

        tokens = cls._tokenize(expr)
        if tokens is None or len(tokens) == 0:
            return None, "MALFORMED_TOKEN_STRUCTURE"

        try:
            val_dec = cls._parse_and_eval(tokens)
            return float(val_dec), None
        except DivisionByZero as ex:
            return None, f"DIVISION_BY_ZERO: {str(ex)}"
        except Exception as ex:
            return None, f"VERIFIER_EVAL_ERROR: {str(ex)}"

    @classmethod
    def verify(
        cls,
        expression_or_input: Any,
        actual_result: Any
    ) -> VerifierOutcome:
        """
        Authoritatively verifies whether the observed actual_result matches
        the independently calculated ground truth.
        """
        expression_str = str(expression_or_input) if expression_or_input is not None else ""
        clean_expr = cls._extract_expression(expression_str) or expression_str

        # 1. Evaluate independent ground truth
        expected, err = cls.compute_ground_truth(expression_str)
        if err or expected is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=None,
                actual_result=float(actual_result) if isinstance(actual_result, (int, float)) else None,
                error=err or "FAILED_TO_COMPUTE_GROUND_TRUTH",
                provenance={"expression": clean_expr}
            )

        # 2. Extract and validate actual result
        if actual_result is None:
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=expected,
                actual_result=None,
                error="ACTUAL_RESULT_IS_NONE",
                provenance={"expression": clean_expr}
            )

        val_to_parse = actual_result
        if isinstance(actual_result, dict):
            val_to_parse = actual_result.get("result", actual_result.get("output", actual_result))
            if isinstance(val_to_parse, dict):
                val_to_parse = val_to_parse.get("result", val_to_parse.get("output", val_to_parse))

        try:
            act_float = float(val_to_parse)
        except (ValueError, TypeError):
            return VerifierOutcome(
                verifier_id=cls.VERIFIER_ID,
                verifier_version=cls.VERIFIER_VERSION,
                is_valid=False,
                outcome_score=0.0,
                expected_result=expected,
                actual_result=None,
                error=f"CANNOT_PARSE_ACTUAL_RESULT: {actual_result}",
                provenance={"expression": clean_expr}
            )

        # 3. Check mathematical equivalence with high precision
        is_equal = math.isclose(expected, act_float, rel_tol=1e-9, abs_tol=1e-9)

        return VerifierOutcome(
            verifier_id=cls.VERIFIER_ID,
            verifier_version=cls.VERIFIER_VERSION,
            is_valid=is_equal,
            outcome_score=1.0 if is_equal else 0.0,
            expected_result=expected,
            actual_result=act_float,
            error=None if is_equal else f"RESULT_MISMATCH: expected {expected}, got {act_float}",
            provenance={"expression": clean_expr}
        )
