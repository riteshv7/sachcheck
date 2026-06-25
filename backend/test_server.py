import os
import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure backend directory is in the Python path
BACKEND_DIR = Path(__file__).parent.resolve()
sys.path.append(str(BACKEND_DIR))

from server import app

class TestSachCheckServer(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_e2e_session_lifecycle(self):
        print("\n--- Starting E2E Session Lifecycle Test ---")
        
        # 1. Start Session
        print("Step 1: Starting a new session...")
        response = self.client.post("/api/session/start")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("session_id", data)
        session_id = data["session_id"]
        print(f"  Session started. ID: {session_id}")
        
        # Check that session directory is created
        session_dir = Path("data/sessions") / session_id
        self.assertTrue(session_dir.exists())
        self.assertTrue((session_dir / "audio.webm").exists())
        print("  Confirmed session directory and audio placeholder exist on disk.")

        # 2. Test Text Checking Endpoint
        print("\nStep 2: Checking text fact-checking endpoint...")
        # We send a factual claim that should trigger search/RAG (using mock mode if keys are unavailable,
        # but here the backend calls the pipeline modules directly).
        # To avoid actual API calls and rate limits during testing, we can send a claim, but wait,
        # since we want to make sure it doesn't fail, let's send a simple sentence.
        # Wait! To avoid making real external API calls during this test which could fail due to missing keys or limits,
        # let's mock the pipeline calls in the test or test the structure.
        # Actually, let's mock search and context card generation for this unit test so it runs fast and offline.
        from unittest.mock import patch
        
        with patch('server.analyze_transcript_claims') as mock_analyze, \
             patch('server.search_for_claim') as mock_search, \
             patch('server.generate_context_card') as mock_generate:
            
            mock_analyze.return_value = [
                {
                    "text": "EPFO data ke mutabik pichle saal hi ek point teen crore jobs generate hui.",
                    "speaker": "Pravakta B",
                    "check_worthy": True,
                    "claim_type": "number",
                    "reason_check_worthy": "Verifiable statistic about job numbers."
                }
            ]
            mock_search.return_value = [{"title": "EPFO Job Report", "url": "https://epfo.gov.in"}]
            mock_generate.return_value = {
                "claim_text": "EPFO data ke mutabik pichle saal hi ek point teen crore jobs generate hui.",
                "speaker": "Pravakta B",
                "claim_type": "number",
                "literal_claim": "1.3 crore jobs generated according to EPFO.",
                "implied_claim": "Employment has increased.",
                "what_is_checkable": "EPFO enrollment statistics.",
                "grounded_context": [{"point": "EPFO records show net additions.", "source_citations": [1]}],
                "missing_context": [],
                "source_disagreement": "None",
                "confidence_level": "High",
                "confidence_reason": "Based on official EPFO data.",
                "sources_used": [{"index": 1, "title": "EPFO Report", "url": "https://epfo.gov.in", "source_type": "govt data"}]
            }

            text_payload = {
                "text": "EPFO data ke mutabik pichle saal hi ek point teen crore jobs generate hui.",
                "speaker": "Pravakta B"
            }
            response = self.client.post(f"/api/session/{session_id}/text", json=text_payload)
            self.assertEqual(response.status_code, 200)
            text_data = response.json()
            self.assertEqual(text_data["status"], "success")
            self.assertEqual(len(text_data["new_cards"]), 1)
            self.assertEqual(text_data["total_cards"], 1)
            self.assertEqual(text_data["new_cards"][0]["speaker"], "Pravakta B")
            print("  Text checking endpoint processed claim successfully.")

        # 3. Test Audio Upload Chunking Endpoint
        print("\nStep 3: Checking audio chunk upload endpoint...")
        # Create a mock audio blob (just dummy WAV bytes)
        dummy_audio = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        
        # We patch the background task to avoid actually calling Sarvam AI/Gemini for the dummy audio
        with patch('server.transcribe_audio') as mock_transcribe, \
             patch('server.llm_cleanup_transcript') as mock_cleanup, \
             patch('server.analyze_transcript_claims') as mock_claims_analysis:
            
            mock_transcribe.return_value = [
                {"speaker": "Pravakta B", "start_time": 0.0, "end_time": 5.0, "text": "EPFO data pichle saal 1.3 crore jobs dikhata hai"}
            ]
            mock_cleanup.return_value = [
                {"speaker": "Pravakta B", "start_time": 0.0, "end_time": 5.0, "text": "EPFO data pichle saal 1.3 crore jobs dikhata hai"}
            ]
            mock_claims_analysis.return_value = [] # No new claims to simplify the background processing
            
            files = {"file": ("chunk.webm", dummy_audio, "audio/webm")}
            response = self.client.post(f"/api/session/{session_id}/audio?mock=true", files=files)
            self.assertEqual(response.status_code, 200)
            audio_data = response.json()
            # The background task is triggered, so the server immediately returns processing status
            self.assertIn(audio_data["status"], ["processing", "idle"])
            print("  Audio chunk uploaded successfully. Background processing triggered.")

            # Verify the audio file grew on disk
            audio_file = session_dir / "audio.webm"
            self.assertTrue(audio_file.exists())
            self.assertEqual(audio_file.stat().st_size, len(dummy_audio))
            print(f"  Confirmed audio master file size matches uploaded chunk: {audio_file.stat().st_size} bytes.")

        # 4. Check Status Endpoint
        print("\nStep 4: Checking session status endpoint...")
        response = self.client.get(f"/api/session/{session_id}/status")
        self.assertEqual(response.status_code, 200)
        status_data = response.json()
        self.assertEqual(status_data["session_id"], session_id)
        self.assertIn("transcript", status_data)
        self.assertIn("context_cards", status_data)
        print("  Session status endpoint returned state correctly.")

        # 5. Stop Session (Cleanup)
        print("\nStep 5: Stopping session and verifying cleanup...")
        response = self.client.post(f"/api/session/{session_id}/stop")
        self.assertEqual(response.status_code, 200)
        stop_data = response.json()
        self.assertEqual(stop_data["status"], "stopped")
        self.assertIn("report_saved_to", stop_data)
        
        # Confirm directory was deleted
        self.assertFalse(session_dir.exists())
        # Confirm final JSON report was saved
        report_path = Path("data/results") / f"session_{session_id}.json"
        self.assertTrue(report_path.exists())
        print(f"  Confirmed session directory deleted. Report saved: {report_path.name}")
        
        # Clean up the report file created by test
        report_path.unlink()
        print("  E2E Session Lifecycle Test completed successfully.")

if __name__ == "__main__":
    unittest.main()
