import re
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sachcheck.youtube")

# Append local bin path where Node.js is installed to allow yt-dlp to use the JS runtime
local_bin = "/Users/riteshverma/.local/bin"
if local_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{local_bin}{os.pathsep}{os.environ.get('PATH', '')}"


# Regex to extract YouTube video ID from various URL formats
YOUTUBE_ID_REGEX = re.compile(
    r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})'
)

def extract_video_id(url: str) -> Optional[str]:
    """
    Extracts the 11-character YouTube video ID from a URL.
    """
    match = YOUTUBE_ID_REGEX.search(url)
    if match:
        return match.group(1)
    return None

def get_youtube_transcript(url: str) -> List[Dict[str, Any]]:
    """
    Instantly retrieves and formats the transcript for a YouTube video.
    Groups individual caption segments into cohesive conversational "turns"
    of approximately 15-20 seconds to match the speaker-turn UI.
    
    Returns:
        A list of turns, where each turn is:
        {
            "speaker": "Speaker",
            "start_time": float,
            "end_time": float,
            "text": str
        }
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL: {url}")
        
    logger.info(f"Fetching YouTube transcript for video ID: {video_id}")
    
    api = YouTubeTranscriptApi()
    raw_segments = None
    try:
        # Try fetching Hindi, Hinglish, and English transcripts first
        fetched = api.fetch(video_id, languages=['hi', 'en', 'en-IN'])
        raw_segments = fetched.to_raw_data()
    except Exception as e:
        logger.warning(f"Preferred languages hi/en not found, attempting fallback. Error: {e}")
        try:
            # Fallback to the first available transcript (including auto-generated)
            transcript_list = api.list(video_id)
            # Find the first transcript and fetch it
            first_transcript = next(iter(transcript_list))
            raw_segments = first_transcript.fetch().to_raw_data()
            logger.info(f"Successfully retrieved fallback transcript (Language: {first_transcript.language})")
        except Exception as fallback_err:
            logger.error(f"Failed to retrieve any transcript: {fallback_err}")
            raise RuntimeError(f"No transcripts or captions available for this video: {fallback_err}")
            
    if not raw_segments:
        raise RuntimeError("Retrieved empty transcript from YouTube.")
        
    # Group raw segments into cohesive conversational "turns" of ~15 seconds
    turns = []
    current_text = []
    current_start = None
    current_end = None
    
    # We group segments that fall within a 15-second window
    chunk_duration = 15.0
    
    for seg in raw_segments:
        start = float(seg.get("start", 0.0))
        duration = float(seg.get("duration", 0.0))
        end = start + duration
        text = seg.get("text", "").strip()
        
        # Skip empty captions or music tags
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
            # Close the current turn and start a new one
            turns.append({
                "speaker": "Presenter",  # Default speaker label since YT captions lack speaker IDs
                "start_time": round(current_start, 2),
                "end_time": round(current_end, 2),
                "text": " ".join(current_text)
            })
            current_start = start
            current_end = end
            current_text = [text]
            
    # Append the last remaining segment
    if current_text:
        turns.append({
            "speaker": "Presenter",
            "start_time": round(current_start, 2),
            "end_time": round(current_end, 2),
            "text": " ".join(current_text)
        })
        
    logger.info(f"Grouped {len(raw_segments)} raw captions into {len(turns)} conversational turns.")
    return turns

def download_youtube_audio(url: str, output_dir: Path) -> Path:
    """
    Downloads only the audio track of a YouTube video using yt-dlp.
    Saves the file to output_dir.
    
    Returns:
        The absolute Path to the downloaded audio file.
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL: {url}")
        
    output_dir.mkdir(parents=True, exist_ok=True)
    # Template to save file named as {video_id}.webm/m4a in the output directory
    outtmpl = str(output_dir / f"{video_id}.%(ext)s")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
    }
    
    logger.info(f"Downloading YouTube audio for video {video_id} to: {output_dir}")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=True)
        # Find the actual filename of the downloaded file (which includes the format extension)
        filename = ydl.prepare_filename(info_dict)
        
    downloaded_path = Path(filename)
    if not downloaded_path.exists():
        # Sometimes extension might differ slightly, let's search the directory for the video_id
        for p in output_dir.glob(f"{video_id}.*"):
            if p.suffix in [".webm", ".m4a", ".opus", ".mp3", ".wav"]:
                downloaded_path = p
                break
                
    if not downloaded_path.exists():
        raise FileNotFoundError(f"Failed to locate downloaded audio file for video ID: {video_id}")
        
    logger.info(f"Successfully downloaded YouTube audio to: {downloaded_path.name}")
    return downloaded_path.resolve()

if __name__ == "__main__":
    # Command Line Interface for quick testing
    import sys
    if len(sys.argv) < 2:
        print("Usage: python backend/youtube.py <youtube_url>")
        sys.exit(1)
        
    url = sys.argv[1]
    
    # Test Transcript Fetching
    try:
        turns = get_youtube_transcript(url)
        print("\n" + "="*50)
        print(" FETCHED TRANSCRIPT PREVIEW (First 5 turns)")
        print("="*50)
        for t in turns[:5]:
            print(f"[{t['speaker']}] ({t['start_time']}s - {t['end_time']}s): {t['text']}")
            print("-"*30)
    except Exception as e:
        print(f"\nTranscript fetching failed: {e}")
        print("Attempting audio download fallback...")
        try:
            temp_dir = Path(__file__).parent.parent / "data" / "audio"
            audio_path = download_youtube_audio(url, temp_dir)
            print(f"Successfully downloaded audio file: {audio_path}")
        except Exception as dl_err:
            print(f"Audio download also failed: {dl_err}")
