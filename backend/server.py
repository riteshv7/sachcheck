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
from fastapi.staticfiles import StaticFiles
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
from youtube import get_youtube_transcript, download_youtube_audio

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

# Check if running on Vercel or similar read-only environment
IS_VERCEL = "VERCEL" in os.environ
if IS_VERCEL:
    TEMP_BASE_DIR = Path("/tmp/sachcheck")
else:
    TEMP_BASE_DIR = BACKEND_DIR.parent

SESSIONS_DIR = TEMP_BASE_DIR / "data" / "sessions"
RESULTS_DIR = TEMP_BASE_DIR / "data" / "results"

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

class URLCheckRequest(BaseModel):
    url: str
    segments: Optional[List[Dict[str, Any]]] = None
    mock: Optional[bool] = False

class TextFactCheckRequest(BaseModel):
    text: str
    mock: Optional[bool] = False

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

# Pre-baked report for mock URL fact-checking runs to showcase UI functionality instantly
MOCK_URL_REPORT = {
    "status": "success",
    "transcript": [
        {
            "speaker": "Anchor",
            "start_time": 0.0,
            "end_time": 5.2,
            "text": "Swagat hai aapka. Aaj hum baat karenge desh mein berozgari aur naukriyon ke baare mein. Hamare sath dono paksh ke pravakta hain."
        },
        {
            "speaker": "Pravakta A",
            "start_time": 5.5,
            "end_time": 15.8,
            "text": "Dekhiye, desh ke yuva aaj pareshan hain. Government ne har saal do crore naukriyon dene ka promise kiya tha. But the truth is, pichle 45 saal mein sabse zyada unemployment rate aaj hai. PLFS data dikhata hai ki youth unemployment 15 percent touch kar raha hai."
        },
        {
            "speaker": "Pravakta B",
            "start_time": 16.2,
            "end_time": 25.5,
            "text": "Yeh bilkul galat baat hai. Hamari sarkar ne EPFO data ke mutabik pichle saal hi ek point teen crore nayi jobs generate ki hain. Aur mudra loan scheme ke under humne 40 crore se zyada loans diye hain, jisse log self-employed ban rahe hain."
        },
        {
            "speaker": "Pravakta A",
            "start_time": 25.8,
            "end_time": 32.4,
            "text": "EPFO data real jobs nahi dikhata, wo sirf formalisation of labor dikhata hai."
        },
        {
            "speaker": "Pravakta A",
            "start_time": 32.6,
            "end_time": 41.0,
            "text": "Mudra loans se koi real long-term employment nahi create ho raha hai, average loan size bohot chota hai."
        }
    ],
    "context_cards": [
        {
            "claim_text": "pichle 45 saal mein sabse zyada unemployment rate aaj hai. PLFS data dikhata hai ki youth unemployment 15 percent touch kar raha hai.",
            "speaker": "Pravakta A",
            "confidence_level": "Medium",
            "literal_claim": "The unemployment rate in India is currently at its highest in 45 years, and youth unemployment is around 15% according to PLFS data.",
            "implied_claim": "The government has failed completely on employment generation, making the job crisis worse than at any point in modern history.",
            "grounded_context": [
                {
                    "point": "The 45-year high unemployment rate of 6.1% was reported in the PLFS 2017-18 report, which was the first annual report under the new survey design.",
                    "source_citations": [1]
                },
                {
                    "point": "According to the latest PLFS annual reports (2022-23 and 2023-24), the overall national unemployment rate has decreased to 3.2%, which is a multi-year low.",
                    "source_citations": [2]
                },
                {
                    "point": "Youth unemployment (ages 15-29) was indeed high at around 17.8% in 2017-18, but has since declined to approximately 10.0% in 2022-23.",
                    "source_citations": [1, 2]
                }
            ],
            "missing_context": [
                "The claim of a '45-year high' refers to 2017-18 data and does not reflect the current 2024-2026 economic situation, where PLFS reports show a significant recovery in employment numbers.",
                "Comparing older NSSO surveys with the newer PLFS design has been noted by economists as methodologically inconsistent due to differences in sampling."
            ],
            "sources_used": [
                {
                    "index": 1,
                    "title": "Periodic Labour Force Survey (PLFS) Annual Report 2017-18 - MoSPI",
                    "url": "https://mospi.gov.in"
                },
                {
                    "index": 2,
                    "title": "Periodic Labour Force Survey (PLFS) Annual Report 2022-23 - MoSPI",
                    "url": "https://mospi.gov.in"
                }
            ]
        },
        {
            "claim_text": "EPFO data ke mutabik pichle saal hi ek point teen crore nayi jobs generate ki hain.",
            "speaker": "Pravakta B",
            "confidence_level": "Medium",
            "literal_claim": "EPFO payroll data shows that 1.3 crore new jobs were generated in the last year.",
            "implied_claim": "Formal job creation is booming under the current administration, proving their economic policies are highly effective.",
            "grounded_context": [
                {
                    "point": "EPFO (Employees' Provident Fund Organisation) added approximately 1.3 crore net subscribers in the financial year 2022-2023.",
                    "source_citations": [1]
                },
                {
                    "point": "Economists and the reserve bank point out that net EPFO additions represent formalization of existing informal jobs rather than entirely new job creation.",
                    "source_citations": [2]
                }
            ],
            "missing_context": [
                "EPFO subscription is mandatory for firms with 20 or more employees. An increase can be driven by formalization, regulatory compliance, or shifting of workers from unregistered firms rather than net new employment.",
                "A significant portion of EPFO additions are individuals re-joining the fund or changing jobs, which is partially corrected in 'net' data but still contains duplicate profiles."
            ],
            "sources_used": [
                {
                    "index": 1,
                    "title": "EPFO Payroll Data Press Release 2023 - MoSPI",
                    "url": "https://mospi.gov.in"
                },
                {
                    "index": 2,
                    "title": "Understanding EPFO Payroll Metrics - Economic and Political Weekly",
                    "url": "https://www.epw.in"
                }
            ]
        },
        {
            "claim_text": "mudra loan scheme ke under humne 40 crore se zyada loans diye hain, jisse log self-employed ban rahe hain.",
            "speaker": "Pravakta B",
            "confidence_level": "High",
            "literal_claim": "Over 40 crore loans have been sanctioned under the Pradhan Mantri Mudra Yojana (PMMY) to promote self-employment.",
            "implied_claim": "The government has successfully turned millions of job seekers into job creators, resolving the unemployment crisis through entrepreneurship.",
            "grounded_context": [
                {
                    "point": "As of 2023, the government reported that over 40.82 crore loans worth ₹23.2 lakh crore had been sanctioned since the inception of the Mudra scheme in 2015.",
                    "source_citations": [1]
                },
                {
                    "point": "About 83% of the sanctioned loans are in the 'Shishu' category (loans up to ₹50,000), which are primarily micro-finance loans for survivalist livelihoods rather than scalable business enterprises.",
                    "source_citations": [2]
                }
            ],
            "missing_context": [
                "While the number of loans is high, independent studies show that the average size of Shishu loans (approx. ₹27,000) is insufficient to create sustainable, long-term employment for more than one person.",
                "There is no comprehensive, official tracking of how many of these loans resulted in net new sustainable jobs versus sustaining existing micro-enterprises."
            ],
            "sources_used": [
                {
                    "index": 1,
                    "title": "Pradhan Mantri Mudra Yojana Official Portal - PMMY",
                    "url": "https://www.mudra.org.in"
                },
                {
                    "index": 2,
                    "title": "Evaluation Study on PMMY - NITI Aayog",
                    "url": "https://niti.gov.in"
                }
            ]
        }
    ],
    "ignored_claims": [
        {
            "speaker": "Anchor",
            "text": "Swagat hai aapka. Aaj hum baat karenge desh mein berozgari aur naukriyon ke baare mein.",
            "reason_check_worthy": "Casual welcome and topic introduction; does not assert verifiable facts."
        },
        {
            "speaker": "Pravakta A",
            "text": "Dekhiye, desh ke yuva aaj pareshan hain.",
            "reason_check_worthy": "General opinion and characterization of public sentiment; not a verifiable statistic."
        }
    ]
}

