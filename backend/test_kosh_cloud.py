import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

# Ensure backend is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app.services.embedding_service import (
    generate_embedding,
    _get_embedding_config,
    EmbeddingDimensionError,
    EmbeddingProviderError,
    EXPECTED_DIMENSION
)
from app.db.database import SessionLocal
from app.models.knowledge import Knowledge
from app.repositories.knowledge_repository import semantic_search
from app.services.kosh_service import kosh

class TestKoshCloudPortability(unittest.TestCase):
    """
    Test suite for KOSH cloud-portability, provider abstraction,
    dimension validation, and upload rollback safety.
    """

    def test_01_ollama_provider_config_and_generation(self):
        """Test 1: Verify Ollama config loading and real local 768-dim embedding generation."""
        print("\n[TEST 1] Testing Ollama provider configuration and local 768-dim generation...")
        with patch.dict(os.environ, {
            "EMBEDDING_PROVIDER": "ollama",
            "EMBEDDING_MODEL": "nomic-embed-text",
            "OLLAMA_HOST": "http://localhost:11434"
        }):
            config = _get_embedding_config()
            self.assertEqual(config["provider"], "ollama")
            self.assertEqual(config["model"], "nomic-embed-text")
            self.assertEqual(config["host"], "http://localhost:11434")

            # Generate real local embedding
            vec = generate_embedding("Employee timesheet submission policy")
            self.assertIsInstance(vec, list)
            self.assertEqual(len(vec), 768)
            print(f" -> PASS: Successfully generated {len(vec)}-dimensional vector via Ollama.")

    def test_02_cloud_provider_mocked_success(self):
        """Test 2: Verify Cloud API provider accepts mocked 768-dim vector without paid API calls."""
        print("\n[TEST 2] Testing Cloud API provider with mocked 768-dimensional response...")
        mock_768_vec = [0.01] * 768
        
        with patch.dict(os.environ, {
            "EMBEDDING_PROVIDER": "cloud",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "EMBEDDING_API_KEY": "test-mock-key"
        }):
            config = _get_embedding_config()
            self.assertEqual(config["provider"], "cloud")
            self.assertEqual(config["model"], "text-embedding-3-small")

            # Mock OpenAI client
            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_response = MagicMock()
                mock_data_item = MagicMock()
                mock_data_item.embedding = mock_768_vec
                mock_response.data = [mock_data_item]
                mock_client.embeddings.create.return_value = mock_response
                mock_openai_cls.return_value = mock_client

                vec = generate_embedding("Cloud document query")
                self.assertEqual(len(vec), 768)
                
                # Verify that dimensions=768 was explicitly passed to cloud API
                mock_client.embeddings.create.assert_called_once_with(
                    input="Cloud document query",
                    model="text-embedding-3-small",
                    dimensions=768
                )
                print(f" -> PASS: Cloud provider produced {len(vec)}-dim vector with dimensions=768 enforced.")

    def test_03_wrong_dimension_rejection(self):
        """Test 3: Verify that unexpected vector dimensions (e.g. 1536) raise EmbeddingDimensionError."""
        print("\n[TEST 3] Testing rejection of non-768 dimensional vectors (e.g. 1536 dims)...")
        mock_1536_vec = [0.005] * 1536

        with patch.dict(os.environ, {
            "EMBEDDING_PROVIDER": "cloud",
            "EMBEDDING_MODEL": "text-embedding-ada-002",
            "EMBEDDING_API_KEY": "test-mock-key"
        }):
            with patch("app.services.embedding_service._generate_cloud_embedding", return_value=mock_1536_vec):
                with self.assertRaises(EmbeddingDimensionError) as ctx:
                    generate_embedding("Test prompt causing 1536 dims")
                self.assertIn("expected exactly 768, got 1536", str(ctx.exception))
                print(f" -> PASS: Safely rejected 1536-dim vector with EmbeddingDimensionError.")

    def test_04_kosh_semantic_retrieval(self):
        """Test 4: Verify KOSH retrieval flow: query -> embedding -> pgvector similarity search."""
        print("\n[TEST 4] Testing KOSH semantic retrieval against active pgvector store...")
        results = kosh.retrieve("What is the backup policy for Project Phoenix?")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        
        # Verify retrieved title & content
        titles = [r["title"] for r in results]
        self.assertIn("Project Phoenix Guidelines", titles)
        print(f" -> PASS: Successfully retrieved {len(results)} relevant documents from pgvector.")

    def test_05_upload_failure_and_rollback(self):
        """Test 5: Simulate embedding failure during upload; verify transaction rollback & 0 leftover records."""
        print("\n[TEST 5] Testing upload error handling and database transaction rollback...")
        db = SessionLocal()
        initial_count = db.query(Knowledge).count()
        db.close()

        # Simulate upload route execution with embedding error
        from app.api.routes.upload import upload_pdf
        from fastapi import HTTPException
        import io

        from unittest.mock import AsyncMock
        dummy_file = MagicMock()
        dummy_file.filename = "corrupted_document.pdf"
        dummy_file.read = AsyncMock(return_value=b"%PDF-1.4 dummy content")

        # Mock pdf extraction and chunking, but cause generate_embedding to fail
        with patch("app.api.routes.upload.extract_text", return_value="Sample text requiring embedding"):
            with patch("app.api.routes.upload.split_into_chunks", return_value=["Chunk 1", "Chunk 2"]):
                with patch("app.api.routes.upload.generate_embedding", side_effect=EmbeddingProviderError("Simulated provider outage")):
                    import asyncio
                    with self.assertRaises(HTTPException) as ctx:
                        asyncio.run(upload_pdf(dummy_file))
                    
                    self.assertEqual(ctx.exception.status_code, 500)
                    self.assertIn("Document upload failed during embedding generation", ctx.exception.detail)

        # Confirm rollback: row count must not have changed
        db = SessionLocal()
        final_count = db.query(Knowledge).count()
        db.close()
        self.assertEqual(initial_count, final_count)
        print(f" -> PASS: Upload failure caught cleanly; transaction rolled back (Row count unchanged at {final_count}).")

    def test_06_cloud_simulation_end_to_end(self):
        """Test 6: Cloud simulation — execute semantic search entirely in cloud mode without Ollama."""
        print("\n[TEST 6] Testing Cloud Simulation (EMBEDDING_PROVIDER=cloud without contacting Ollama)...")
        mock_768_vec = [0.01] * 768

        with patch.dict(os.environ, {
            "EMBEDDING_PROVIDER": "cloud",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "EMBEDDING_API_KEY": "test-cloud-key"
        }):
            with patch("app.services.embedding_service._generate_cloud_embedding", return_value=mock_768_vec):
                db = SessionLocal()
                try:
                    # Run semantic search in cloud mode
                    results = semantic_search(db, "Timesheets and holiday calendar", top_k=2)
                    self.assertIsInstance(results, list)
                    print(f" -> PASS: Cloud simulation executed successfully without Ollama dependency.")
                finally:
                    db.close()

if __name__ == "__main__":
    unittest.main()
