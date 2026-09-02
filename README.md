# Brahma-COS

**Brahma-COS (Cognitive Operating System)** is an advanced AI Agent Orchestration platform. It integrates a powerful AI agent workflow with a robust backend and a modern frontend dashboard.

## 🚀 Tech Stack

- **AI Agents (Member 1):** LangGraph, LiteLLM, Ollama (`llama3.2:3b`)
- **Backend & Memory (Member 2):** FastAPI, PostgreSQL, pgvector, SQLAlchemy, PyMuPDF
- **Frontend (Member 3):** Next.js, React, TailwindCSS

## 📂 Project Structure

- `/backend` - FastAPI server, AI Agents (KARMA, PRAGYA, MURPHY, MARYADA, RACHIT), database models, and RAG/Memory pipelines.
- `/app` & `/components` - Next.js frontend code and UI components.

## ⚙️ Setup Instructions

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL** (running locally or via Docker)
- **Ollama** (for local LLM execution)

### 2. Ollama & AI Models Setup
Ensure Ollama is installed and running, then download the required model:
```bash
ollama pull llama3.2:3b
```

### 3. Backend Setup
Navigate to the root directory and set up the Python virtual environment:
```bash
# Create and activate virtual environment
python -m venv backend/venv
# Windows
.\backend\venv\Scripts\activate
# Mac/Linux
source backend/venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

Run the FastAPI server:
```bash
uvicorn backend.main:app --reload
```

### 4. Frontend Setup
Open a new terminal, ensure you are in the root directory:
```bash
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`.

## 🤖 Agent Workflow
The system follows a strict, fail-closed policy evaluation workflow:
1. **KARMA**: Orchestrates the task.
2. **PRAGYA**: Reasons over the intent and creates a plan.
3. **MURPHY**: Analyzes risks and simulates failures.
4. **MARYADA**: Evaluates enterprise policies. Approves low-risk tasks or escalates high-risk/failed tasks to humans.
5. **RACHIT**: Executes approved tasks.
