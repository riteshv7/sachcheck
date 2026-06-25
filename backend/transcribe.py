import os
import sys
import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sachcheck.transcribe")

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

def get_sarvam_client():
    """Initializes and returns the SarvamAI client if the API key is present."""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise ValueError(
            "Sarvam AI API key is missing. Please set SARVAM_API_KEY in backend/.env.\n"
            "You can sign up and get a key at https://dashboard.sarvam.ai"
        )
    from sarvamai import SarvamAI
    return SarvamAI(api_subscription_key=api_key)

def run_real_transcription(audio_path: str, num_speakers: int = None) -> list:
    """
    Executes the real asynchronous batch ASR pipeline via Sarvam's Saaras V3.
    """
    audio_file = Path(audio_path)
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
    logger.info(f"Initiating Sarvam ASR Batch Job for: {audio_file.name}")
    client = get_sarvam_client()
    
    # 1. Create the SpeechToTextJob
    logger.info("Step 1: Creating ASR batch job...")
    job = client.speech_to_text_job.create_job(
        model="saaras:v3",
        mode="codemix",
        with_diarization=True,
        num_speakers=num_speakers
    )
    job_id = job.job_id
    logger.info(f"Job created successfully. Job ID: {job_id}")
    
    # 2. Upload Files
    logger.info(f"Step 2: Uploading audio file '{audio_file.name}'...")
    job.upload_files(files=[str(audio_file)])
    logger.info("File upload complete.")
    
    # 3. Start the Job
    logger.info("Step 3: Starting transcription processing...")
    job.start()
    
    # 4. Wait for Job to Complete
    logger.info("Step 4: Waiting for ASR job to complete...")
    job.wait_until_complete()
    logger.info("ASR Job completed successfully!")
    
    # 5. Download Results
    logger.info("Step 5: Downloading transcription results...")
    output_dir = audio_file.parent
    job.download_outputs(output_dir=str(output_dir))
    
    # Read the downloaded JSON output
    json_path = output_dir / f"{audio_file.name}.json"
    if not json_path.exists():
        raise FileNotFoundError(f"ASR output JSON not found at: {json_path}")
         
    with open(json_path, "r", encoding="utf-8") as f:
        results = json.load(f)
         
    # Format the results into a standardized segment list
    formatted_segments = []
    raw_segments = []
    
    if isinstance(results, list):
        raw_segments = results
    elif isinstance(results, dict):
        raw_segments = results.get("transcripts", []) or results.get("segments", []) or []
         
    for idx, seg in enumerate(raw_segments):
        # Extract transcript text and speaker labels
        text = seg.get("transcript", "") or seg.get("text", "")
        speaker_id = seg.get("speaker_id", "")
        speaker = seg.get("speaker", "")
        if not speaker:
            speaker = f"SPEAKER_{speaker_id}" if speaker_id else f"SPEAKER_{idx:02d}"
             
        formatted_segments.append({
            "speaker": speaker,
            "start_time": float(seg.get("start_time", 0.0)),
            "end_time": float(seg.get("end_time", 0.0)),
            "text": text
        })
        
    return formatted_segments

def run_mock_transcription(audio_path: str) -> list:
    """
    SIMULATED/MOCKED TRANSCRIPTION
    Generates a realistic diarized Hinglish transcript turn list for local testing.
    This is used for development when no Sarvam API key is configured.
    """
    logger.warning("==========================================================")
    logger.warning(" WARNING: RUNNING IN MOCK/DRY-RUN TRANSCRIPTION MODE      ")
    logger.warning(" No real API calls are being made to Sarvam AI ASR.        ")
    logger.warning(" This generates simulated diarized speech segments.      ")
    logger.warning("==========================================================")
    
    # We return a simulated transcript matching transcript_1 (unemployment debate)
    # with realistic timestamps and speaker labels.
    time.sleep(1.5)  # Simulate API latency
    
    mock_segments = [
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
    ]
    
    logger.info(f"Generated {len(mock_segments)} simulated diarized segments successfully.")
    return mock_segments

def transcribe_audio(audio_path: str, num_speakers: int = None, force_mock: bool = False) -> list:
    """
    Helper function to execute transcription. Automatically falls back to mock mode
    if SARVAM_API_KEY is missing, or if force_mock is True.
    """
    has_key = bool(os.getenv("SARVAM_API_KEY"))
    
    if force_mock or not has_key:
        return run_mock_transcription(audio_path)
    else:
        try:
            return run_real_transcription(audio_path, num_speakers)
        except Exception as e:
            logger.error(f"Real Sarvam transcription failed: {e}")
            logger.warning("Falling back to Mock/Simulated transcription due to error.")
            return run_mock_transcription(audio_path)

if __name__ == "__main__":
    # Command Line Interface
    import argparse
    parser = argparse.ArgumentParser(description="SachCheck ASR Batch Audio Transcription Utility")
    parser.add_argument("audio_path", help="Path to the input audio file (WAV/MP3)")
    parser.add_argument("--speakers", type=int, default=None, help="Number of speakers (optional)")
    parser.add_argument("--mock", action="store_true", help="Force run in mock/dry-run mode")
    parser.add_argument("--output", help="Path to save the output JSON (optional)")
    
    args = parser.parse_args()
    
    try:
        segments = transcribe_audio(args.audio_path, args.speakers, args.mock)
        
        # Print results in human-readable format
        print("\n" + "=" * 60)
        print(" DIARIZED TRANSCRIPTION OUTPUT")
        print("=" * 60)
        for seg in segments:
            print(f"[{seg['speaker']}] ({seg['start_time']:.1f}s - {seg['end_time']:.1f}s):")
            print(f"  \"{seg['text']}\"")
            print("-" * 40)
            
        # Save output if requested
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, indent=2, ensure_ascii=False)
            print(f"\nResults saved to: {out_path}")
            
    except Exception as err:
        logger.exception(f"ASR Transcription utility failed: {err}")
        sys.exit(1)
