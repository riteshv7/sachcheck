import os
import sys
import uuid
import json
import time
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure backend directory is in the Python path
BACKEND_DIR = Path(__file__).parent.resolve()
sys.path.append(str(BACKEND_DIR))

from transcribe import transcribe_audio
from cleanup import llm_cleanup_transcript
from claims import analyze_transcript_claims
from search import search_for_claim
from context import generate_context_card
from matcher import match_claim

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sachcheck.server")

app = FastAPI(
    title="SachCheck API Server",
    description="Local fact-checking brain serving the SachCheck Chrome Extension",
    version="1.0.0"
)

# Enable CORS for Chrome Extension access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local extension development, allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "app": "SachCheck Fact-Checking Backend Brain",
        "version": "1.0.0",
        "docs_url": "http://127.0.0.1:8000/docs"
    }

class LogRequest(BaseModel):
    level: str
    message: str
    context: Optional[str] = None

@app.post("/api/log")
def log_extension_message(request: LogRequest):
    msg = f"[EXTENSION {request.level.upper()}] {request.message}"
    if request.context:
        msg += f" (Context: {request.context})"
    logger.info(msg)
    return {"status": "logged"}

# Global in-memory session store
sessions: Dict[str, Dict[str, Any]] = {}
SESSIONS_DIR = Path("data/sessions")
RESULTS_DIR = Path("data/results")

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

class SessionStartResponse(BaseModel):
    session_id: str
    status: str
    message: str

class TextCheckRequest(BaseModel):
    text: str
    speaker: Optional[str] = "User"

def get_session_file_path(session_id: str) -> Path:
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir

async def process_audio_background(session_id: str, force_mock: bool):
    """
    Background task to process the accumulated audio file:
    ASR -> Cleanup -> Claim Detection -> Incremental Fact-checking.
    """
    session = sessions.get(session_id)
    if not session:
        logger.error(f"Session {session_id} not found in background task.")
        return

    try:
        session_dir = get_session_file_path(session_id)
        audio_path = session_dir / "audio.webm"

        if not audio_path.exists() or audio_path.stat().st_size == 0:
            logger.warning(f"Audio file empty or missing for session {session_id}")
            session["is_processing"] = False
            return

        logger.info(f"[{session_id}] Starting background audio processing. File size: {audio_path.stat().st_size} bytes")

        # 1. Transcribe the accumulated audio file
        # Using loop.run_in_executor to prevent blocking the async event loop with CPU/blocking I/O
        loop = asyncio.get_running_loop()
        raw_segments = await loop.run_in_executor(
            None, 
            lambda: transcribe_audio(str(audio_path), force_mock=force_mock)
        )
        
        # 2. Run LLM cleanup pass
        cleaned_segments = await loop.run_in_executor(
            None,
            lambda: llm_cleanup_transcript(raw_segments)
        )

        # Update transcript turns in the session state
        session["transcript"] = cleaned_segments

        # 3. Compile transcript text for claim analysis
        transcript_text = "\n".join(f"{seg['speaker']}: {seg['text']}" for seg in cleaned_segments)
        
        # 4. Extract claims
        all_claims = await loop.run_in_executor(
            None,
            lambda: analyze_transcript_claims(transcript_text)
        )

        if not all_claims:
            logger.info(f"[{session_id}] No claims detected in current transcript.")
            session["is_processing"] = False
            return

        # 5. Incremental Claim Processing
        new_cards_count = 0
        for claim in all_claims:
            claim_text = claim.get("text", "")
            speaker = claim.get("speaker", "Unknown")
            
            if claim.get("check_worthy"):
                # Check if this claim has already been processed (exact match on claim_text)
                already_processed = False
                for card in session["context_cards"]:
                    if card.get("claim_text") == claim_text:
                        already_processed = True
                        break

                if not already_processed:
                    logger.info(f"[{session_id}] New check-worthy claim detected: \"{claim_text}\"")
                    new_cards_count += 1
                    
                    # Run vector matcher "Fast Speed" path first
                    try:
                        matched_fc = await loop.run_in_executor(
                            None,
                            lambda: match_claim(claim_text)
                        )
                    except Exception as e:
                        logger.error(f"Matcher failed: {e}")
                        matched_fc = None
                        
                    if matched_fc:
                        logger.info(f"[{session_id}] Fast Path Match! Recycled claim matched for: \"{claim_text}\"")
                        context_card = matched_fc.copy()
                        context_card["claim_text"] = claim_text
                        context_card["speaker"] = speaker
                        context_card["is_recycled"] = True
                        session["context_cards"].append(context_card)
                    else:
                        # Deep Path: Run search and RAG synthesis
                        logger.info(f"[{session_id}] Deep Path: No recycled match. Executing search and RAG...")
                        # Run search
                        try:
                            search_results = await loop.run_in_executor(
                                None,
                                lambda: search_for_claim(claim)
                            )
                        except Exception as e:
                            logger.error(f"Search failed: {e}")
                            search_results = []

                        # Generate context card
                        try:
                            context_card = await loop.run_in_executor(
                                None,
                                lambda: generate_context_card(claim, search_results)
                            )
                            session["context_cards"].append(context_card)
                        except Exception as e:
                            logger.error(f"Context card generation failed: {e}")
                            session["context_cards"].append({
                                "claim_text": claim_text,
                                "speaker": speaker,
                                "error": f"Failed to generate context card: {str(e)}"
                            })
                        
                        # Pace consecutive API calls only on deep path
                        await asyncio.sleep(2)
            else:
                # Add to ignored audit log if not already there
                already_ignored = False
                for ignored in session["ignored_claims"]:
                    if ignored.get("text") == claim_text:
                        already_ignored = True
                        break
                
                if not already_ignored:
                    session["ignored_claims"].append({
                        "speaker": speaker,
                        "text": claim_text,
                        "reason_check_worthy": claim.get("reason_check_worthy", "Filtered out.")
                    })

        logger.info(f"[{session_id}] Background processing complete. Added {new_cards_count} new context cards.")

    except Exception as e:
        logger.exception(f"[{session_id}] Error in background processing: {e}")
    finally:
        session["is_processing"] = False

