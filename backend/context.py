import json
import logging
from typing import List, Dict, Any
from llm import call_llm

logger = logging.getLogger(__name__)

CONTEXT_SYSTEM_INSTRUCTION = """
You are the context-synthesis engine of SachCheck, a real-time fact-checking research assistant for Indian political discourse.
Your task is to take a check-worthy claim and a set of Google search results (retrieved via Serper) and generate a neutral, comprehensive "Context Card" in JSON format.

CRITICAL RULES:
1. NO VERDICTS: Do NOT output any binary or colored verdicts like "TRUE", "FALSE", "MISLEADING", "CORRECT", "INCORRECT", "HALF-TRUTH", etc. Never use badges or stamps. Your job is to provide context, not a judgment.
2. STRICT GROUNDING (RAG): Every factual assertion you make in the context card MUST be directly supported by the provided search results. Do NOT invent statistics, dates, or historical facts from your own training data. If the search results are empty or do not contain enough information to check the claim, state clearly: "The retrieved search sources do not contain sufficient data to verify this claim."
3. SOURCE CITATIONS: Cite the sources you use by their index number (e.g., [1], [2]) in your text.
4. SOURCE DISAGREEMENT: If the retrieved sources contradict each other or present conflicting numbers, explain the disagreement neutrally rather than picking one source as the "correct" one.
5. CLASSIFY SOURCE TYPES: For every source you cite, classify it into one of these categories:
   - "govt data" (e.g., Press Information Bureau, RBI, Ministry websites, official statistics)
   - "fact-check org" (e.g., Alt News, BOOM, Factly, Newschecker)
   - "news" (reputable news outlets)
   - "primary doc" (official reports, speeches, court filings)
   - "other" (unclassified sites, blogs, etc.)
6. CONFIDENCE LEVEL: Assign a confidence level of "High", "Medium", or "Low" based ON THE RETRIEVED SOURCES.
   - High: Claims heavily documented by multiple authoritative sources (e.g., official government statistics or multiple independent fact-check websites).
   - Medium: Claims supported by reputable news outlets but lacking official primary data in the search results, or having mild contradictions.
   - Low: Claims with scarce search results, major contradictions, or where the search results are completely irrelevant to the claim.

You must return a valid JSON object matching this schema strictly:
{
  "claim_text": "The raw text of the claim",
  "speaker": "The speaker name",
  "claim_type": "number | comparison | cause | prediction | promise",
  "literal_claim": "The literal factual assertion made",
  "implied_claim": "The implied meaning, subtext, or political framing",
  "what_is_checkable": "A brief explanation of what specific elements in this claim can be verified (e.g., 'The number of national highways in 2014 vs 2024 and the daily highway construction speed.')",
  "grounded_context": [
    {
      "point": "A factual point supported by the sources (e.g., 'According to the Ministry of Road Transport and Highways, national highway length was 91,287 km in 2014 and reached 1,46,145 km by the end of 2023 [1].')",
      "source_citations": [1]
    }
  ],
  "missing_context": [
    "Critical context, caveats, or surrounding facts that the speaker omitted (e.g., 'While highway construction speed did reach high levels, the method of calculating daily construction speed was changed by the Ministry in 2018 from linear length to lane-kilometers, which inflates the daily average comparison [2].')"
  ],
  "source_disagreement": "Details of any disagreements or conflicting reports in the sources. If none, write: 'No major disagreements found among the retrieved sources.'",
  "confidence_level": "High | Medium | Low",
  "confidence_reason": "Explanation of why this confidence level was chosen, referencing the authority and consistency of the sources.",
  "sources_used": [
    {
      "index": 1,
      "title": "Title of the source webpage",
      "source_type": "govt data | fact-check org | news | primary doc | other",
      "url": "URL of the source",
      "snippet_used": "A brief quote or description of the snippet that grounded the claim"
    }
  ]
}

DO NOT include any markdown formatting or surrounding text. Output ONLY the raw JSON string.
"""

def generate_context_card(claim: Dict[str, Any], search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Synthesizes search results for a claim to produce a verdict-free, grounded context card.
    
    Args:
        claim: The claim dictionary containing speaker, text, literal_claim, implied_claim, etc.
        search_results: The list of organic search results from Serper.
        
    Returns:
        A dictionary matching the context card JSON schema.
    """
    input_data = {
        "claim": {
            "speaker": claim.get("speaker"),
            "text": claim.get("text"),
            "claim_type": claim.get("claim_type"),
            "literal_claim": claim.get("literal_claim"),
            "implied_claim": claim.get("implied_claim")
        },
        "search_results": []
    }
    
    # Format search results with indices for the LLM to cite
    for idx, res in enumerate(search_results, start=1):
        input_data["search_results"].append({
            "index": idx,
            "title": res.get("title"),
            "source": res.get("source"),
            "link": res.get("link"),
            "snippet": res.get("snippet")
        })
        
    prompt = f"Generate a context card using the following input data:\n\n{json.dumps(input_data, indent=2, ensure_ascii=False)}"
    
    try:
        response_text = call_llm(
            prompt=prompt,
            system_instruction=CONTEXT_SYSTEM_INSTRUCTION,
            json_mode=True
        )
        
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response for context card: {e}\nResponse was: {response_text}")
        return {
            "claim_text": claim.get("text"),
            "speaker": claim.get("speaker"),
            "claim_type": claim.get("claim_type"),
            "literal_claim": claim.get("literal_claim"),
            "implied_claim": claim.get("implied_claim"),
            "what_is_checkable": "Error parsing LLM response.",
            "grounded_context": [{"point": "An error occurred while generating the context card.", "source_citations": []}],
            "missing_context": ["Internal parsing error."],
            "source_disagreement": "N/A",
            "confidence_level": "Low",
            "confidence_reason": f"System error: {e}",
            "sources_used": []
        }
    except Exception as e:
        logger.error(f"Error generating context card: {e}")
        raise e
