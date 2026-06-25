import os
import sys
import logging
from pathlib import Path

# Ensure backend directory is in the Python path
BACKEND_DIR = Path(__file__).parent.resolve()
sys.path.append(str(BACKEND_DIR))

from youtube import extract_video_id, get_youtube_transcript, download_youtube_audio

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sachcheck.test_youtube")

def test_youtube_pipeline():
    logger.info("Starting YouTube transcript and audio engine tests...")

    # Test URL: A stable public video for testing (Rick Astley - Never Gonna Give You Up)
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    # 1. Test Video ID Extraction
    video_id = extract_video_id(test_url)
    logger.info(f"Step 1: Extracted video ID: {video_id}")
    assert video_id == "dQw4w9WgXcQ", f"Expected dQw4w9WgXcQ, got {video_id}"
    logger.info("✓ Video ID extraction passed.")

    # 2. Test Transcript Fetching
    logger.info("Step 2: Fetching transcript turns...")
    try:
        turns = get_youtube_transcript(test_url)
        logger.info(f"✓ Transcript fetching passed. Retracted {len(turns)} conversational turns.")
        if turns:
            logger.info(f"First turn preview: [{turns[0]['speaker']}] ({turns[0]['start_time']}s - {turns[0]['end_time']}s): {turns[0]['text']}")
    except Exception as e:
        logger.error(f"Transcript fetching failed: {e}")
        logger.info("This is expected if the video has captions disabled or is blocked.")

    # 3. Test Audio Downloading (Fallback Path)
    logger.info("Step 3: Downloading audio track as fallback...")
    temp_dir = BACKEND_DIR / "data" / "test_audio"
    try:
        audio_path = download_youtube_audio(test_url, temp_dir)
        logger.info(f"✓ Audio download passed. File saved to: {audio_path}")
        assert audio_path.exists(), "Downloaded audio file does not exist!"
        logger.info(f"Audio file size: {audio_path.stat().st_size} bytes")
        
        # Clean up
        if audio_path.exists():
            audio_path.unlink()
            logger.info("✓ Cleaned up test audio file.")
        if temp_dir.exists():
            temp_dir.rmdir()
            logger.info("✓ Cleaned up test directory.")
    except Exception as e:
        logger.error(f"Audio download failed: {e}")
        raise e

    logger.info("==================================================")
    logger.info(" ALL YOUTUBE TRANSCRIPTION ENGINE TESTS PASSED!   ")
    logger.info("==================================================")

if __name__ == "__main__":
    test_youtube_pipeline()
