# BRAHMA PDF Requirement Gap Report

## Executive Summary
The current codebase is an MVP prototype that borrows nomenclature from the BRAHMA vFinal PDF specification but does not implement its core architectural guarantees. The codebase is a simple 6-node LangGraph pipeline with a PostgreSQL backend, lacking the deterministic, structural, and cryptographic rigor demanded by the PDF.

## Critical Gaps

### 1. Missing Cognitive Paths & Faculties
The PDF requires exactly 9 paths (NETRA, SMRITI, KOSH, PRAGYA, VIVEK, MARYADA, NIYANTRA, RACHIT, BRAHMA) controlling 15 Faculties (F1-F15).
**Current State**: Only KARMA (acting as NETRA/Orchestrator), KOSH, PRAGYA, MURPHY (acting as F3b), MARYADA, and RACHIT exist.
**Gap**: 4 entire paths and 11 distinct faculties are missing. There is no Faculty Registry or Contract Dispatcher.

### 2. Missing 4-Tier Memory Hierarchy
The PDF requires Working, Episodic, Semantic, and Strategic memory with strict decay, promotion, and cross-tier conflict resolution rules.
**Current State**: Memory consists of a single `tasks` table and a `pgvector` store for unstructured RAG.
**Gap**: No Semantic graph, no Episodic episode serialization, no Strategic mission persistence.

### 3. Missing KARMA Execution Engine
The PDF requires KARMA to be an execution layer comprising a Planner (DAG generator), Tool Router, Executor, Retry System, and Completion Validator.
**Current State**: The system never executes actions. `RACHIT` merely outputs a text string simulating successful execution.
**Gap**: Total absence of actual agentic tool execution, authority token generation, or recovery handling.

### 4. Non-Cryptographic Ledger (CHITRA)
The PDF requires CHITRA to be an immutable, append-only ledger using cryptographic hash chaining with a Replay Engine.
**Current State**: `Audit` is a standard SQL table with no cryptographic integrity or replayability.
**Gap**: Total lack of verifiable trust or chain integrity.

### 5. Constitutional Governance
The PDF requires a 3-tier hierarchy (Principles, Rules, Policies) evaluated via machine-enforceable predicates (F10).
**Current State**: `MARYADA` uses a generic LLM prompt to output a `LOW/HIGH` risk string.
**Gap**: No machine-enforceable rules, no formal compliance score computation.

### 6. Federation & Learning
The PDF defines a Multi-Agent Consensus protocol and an Evolutionary Stewardship learning pipeline with Regression Suites.
**Current State**: Single instance, no learning.
**Gap**: 100% of Federation and Learning requirements are CONCEPTUAL/NOT IMPLEMENTED.
