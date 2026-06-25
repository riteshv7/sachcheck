import re
import sys
import json
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("sachcheck.wer")

def normalize_text(text: str) -> List[str]:
    """
    Normalizes text for word-level evaluation:
    - Converts to lowercase
    - Strips punctuation (retaining alphanumeric characters and spaces)
    - Splits into a list of words, removing extra whitespace
    """
    if not text:
        return []
    # Lowercase
    text = text.lower()
    # Remove punctuation, replace with space
    text = re.sub(r"[^\w\s]", " ", text)
    # Split by whitespace
    words = text.strip().split()
    return words

def calculate_wer(reference_words: List[str], hypothesis_words: List[str]) -> Tuple[float, int, int, int]:
    """
    Calculates the Word Error Rate (WER) between a reference word sequence (ground truth)
    and a hypothesis word sequence (ASR output) using Levenshtein distance.
    
    Returns:
        A tuple of (wer_value, substitutions, deletions, insertions)
    """
    r_len = len(reference_words)
    h_len = len(hypothesis_words)
    
    # Handle edge cases
    if r_len == 0 and h_len == 0:
        return 0.0, 0, 0, 0
    if r_len == 0:
        return 1.0, 0, 0, h_len  # All insertions
    if h_len == 0:
        return 1.0, 0, r_len, 0  # All deletions

    # Initialize DP table
    # dp[i][j] stores the edit distance between reference_words[:i] and hypothesis_words[:j]
    dp = [[0] * (h_len + 1) for _ in range(r_len + 1)]
    
    for i in range(r_len + 1):
        dp[i][0] = i
    for j in range(h_len + 1):
        dp[0][j] = j
        
    # Populate DP table
    for i in range(1, r_len + 1):
        for j in range(1, h_len + 1):
            if reference_words[i - 1] == hypothesis_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                substitution = dp[i - 1][j - 1] + 1
                deletion = dp[i - 1][j] + 1
                insertion = dp[i][j - 1] + 1
                dp[i][j] = min(substitution, deletion, insertion)
                
    # Backtrack to identify substitutions, deletions, and insertions
    i = r_len
    j = h_len
    substitutions = 0
    deletions = 0
    insertions = 0
    
    while i > 0 or j > 0:
        if i > 0 and j > 0 and reference_words[i - 1] == hypothesis_words[j - 1]:
            i -= 1
            j -= 1
        else:
            current = dp[i][j]
            # Substitution check
            if i > 0 and j > 0 and current == dp[i - 1][j - 1] + 1:
                substitutions += 1
                i -= 1
                j -= 1
            # Deletion check
            elif i > 0 and current == dp[i - 1][j] + 1:
                deletions += 1
                i -= 1
            # Insertion check
            elif j > 0 and current == dp[i][j - 1] + 1:
                insertions += 1
                j -= 1
            else:
                # Fallback tie breaker
                if i > 0 and j > 0:
                    substitutions += 1
                    i -= 1
                    j -= 1
                elif i > 0:
                    deletions += 1
                    i -= 1
                else:
                    insertions += 1
                    j -= 1
                    
    wer_value = dp[r_len][h_len] / r_len
    return wer_value, substitutions, deletions, insertions

def evaluate_transcript_texts(ground_truth: str, machine_transcript: str) -> Dict[str, Any]:
    """
    Normalizes both texts and evaluates ASR quality metrics.
    """
    ref_words = normalize_text(ground_truth)
    hyp_words = normalize_text(machine_transcript)
    
    wer, s, d, i = calculate_wer(ref_words, hyp_words)
    
    return {
        "wer": wer,
        "substitutions": s,
        "deletions": d,
        "insertions": i,
        "reference_word_count": len(ref_words),
        "hypothesis_word_count": len(hyp_words)
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SachCheck ASR WER Evaluation Utility")
    parser.add_argument("ground_truth", help="Path to the ground truth text file")
    parser.add_argument("machine_transcript", help="Path to the machine-generated text file")
    
    args = parser.parse_args()
    
    try:
        with open(args.ground_truth, "r", encoding="utf-8") as f:
            gt_text = f.read()
        with open(args.machine_transcript, "r", encoding="utf-8") as f:
            mt_text = f.read()
            
        report = evaluate_transcript_texts(gt_text, mt_text)
        
        print("\n" + "=" * 50)
        print(" WORD ERROR RATE (WER) EVALUATION REPORT")
        print("=" * 50)
        print(f"Reference Words (Ground Truth): {report['reference_word_count']}")
        print(f"Hypothesis Words (ASR Output):  {report['hypothesis_word_count']}")
        print(f"Substitutions (S):             {report['substitutions']}")
        print(f"Deletions (D):                 {report['deletions']}")
        print(f"Insertions (I):                {report['insertions']}")
        print(f"Total Errors (S + D + I):       {report['substitutions'] + report['deletions'] + report['insertions']}")
        print("-" * 50)
        print(f"WORD ERROR RATE (WER):          {report['wer']:.2%} ({report['wer']:.4f})")
        print("=" * 50)
        
    except Exception as err:
        logger.exception(f"WER evaluation failed: {err}")
        sys.exit(1)