@app.post("/api/session/start", response_model=SessionStartResponse)
def start_session():
    """Starts a new fact-checking session, initializing local storage and session state."""
    session_id = str(uuid.uuid4())
    session_dir = get_session_file_path(session_id)
    audio_path = session_dir / "audio.webm"
    
    # Initialize empty audio file
    with open(audio_path, "wb") as f:
        pass

    sessions[session_id] = {
        "session_id": session_id,
        "is_processing": False,
        "transcript": [],
        "context_cards": [],
        "ignored_claims": [],
        "created_at": time.time()
    }
    
    logger.info(f"Started session {session_id}. Storage initialized at: {session_dir}")
    return SessionStartResponse(
        session_id=session_id,
        status="success",
        message="Session started successfully."
    )

@app.post("/api/session/{session_id}/audio")
async def upload_audio_chunk(
    session_id: str, 
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mock: bool = Query(False)
):
    """
    Receives a WebM audio chunk from the Chrome extension, appends it to the session audio,
    and triggers the background processing pipeline.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    session_dir = get_session_file_path(session_id)
    audio_path = session_dir / "audio.webm"
    
    # 1. Append bytes of uploaded chunk to session master audio file
    chunk_bytes = await file.read()
    logger.info(f"[{session_id}] Received audio chunk of {len(chunk_bytes)} bytes.")
    
    with open(audio_path, "ab") as f:
        f.write(chunk_bytes)
        
    # 2. Trigger background processing if not already running
    if not session["is_processing"]:
        session["is_processing"] = True
        background_tasks.add_task(process_audio_background, session_id, mock)
        logger.info(f"[{session_id}] Spawned background task to process accumulated audio.")
    else:
        logger.info(f"[{session_id}] Session is already processing. Chunk appended; will be analyzed in subsequent passes.")
        
    return {
        "status": "processing" if session["is_processing"] else "idle",
        "transcript_length": len(session["transcript"]),
        "context_cards_count": len(session["context_cards"])
    }

@app.post("/api/session/{session_id}/text")
async def check_text_turn(session_id: str, request: TextCheckRequest):
    """
    Endpoint to process a plain-text turn. Useful for manual input or testing.
    Runs the pipeline synchronously to immediately return the result.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    text_turn = request.text.strip()
    speaker = request.speaker or "User"
    if not text_turn:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
        
    logger.info(f"[{session_id}] Processing text turn from {speaker}: \"{text_turn}\"")
    
    # Add to transcript
    session["transcript"].append({
        "speaker": speaker,
        "start_time": 0.0,
        "end_time": 0.0,
        "text": text_turn
    })
    
    # Compile text for analysis
    transcript_text = f"{speaker}: {text_turn}"
    
    # Extract claims
    loop = asyncio.get_running_loop()
    all_claims = await loop.run_in_executor(
        None,
        lambda: analyze_transcript_claims(transcript_text)
    )
    
    new_cards = []
    
    for claim in all_claims:
        claim_text = claim.get("text", "")
        if claim.get("check_worthy"):
            # Check for duplicates
            already_processed = False
            for card in session["context_cards"]:
                if card.get("claim_text") == claim_text:
                    already_processed = True
                    break
                    
            if not already_processed:
                logger.info(f"[{session_id}] New text claim: \"{claim_text}\"")
                
                # Check for recycled match
                try:
                    matched_fc = await loop.run_in_executor(
                        None,
                        lambda: match_claim(claim_text)
                    )
                except Exception as e:
                    logger.error(f"Matcher failed: {e}")
                    matched_fc = None
                    
                if matched_fc:
                    logger.info(f"[{session_id}] Fast Path Match for text claim: \"{claim_text}\"")
                    context_card = matched_fc.copy()
                    context_card["claim_text"] = claim_text
                    context_card["speaker"] = speaker
                    context_card["is_recycled"] = True
                    session["context_cards"].append(context_card)
                    new_cards.append(context_card)
                else:
                    logger.info(f"[{session_id}] Deep Path for text claim: \"{claim_text}\"")
                    # Run search
                    search_results = await loop.run_in_executor(
                        None,
                        lambda: search_for_claim(claim)
                    )
                    # Generate card
                    context_card = await loop.run_in_executor(
                        None,
                        lambda: generate_context_card(claim, search_results)
                    )
                    session["context_cards"].append(context_card)
                    new_cards.append(context_card)
        else:
            # Audit log
            already_ignored = False
            for ignored in session["ignored_claims"]:
                if ignored.get("text") == claim_text:
                    already_ignored = True
                    break
            if not already_ignored:
                session["ignored_claims"].append({
                    "speaker": speaker,
                    "text": claim_text,
                    "reason_check_worthy": claim.get("reason_check_worthy", "Filtered out.")
                })
                
    return {
        "status": "success",
        "new_cards": new_cards,
        "total_cards": len(session["context_cards"])
    }

