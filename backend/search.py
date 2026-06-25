import os
import json
import logging
import requests
from typing import List, Dict, Any
from llm import call_llm

logger = logging.getLogger(__name__)

QUERY_GENERATION_SYSTEM_INSTRUCTION = """
You are a research assistant for SachCheck, a fact-checking platform for Indian political discourse.
Your task is to take a check-worthy political claim (featuring literal and implied meanings, which might be in code-mixed Hindi-English/Hinglish) and generate 1 to 2 highly optimized, neutral search queries.

Guidelines:
1. Translate colloquial Hinglish terms into standard English or formal Hindi terms that would appear in official statistics, news articles, or fact-checks (e.g., convert "naukriyan" to "employment jobs data", "mehangai" to "inflation rate").
2. Keep specific Indian scheme names, political leaders, or government ministries intact (e.g., "Ayushman Bharat", "EPFO", "PLFS", "Mudra loan").
3. Make the queries completely neutral. Do not include biased words like "lie", "fake", "scam" or "achievement" unless they are part of the specific name of a topic.
4. Output the queries as a JSON list of strings.

Example:
Input:
{
  "speaker": "Pravakta B",
  "text": "EPFO data ke mutabik pichle saal hi 1.3 crore nayi jobs generate ki hain.",
  "literal_claim": "1.3 crore new jobs were generated last year according to EPFO data",
  "implied_claim": "The government has successfully generated massive employment in the formal sector."
}
Output:
[
  "EPFO new subscribers data last year jobs generated",
  "EPFO net payroll addition India statistics"
]

Output ONLY a valid JSON list of strings. No markdown formatting, no explanations.
"""

def generate_search_queries(claim: Dict[str, Any]) -> List[str]:
    """
    Uses the LLM to generate optimized search queries for a check-worthy claim.
    """
    claim_summary = {
        "speaker": claim.get("speaker"),
        "text": claim.get("text"),
        "literal_claim": claim.get("literal_claim"),
        "implied_claim": claim.get("implied_claim"),
        "claim_type": claim.get("claim_type")
    }
    
    prompt = f"Generate search queries for this claim:\n{json.dumps(claim_summary, indent=2, ensure_ascii=False)}"
    
    try:
        response_text = call_llm(
            prompt=prompt,
            system_instruction=QUERY_GENERATION_SYSTEM_INSTRUCTION,
            json_mode=True
        )
        
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        queries = json.loads(response_text)
        if isinstance(queries, list):
            return [q for q in queries if isinstance(q, str)]
        return []
    except Exception as e:
        logger.error(f"Error generating search queries: {e}")
        # Fallback query based on literal claim
        fallback = claim.get("literal_claim", claim.get("text", ""))
        return [fallback] if fallback else []

def execute_serper_search(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """
    Executes a search query using the Serper API, targeting the India region (gl='in').
    
    Args:
        query: The search query string.
        num_results: The number of organic search results to retrieve.
        
    Returns:
        A list of search results with titles, links, snippets, and source names.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise ValueError(
            "Serper API key is missing. Please set SERPER_API_KEY in backend/.env or your environment.\n"
            "You can get a free key (2,500 queries) from https://serper.dev"
        )
        
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    # Target 'in' (India) region for Indian political context
    payload = {
        "q": query,
        "num": num_results,
        "gl": "in" 
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        results_data = response.json()
        
        organic_results = results_data.get("organic", [])
        
        formatted_results = []
        for item in organic_results:
            formatted_results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": item.get("source", "") or item.get("link", "").split("/")[2] # Fallback to domain name
            })
            
        return formatted_results
    except Exception as e:
        logger.error(f"Serper API search failed for query '{query}': {e}")
        raise e

def search_for_claim(claim: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generates search queries for a claim and executes the search, merging results.
    """
    queries = generate_search_queries(claim)
    all_results = []
    seen_links = set()
    
    # Execute search for each generated query (usually 1 or 2)
    for query in queries[:2]:
        logger.info(f"Executing search for query: {query}")
        try:
            results = execute_serper_search(query)
            for res in results:
                if res["link"] not in seen_links:
                    seen_links.add(res["link"])
                    all_results.append(res)
        except Exception as e:
            logger.error(f"Search failed for query {query}: {e}")
            # Continue to next query or raise if no results at all
            
    return all_results

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    
    # Quick CLI test
    if len(sys.argv) > 1:
        query_str = sys.argv[1]
        print(f"Searching for: {query_str}")
        try:
            res = execute_serper_search(query_str)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        except Exception as err:
            print(f"Error: {err}")
    else:
        print("Usage: python backend/search.py <query>")
