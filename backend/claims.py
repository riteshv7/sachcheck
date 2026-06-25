import json
import logging
from typing import List, Dict, Any
from llm import call_llm

logger = logging.getLogger(__name__)

CLAIMS_SYSTEM_INSTRUCTION = """
You are the core intelligence of SachCheck, a real-time fact-checking research assistant for Indian political discourse.
Your input is code-mixed Hindi-English (Hinglish) text transcript.
Your task is to analyze the transcript and extract all factual claims made by the speakers.

You must evaluate and classify each claim according to these precise criteria:

1. Language Understanding (Hinglish):
   - You must understand code-mixed Hindi-English (e.g., "2 crore naukriyan", "national highways ki length double", "inflation control mein hai").
   - Perform semantic analysis on Hinglish text in Latin script (e.g., recognizing that "bijli" means electricity, "naukri" means job, "mehangai" means inflation, "garib" means poor).

2. Claim Detection & Check-Worthiness:
   - Identify sentences where a speaker asserts a statement of fact about the past, present, or a concrete future target.
   - For each statement, determine if it is "Check-Worthy" (check_worthy = true or false).
   - Check-worthy: Specific, verifiable statements involving statistics, historical records, policy actions, infrastructure metrics, economic indicators, or comparative performance.
   - NOT Check-worthy: Vague opinions, insults, general political rhetoric, future predictions/promises without factual assertions, or casual chatter.

3. Claim Type Classification:
   - Classify each claim into exactly one of these types:
     * "number": Contains specific statistics, percentages, currency, counts, or measurements (e.g., "40 crore loans", "₹5 lakh insurance").
     * "comparison": Compares two entities, political parties, time periods, or policies (e.g., "average inflation rate was 10.4% under UPA vs 5% now").
     * "cause": Asserts a direct cause-and-effect relationship between a policy/action and an outcome (e.g., "Ayushman Bharat scheme ke chalte ₹1 lakh crore bache").
     * "prediction": Verifiable assertions about future outcomes (e.g., "we will reach 500 GW by 2030").
     * "promise": Pledges, commitments, or manifestos for the future.
   - Note: If a claim fits multiple types (e.g., a numerical comparison), choose the most dominant one (e.g., "comparison" or "number").

4. Literal vs. Implied Meaning (Crucial for "true but misleading" claims):
   - "literal_claim": What the speaker explicitly stated in the text (translated/summarized in clear English/Hinglish).
   - "implied_claim": The subtext, insinuation, or political framing of the statement. What is the speaker trying to make the audience believe? (e.g., if they compare gas prices, they are implying government failure or success in managing cost of living).

You must return a valid JSON object matching this schema strictly:
{
  "claims": [
    {
      "speaker": "Name or role of the speaker (e.g., Pravakta A, Neta, Anchor)",
      "text": "The raw transcript sentence or segment containing the claim",
      "check_worthy": true,
      "reason_check_worthy": "A clear, concise reason explaining why this claim is check-worthy (e.g., 'Asserts a specific historical inflation rate comparison') or why it is not (e.g., 'General political opinion and rhetoric')",
      "claim_type": "number | comparison | cause | prediction | promise",
      "literal_claim": "The literal factual assertion made in the sentence",
      "implied_claim": "The underlying insinuation, framing, or subtext of the claim"
    }
  ]
}

DO NOT include any markdown formatting or surrounding text. Output ONLY the raw JSON string.
"""

def analyze_transcript_claims(transcript_text: str) -> List[Dict[str, Any]]:
    """
    Analyzes a Hinglish transcript to extract, filter, and classify claims.
    
    Args:
        transcript_text: The full plain-text transcript of a political clip.
        
    Returns:
        A list of dictionaries representing the extracted claims and their classifications.
    """
    prompt = f"Analyze the following Hinglish transcript and extract all claims:\n\n{transcript_text}"
    
    try:
        response_text = call_llm(
            prompt=prompt,
            system_instruction=CLAIMS_SYSTEM_INSTRUCTION,
            json_mode=True
        )
        
        # Clean the response just in case markdown fences are present
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        data = json.loads(response_text)
        return data.get("claims", [])
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response from LLM: {e}\nResponse was: {response_text}")
        # Return empty list in case of parsing failure
        return []
    except Exception as e:
        logger.error(f"Error analyzing transcript claims: {e}")
        raise e

if __name__ == "__main__":
    import sys
    # Quick CLI test
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            text = f.read()
        print("Analyzing...")
        claims = analyze_transcript_claims(text)
        print(json.dumps(claims, indent=2, ensure_ascii=False))
    else:
        print("Usage: python backend/claims.py <transcript_file_path>")