@app.get("/api/session/{session_id}/status")
def get_session_status(session_id: str):
    """Returns the current state of a session, including transcript and context cards."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    return {
        "session_id": session_id,
        "is_processing": session["is_processing"],
        "transcript": session["transcript"],
        "context_cards": session["context_cards"],
        "ignored_claims": session["ignored_claims"]
    }

@app.post("/api/session/{session_id}/stop")
def stop_session(session_id: str):
    """Stops the session, saves the final report, and cleans up local temporary files."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    logger.info(f"Stopping session {session_id} and writing final report.")
    
    # Save final report to results directory
    report = {
        "session_id": session_id,
        "summary": {
            "total_turns": len(session["transcript"]),
            "context_cards_count": len(session["context_cards"]),
            "ignored_claims_count": len(session["ignored_claims"])
        },
        "transcript": session["transcript"],
        "context_cards": session["context_cards"],
        "ignored_claims": session["ignored_claims"]
    }
    
    report_file = RESULTS_DIR / f"session_{session_id}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    # Clean up local audio and session files
    session_dir = SESSIONS_DIR / session_id
    if session_dir.exists():
        try:
            # Remove directory and its contents
            import shutil
            shutil.rmtree(session_dir)
            logger.info(f"Cleaned up session storage directory: {session_dir}")
        except Exception as e:
            logger.error(f"Failed to delete session directory {session_dir}: {e}")
            
    # Remove from in-memory sessions
    del sessions[session_id]
    
    return {
        "status": "stopped",
        "report_saved_to": str(report_file.name),
        "message": "Session stopped and temporary storage cleaned up."
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000)
