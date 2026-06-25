import json
import logging
from typing import List, Dict, Any
from llm import call_llm

logger = logging.getLogger("sachcheck.cleanup")

# Political Vocabulary & Hotword Reference List
POLITICAL_HOTWORDS = [
    # Parties
    "BJP", "BJP (Bharatiya Janata Party)", "Congress", "INC (Indian National Congress)", "AAP (Aam Aadmi Party)", "TMC", "SP (Samajwadi Party)", "BSP", "CPI(M)",
    # Leaders
    "Narendra Modi", "PM Modi", "Rahul Gandhi", "Amit Shah", "Arvind Kejriwal", "Mallikarjun Kharge", "Yogi Adityanath",
    # Welfare Schemes / Policies
    "Ayushman Bharat", "Pradhan Mantri Jan Arogya Yojana (PMJAY)", "PM Mudra Yojana", "Mudra Scheme", "PMMY",
    "Deen Dayal Upadhyaya Gram Jyoti Yojana", "DDUGJY", "Lakhpati Didi", "PM-KISAN", "Pradhan Mantri Awas Yojana (PMAY)",
    "Pradhan Mantri Garib Kalyan Anna Yojana (PMGKAY)", "Jan Dhan Yojana (PMJDY)", "Ujjwala Yojana",
    # Economic/Statistical Terms & Institutions
    "EPFO (Employees' Provident Fund Organisation)", "PLFS (Periodic Labour Force Survey)", "NSSO", "GDP", "RBI", "GST", "UPI", "NITI Aayog", "unemployment rate", "inflation",
    # Common code-mixed numbers / concepts
    "crore", "lakh", "percent", "billion", "million"
]

CLEANUP_SYSTEM_INSTRUCTION = """
You are the transcription-cleanup module of SachCheck, a fact-checking research assistant for Indian political discourse.
Your task is to review a list of machine-transcribed Hinglish (code-mixed Hindi-English) speech segments and correct obvious phonetic ASR (Speech-to-Text) errors.

You are provided with a reference list of POLITICAL HOTWORDS:
{hotwords_list}

RULES FOR CLEANUP:
1. STRICT SPELLING CORRECTION ONLY: Correct obvious phonetic misspellings, garbled audio terms, or incorrect representations of political parties, leaders, schemes, locations, and data terms (e.g., correct "ayushman bhari" or "ayushman bharat scheme" to "Ayushman Bharat", "bjp" to "BJP", "niti ayog" to "NITI Aayog", "epfo" to "EPFO").
2. DO NOT REWRITE: Never rewrite sentences, do not improve grammar, do not translate, and do not summarize what the speaker said. Keep their exact words, phrasing, colloquialisms, and code-mixed structure (Hinglish). Only fix spelling/transcription errors.
3. CONVERT NUMBERS: Convert spoken Hinglish numbers to digits for readability where appropriate (e.g., "ek point teen crore" to "1.3 crore", "do crore" to "2 crore", "forty crore" to "40 crore").
4. PRESERVE STRUCTURE: You will receive a JSON list of segments with an "index" and "text". You MUST return a JSON list containing the exact same number of items, where each item has the "index" and the corrected "text". Do NOT alter the index.

Example Input:
[
  {{
    "index": 0,
    "text": "bjp government ne har saal do crore naukriyon ka vaada kiya tha"
  }},
  {{
    "index": 1,
    "text": "hamne epfo data ke mutabik ek point teen crore jobs generate ki hain"
  }}
]

Example Output:
[
  {{
    "index": 0,
    "text": "BJP government ne har saal 2 crore naukriyon ka vaada kiya tha"
  }},
  {{
    "index": 1,
    "text": "hamne EPFO data ke mutabik 1.3 crore jobs generate ki hain"
  }}
]

DO NOT include any markdown formatting or surrounding text. Output ONLY the raw JSON list.
"""

def llm_cleanup_transcript(diarized_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Applies an LLM-based cleanup pass to correct phonetic STT errors in Hinglish segments.
    Merges corrected text back into the original segment dictionaries (preserving speakers/timestamps).
    
    Args:
        diarized_segments: A list of diarized segment dictionaries (speaker, start_time, end_time, text).
        
    Returns:
        A new list of diarized segment dictionaries with cleaned text.
    """
    if not diarized_segments:
        return []
        
    logger.info(f"Starting LLM transcript cleanup pass for {len(diarized_segments)} segments...")
    
    # Extract only index and text to send to LLM (prevents model from corrupting speaker/timestamps)
    llm_input = []
    for idx, seg in enumerate(diarized_segments):
        llm_input.append({
            "index": idx,
            "text": seg.get("text", "")
        })
        
    hotwords_str = ", ".join(POLITICAL_HOTWORDS)
    system_instruction = CLEANUP_SYSTEM_INSTRUCTION.format(hotwords_list=hotwords_str)
    prompt = f"Perform transcription cleanup on this JSON data:\n\n{json.dumps(llm_input, indent=2, ensure_ascii=False)}"
    
    try:
        response_text = call_llm(
            prompt=prompt,
            system_instruction=system_instruction,
            json_mode=True
        )
        
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        corrected_list = json.loads(response_text)
        
        # Create a lookup dictionary of corrected text by index
        corrections_by_index = {}
        for item in corrected_list:
            idx = item.get("index")
            text = item.get("text")
            if idx is not None and text is not None:
                corrections_by_index[int(idx)] = text
                
        # Merge corrections back into a copy of the original segments
        cleaned_segments = []
        for idx, seg in enumerate(diarized_segments):
            cleaned_seg = seg.copy()
            # If a correction was returned, use it; otherwise fallback to original
            if idx in corrections_by_index:
                cleaned_seg["text"] = corrections_by_index[idx]
            cleaned_segments.append(cleaned_seg)
            
        logger.info("LLM transcript cleanup pass complete.")
        return cleaned_segments
        
    except Exception as e:
        logger.error(f"Error during LLM transcript cleanup: {e}. Returning original segments.")
        # Fallback: return copy of original segments if LLM pass fails (prevents breaking pipeline)
        return [seg.copy() for seg in diarized_segments]

if __name__ == "__main__":
    # Quick CLI test
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            data = json.load(f)
        print("Cleaning...")
        cleaned = llm_cleanup_transcript(data)
        print(json.dumps(cleaned, indent=2, ensure_ascii=False))
    else:
        # Simple self-test
        sample = [
            {"speaker": "Speaker 1", "start_time": 0.0, "end_time": 5.0, "text": "bjp ne mudra loan under 40 crore se zyada loans diye"},
            {"speaker": "Speaker 2", "start_time": 5.0, "end_time": 10.0, "text": "par niti ayog says average loan is very small"}
        ]
        print("Self-Test Running...")
        cleaned = llm_cleanup_transcript(sample)
        print("Original:\n", json.dumps(sample, indent=2))
        print("Cleaned:\n", json.dumps(cleaned, indent=2))