def group_browser_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Groups raw individual caption segments (e.g. from the browser) into
    cohesive conversational turns of approximately 15 seconds.
    """
    turns = []
    current_text = []
    current_start = None
    current_end = None
    chunk_duration = 15.0
    
    for seg in segments:
        start = float(seg.get("start", seg.get("start_time", 0.0)))
        duration = seg.get("duration")
        if duration is not None:
            end = start + float(duration)
        else:
            end = float(seg.get("end", seg.get("end_time", start + 2.0)))
        text = seg.get("text", "").strip()
        
        if not text or text.lower() in ["[music]", "[applause]", "[laughter]"]:
            continue
            
        if current_start is None:
            current_start = start
            current_end = end
            current_text.append(text)
        elif (start - current_start) < chunk_duration:
            current_end = end
            current_text.append(text)
        else:
            turns.append({
                "speaker": "Presenter",
                "start_time": round(current_start, 2),
                "end_time": round(current_end, 2),
                "text": " ".join(current_text)
            })
            current_start = start
            current_end = end
            current_text = [text]
            
    if current_text:
        turns.append({
            "speaker": "Presenter",
            "start_time": round(current_start, 2),
            "end_time": round(current_end, 2),
            "text": " ".join(current_text)
        })
        
    return turns

async def process_claim_e2e(claim: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """
    Shared helper to process a single claim:
    First attempts Fast Path (recycled match), then falls back to Deep Path (search + RAG).
    """
    claim_text = claim.get("text", "")
    speaker = claim.get("speaker", "Unknown")
    
    # A. Fast Path: Recycled Match
    try:
        matched_fc = await loop.run_in_executor(
            None,
            lambda: match_claim(claim_text)
        )
    except Exception as match_err:
        logger.error(f"Fast path match failed for '{claim_text}': {match_err}")
        matched_fc = None
        
    if matched_fc:
        logger.info(f"Fast Path Match! Reusing context card for: \"{claim_text}\"")
        context_card = matched_fc.copy()
        context_card["claim_text"] = claim_text
        context_card["speaker"] = speaker
        context_card["is_recycled"] = True
        return context_card
        
    # B. Deep Path: Search + RAG
    logger.info(f"Deep Path: Running search & RAG for: \"{claim_text}\"")
    try:
        search_results = await loop.run_in_executor(
            None,
            lambda: search_for_claim(claim)
        )
    except Exception as search_err:
        logger.error(f"Search failed for '{claim_text}': {search_err}")
        search_results = []
        
    try:
        context_card = await loop.run_in_executor(
            None,
            lambda: generate_context_card(claim, search_results)
        )
        return context_card
    except Exception as rag_err:
        logger.error(f"RAG card generation failed for '{claim_text}': {rag_err}")
        return {
            "claim_text": claim_text,
            "speaker": speaker,
            "error": f"Failed to generate context card: {str(rag_err)}"
        }

@app.post("/api/factcheck/url")
async def factcheck_url(request: URLCheckRequest):
    """
    Fact-checks a full YouTube video URL.
    Returns the complete transcript turns, context cards, and ignored claims.
    Supports instant caption extraction, with fallback to ASR transcription.
    Also supports client-extracted captions passed in the payload.
    """
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty.")
        
    logger.info(f"Received URL fact-check request for: {url} (Mock: {request.mock})")
    
    # 1. Handle Mock Mode
    if request.mock:
        logger.info("Mock mode enabled. Returning pre-baked fact-check report.")
        return MOCK_URL_REPORT
        
    # 2. Get Video ID
    from youtube import extract_video_id
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL format. Could not extract video ID.")
        
    # 3. Retrieve/Transcribe Transcript
    raw_turns = []
    
    if request.segments:
        logger.info(f"Using {len(request.segments)} browser-provided segments for URL: {url}")
        raw_turns = group_browser_segments(request.segments)
    else:
        # Try fetching server-side captions first
        try:
            raw_turns = get_youtube_transcript(url)
            logger.info(f"Successfully retrieved server-side captions for {url}. Total turns: {len(raw_turns)}")
        except Exception as e:
            logger.warning(f"Could not retrieve server-side captions for {url}: {e}. Falling back to audio download and ASR...")
            
            # Fallback path: download audio and run ASR
            try:
                temp_dir = TEMP_BASE_DIR / "data" / "audio"
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                # Download audio
                audio_path = download_youtube_audio(url, temp_dir)
                logger.info(f"Downloaded audio to {audio_path}. Starting transcription...")
                
                # Run transcription (in-executor since it's blocking/CPU)
                loop = asyncio.get_running_loop()
                raw_segments = await loop.run_in_executor(
                    None,
                    lambda: transcribe_audio(str(audio_path), force_mock=False)
                )
                
                # Clean up downloaded audio file
                try:
                    if audio_path.exists():
                        audio_path.unlink()
                except Exception as cleanup_err:
                    logger.error(f"Failed to delete temporary audio file: {cleanup_err}")
                
                # Run LLM cleanup pass on raw ASR segments
                raw_turns = await loop.run_in_executor(
                    None,
                    lambda: llm_cleanup_transcript(raw_segments)
                )
                logger.info(f"ASR & LLM cleanup complete. Total turns: {len(raw_turns)}")
                
            except Exception as fallback_err:
                logger.error(f"Fallback audio transcription failed: {fallback_err}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to transcribe video audio: {str(fallback_err)}"
                )
                
    if not raw_turns:
        raise HTTPException(status_code=500, detail="Could not retrieve or generate transcript for the video.")
        
    # 4. Extract claims from the transcript in a single pass
    # Format the transcript text for claim analysis
    transcript_text = "\n".join(f"{t['speaker']}: {t['text']}" for t in raw_turns)
    
    loop = asyncio.get_running_loop()
    try:
        all_claims = await loop.run_in_executor(
            None,
            lambda: analyze_transcript_claims(transcript_text)
        )
    except Exception as e:
        logger.error(f"Claim extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to extract claims: {str(e)}")
        
    # 5. Process claims concurrently using shared helper
    check_worthy_claims = [c for c in all_claims if c.get("check_worthy")]
    
    context_cards = []
    if check_worthy_claims:
        logger.info(f"Found {len(check_worthy_claims)} check-worthy claims. Processing concurrently...")
        context_cards = await asyncio.gather(*(process_claim_e2e(c, loop) for c in check_worthy_claims))
        logger.info(f"Successfully generated {len(context_cards)} context cards.")
        
    # Compile ignored claims
    ignored_claims = []
    for claim in all_claims:
        if not claim.get("check_worthy"):
            ignored_claims.append({
                "speaker": claim.get("speaker", "Unknown"),
                "text": claim.get("text", ""),
                "reason_check_worthy": claim.get("reason_check_worthy", "Filtered out.")
            })
            
    return {
        "status": "success",
        "transcript": raw_turns,
        "context_cards": context_cards,
        "ignored_claims": ignored_claims
    }

@app.post("/api/factcheck/text")
async def factcheck_text(request: TextFactCheckRequest):
    """
    Fact-checks a raw transcript text turn-by-turn.
    Extracts claims, runs the hybrid routing engine (Fast/Deep path), and returns context cards.
    """
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text transcript cannot be empty.")
        
    logger.info(f"Received text fact-check request (Mock: {request.mock})")
    
    # 1. Handle Mock Mode
    if request.mock:
        logger.info("Mock mode enabled for text. Returning mock fact-check report.")
        # We can return the MOCK_URL_REPORT but with a custom transcript
        mock_report = MOCK_URL_REPORT.copy()
        mock_report["transcript"] = [
            {"speaker": "Anchor", "text": "Swagat hai aapka. Aaj hum baat karenge desh mein berozgari aur naukriyon ke baare mein."},
            {"speaker": "Pravakta A", "text": "Government ne har saal do crore naukriyon dene ka promise kiya tha. PLFS data dikhata hai ki youth unemployment 15% touch kar raha hai."},
            {"speaker": "Pravakta B", "text": "Hamari sarkar ne EPFO data ke mutabik pichle saal hi 1.3 crore jobs generate ki hain. Aur mudra loan scheme ke under 40 crore se zyada loans diye hain."},
            {"speaker": "Pravakta A", "text": "EPFO data real jobs nahi dikhata. Mudra loans se koi real employment nahi create ho raha, average loan size bohot chota hai."}
        ]
        return mock_report
        
    # 2. Analyze Claims from input text
    loop = asyncio.get_running_loop()
    try:
        all_claims = await loop.run_in_executor(
            None,
            lambda: analyze_transcript_claims(text)
        )
    except Exception as e:
        logger.error(f"Claim extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to extract claims: {str(e)}")
        
    # 3. Process claims concurrently using the shared process_claim_e2e helper
    check_worthy_claims = [c for c in all_claims if c.get("check_worthy")]
    
    context_cards = []
    if check_worthy_claims:
        logger.info(f"Found {len(check_worthy_claims)} check-worthy claims. Processing concurrently...")
        context_cards = await asyncio.gather(*(process_claim_e2e(c, loop) for c in check_worthy_claims))
        logger.info(f"Successfully generated {len(context_cards)} context cards.")
        
    # 4. Compile ignored claims
    ignored_claims = []
    for claim in all_claims:
        if not claim.get("check_worthy"):
            ignored_claims.append({
                "speaker": claim.get("speaker", "Unknown"),
                "text": claim.get("text", ""),
                "reason_check_worthy": claim.get("reason_check_worthy", "Filtered out.")
            })
            
    # Parse text lines into turns for the frontend transcript display
    transcript_turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            parts = line.split(":", 1)
            speaker = parts[0].strip()
            speech_text = parts[1].strip()
        else:
            speaker = "Speaker"
            speech_text = line
        transcript_turns.append({
            "speaker": speaker,
            "text": speech_text
        })
            
    return {
        "status": "success",
        "transcript": transcript_turns,
        "context_cards": context_cards,
        "ignored_claims": ignored_claims
    }

@app.get("/api/system/status")
def get_system_status():
    """
    Returns system readiness state, API keys configuration status,
    and loaded database and cache statistics.
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    serper_key = os.getenv("SERPER_API_KEY", "")
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    
    has_gemini = bool(gemini_key and not gemini_key.startswith("your_"))
    has_serper = bool(serper_key and not serper_key.startswith("your_"))
    has_sarvam = bool(sarvam_key and not sarvam_key.startswith("your_"))
    
    db_size = 0
    db_file = BACKEND_DIR.parent / "data" / "debunked_db.json"
    if db_file.exists():
        try:
            with open(db_file, "r", encoding="utf-8") as f:
                db_data = json.load(f)
                db_size = len(db_data)
        except Exception as e:
            logger.error(f"Failed to read debunked_db.json size: {e}")
            
    cache_size = 0
    cache_file = BACKEND_DIR.parent / "data" / "embedding_cache.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                cache_size = len(cache_data)
        except Exception:
            pass

    return {
        "status": "online",
        "api_keys": {
            "gemini": has_gemini,
            "serper": has_serper,
            "sarvam": has_sarvam
        },
        "database": {
            "seeded_claims_count": db_size,
            "cached_embeddings_count": cache_size
        },
        "system_time": time.time()
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

# Mount static files for the web dashboard at the root URL
static_dir = BACKEND_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000)
