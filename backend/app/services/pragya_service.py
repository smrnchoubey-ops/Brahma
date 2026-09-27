import os
import ollama

from app.services.kosh_service import kosh

# Default model
MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")


class PragyaService:

    def answer(self, query: str, tenant_id: str):
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: PRAGYA reasoning requires a non-empty tenant_id (CA-008 fail-closed).")

        # Retrieve knowledge from KOSH strictly scoped to tenant
        docs = kosh.retrieve(query=query, tenant_id=tenant_id.strip())


        if docs:
            context = "\n\n".join([doc["content"] for doc in docs])
        else:
            context = "No relevant knowledge found."

        prompt = f"""
You are PRAGYA, the reasoning engine of the BRAHMA Cognitive Operating System.

Use ONLY the provided knowledge.

If the knowledge is insufficient, reply exactly:
"I don't have enough knowledge."

Knowledge:
{context}

Question:
{query}

Answer:
"""

        try:
            response = ollama.chat(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            return response["message"]["content"]

        except Exception as e:
            return f"Ollama Error: {str(e)}"


pragya = PragyaService()