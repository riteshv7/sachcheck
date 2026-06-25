import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure the backend directory is in the Python path
sys.path.append(str(Path(__file__).parent))

from claims import analyze_transcript_claims
from search import search_for_claim
from context import generate_context_card

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sachcheck.pipeline")

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

def run_pipeline(transcript_path: str, output_dir: str = "data/results") -> Dict[str, Any]:
    """
    Runs the entire SachCheck Phase 0 pipeline on a single transcript file.
    
    Args:
        transcript_path: Path to the plain-text Hinglish transcript file.
        output_dir: Directory where the output JSON results will be saved.
        
    Returns:
        A dictionary containing the pipeline results.
    """
    transcript_file = Path(transcript_path)
    if not transcript_file.exists():
        raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
        
    logger.info(f"Reading transcript from: {transcript_file}")
    with open(transcript_file, "r", encoding="utf-8") as f:
        transcript_text = f.read()
        
    logger.info("Step 1 & 2: Extracting claims and filtering for check-worthiness...")
    all_claims = analyze_transcript_claims(transcript_text)
    
    if not all_claims:
        logger.warning("No claims were extracted from the transcript. Check LLM configuration or transcript content.")
        return {"transcript": transcript_text, "check_worthy_claims": [], "ignored_claims": []}
        
    check_worthy_claims = []
    ignored_claims = []
    
    for claim in all_claims:
        if claim.get("check_worthy"):
            check_worthy_claims.append(claim)
        else:
            ignored_claims.append(claim)
            
    logger.info(f"Claim detection summary: Found {len(all_claims)} total claims. "
                f"{len(check_worthy_claims)} are check-worthy, {len(ignored_claims)} were filtered out.")
                
    context_cards = []
    
    # Process check-worthy claims
    for i, claim in enumerate(check_worthy_claims, start=1):
        logger.info(f"\n--- Processing Check-Worthy Claim {i}/{len(check_worthy_claims)} ---")
        logger.info(f"Speaker: {claim.get('speaker')}")
        logger.info(f"Claim: {claim.get('text')}")
        
        # Step 3: Search Web
        logger.info("Executing Serper web search for grounding...")
        try:
            search_results = search_for_claim(claim)
            logger.info(f"Retrieved {len(search_results)} search results.")
        except Exception as e:
            logger.error(f"Search failed for claim: {e}")
            search_results = []
            
        # Step 4: Context Card Synthesis (RAG)
        logger.info("Synthesizing context card...")
        try:
            context_card = generate_context_card(claim, search_results)
            context_cards.append(context_card)
        except Exception as e:
            logger.error(f"Context card generation failed: {e}")
            # Insert error placeholder (no silent mocks)
            context_cards.append({
                "claim_text": claim.get("text"),
                "speaker": claim.get("speaker"),
                "error": f"Failed to generate context card: {str(e)}"
            })
        
        # Pace API calls to respect free tier rate limits
        import time
        time.sleep(3)
            
    # Compile final report
    report = {
        "transcript_file": transcript_file.name,
        "summary": {
            "total_claims_detected": len(all_claims),
            "check_worthy_count": len(check_worthy_claims),
            "ignored_count": len(ignored_claims)
        },
        "context_cards": context_cards,
        "ignored_claims": ignored_claims
    }
    
    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    result_file = output_path / f"result_{transcript_file.stem}.json"
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    logger.info(f"\nPipeline finished! Results saved to: {result_file}")
    return report

def print_text_summary(report: Dict[str, Any]):
    """Prints a clean, human-readable terminal report of the pipeline results."""
    print("=" * 80)
    print(f" SACHCHECK CONTEXT CARD REPORT: {report.get('transcript_file')}")
    print("=" * 80)
    print(f"Claims Detected: {report['summary']['total_claims_detected']}")
    print(f"Check-Worthy:    {report['summary']['check_worthy_count']}")
    print(f"Ignored/Filtered: {report['summary']['ignored_count']}")
    print("=" * 80)
    
    if report["ignored_claims"]:
        print("\n--- FILTERED OUT CLAIMS (AUDIT LOG) ---")
        for claim in report["ignored_claims"]:
            print(f"[{claim.get('speaker')}] \"{claim.get('text')}\"")
            print(f"  -> Reason Dropped: {claim.get('reason_check_worthy')}")
            print("-" * 40)
            
    for idx, card in enumerate(report["context_cards"], start=1):
        if "error" in card:
            print(f"\n[CARD {idx}] ERROR: {card['error']}")
            continue
            
        print(f"\n--- CONTEXT CARD {idx}: [{card.get('speaker')}] ---")
        print(f"Claim:          {card.get('claim_text')}")
        print(f"Claim Type:     {card.get('claim_type').upper()}")
        print(f"Literal Claim:  {card.get('literal_claim')}")
        print(f"Implied Claim:  {card.get('implied_claim')}")
        print(f"What's Checkable: {card.get('what_is_checkable')}")
        
        print("\nGrounded Context:")
        for point_obj in card.get("grounded_context", []):
            citations = ", ".join(f"[{c}]" for c in point_obj.get("source_citations", []))
            print(f"  • {point_obj.get('point')} {citations}")
            
        print("\nMissing Context / Caveats:")
        for mc in card.get("missing_context", []):
            print(f"  • {mc}")
            
        print(f"\nSource Disagreements: {card.get('source_disagreement')}")
        print(f"Confidence Level:     {card.get('confidence_level')} - {card.get('confidence_reason')}")
        
        print("\nSources Cited:")
        for src in card.get("sources_used", []):
            print(f"  [{src.get('index')}] {src.get('title')} ({src.get('source_type')})")
            print(f"      URL: {src.get('url')}")
        print("-" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/pipeline.py <path_to_transcript>")
        sys.exit(1)
        
    try:
        results = run_pipeline(sys.argv[1])
        print_text_summary(results)
    except Exception as err:
        logger.exception(f"Pipeline execution failed: {err}")
        sys.exit(1)
