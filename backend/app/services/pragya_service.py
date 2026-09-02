import os
import ollama

from app.services.kosh_service import kosh

# Default model
MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")


class PragyaService:

    def answer(self, query: str):

        # Retrieve knowledge from KOSH
        docs = kosh.retrieve(query)

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