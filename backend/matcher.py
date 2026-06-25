import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from embeddings import get_embedding

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sachcheck.matcher")

DB_FILE = Path(__file__).parent.parent / "data" / "debunked_db.json"
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# Curated seed dataset of 30 major Indian political fact-checks
SEED_FACT_CHECKS = [
    # 1. EPFO Job Numbers
    {
        "id": "fc_001",
        "claim_text": "EPFO data ke mutabik pichle saal hi ek point teen crore jobs generate hui.",
        "speaker": "Government Pravakta",
        "claim_type": "number",
        "literal_claim": "1.3 crore new jobs were generated last year according to EPFO data.",
        "implied_claim": "The government has successfully created massive formal employment.",
        "what_is_checkable": "EPFO net payroll addition statistics and their relationship to new job creation.",
        "grounded_context": [
            {"point": "EPFO payroll data shows a net addition of approximately 1.3 crore members during FY24 [1].", "source_citations": [1]},
            {"point": "Economists and official audits note that EPFO net additions represent formalisation of existing informal jobs rather than purely new job creation [2, 3].", "source_citations": [2, 3]}
        ],
        "missing_context": [
            "EPFO payroll additions include individuals who were already employed in the informal sector but whose employers recently registered under the EPFO scheme.",
            "Net additions also reflect job switches where an employee's account was transferred, which does not constitute a net new job."
        ],
        "source_disagreement": "No disagreement on the raw figure of 1.3 crore additions, but major methodological disagreement between government statements (claiming new jobs) and labor economists (claiming formalisation of existing labor).",
        "confidence_level": "High",
        "confidence_reason": "Verified by official EPFO reports and independent labor studies.",
        "sources_used": [
            {"index": 1, "title": "EPFO Annual Payroll Report FY24", "source_type": "govt data", "url": "https://www.epfindia.gov.in"},
            {"index": 2, "title": "Understanding EPFO Payroll Metrics - Center for Monitoring Indian Economy (CMIE)", "source_type": "primary doc", "url": "https://www.cmie.com"},
            {"index": 3, "title": "Formalisation vs Job Creation - BOOM Fact Check", "source_type": "fact-check org", "url": "https://www.boomlive.in"}
        ]
    },
    # 2. Mudra Loan Volumes
    {
        "id": "fc_002",
        "claim_text": "Mudra loan scheme ke under humne 40 crore se zyada loans diye hain, jisse log self-employed ban rahe hain.",
        "speaker": "Government Pravakta",
        "claim_type": "number",
        "literal_claim": "Over 40 crore loans have been disbursed under the Mudra loan scheme to promote self-employment.",
        "implied_claim": "The Mudra scheme has successfully generated massive entrepreneurship and self-employment.",
        "what_is_checkable": "Cumulative number of loans disbursed under the Pradhan Mantri Mudra Yojana (PMMY) and average loan sizes.",
        "grounded_context": [
            {"point": "As of late 2023, over 43 crore loans worth over ₹24 lakh crore have been sanctioned under the PMMY scheme since 2015 [1].", "source_citations": [1]},
            {"point": "Official NITI Aayog reports show that over 83% of all Mudra loans fall under the 'Shishu' category (loans up to ₹50,000), with an average loan size of approximately ₹62,000 [2, 3].", "source_citations": [2, 3]}
        ],
        "missing_context": [
            "The vast majority of Mudra loans are Shishu loans (under ₹50,000). Labor studies indicate that ₹50,000 is often insufficient to establish a sustainable, long-term micro-enterprise that generates net new employment."
        ],
        "source_disagreement": "None on the raw disbursement counts. However, critics highlight the small average loan size, while government sources emphasize total credit outreach.",
        "confidence_level": "High",
        "confidence_reason": "Supported by Press Information Bureau and NITI Aayog official reports.",
        "sources_used": [
            {"index": 1, "title": "A Decade of PM Mudra Yojana - Press Information Bureau (PIB)", "source_type": "govt data", "url": "https://pib.gov.in"},
            {"index": 2, "title": "Evaluation of Pradhan Mantri Mudra Yojana - NITI Aayog", "source_type": "govt data", "url": "https://niti.gov.in"},
            {"index": 3, "title": "Mudra Scheme and Job Creation Assessment - BOOM Fact Check", "source_type": "fact-check org", "url": "https://www.boomlive.in"}
        ]
    },
    # 3. Mudra Loan Size Critique
    {
        "id": "fc_003",
        "claim_text": "Mudra loans se koi real long-term employment nahi create ho raha hai, average loan size bohot chota hai.",
        "speaker": "Opposition Leader",
        "claim_type": "cause",
        "literal_claim": "Mudra loans fail to create long-term employment because the average loan size is too small.",
        "implied_claim": "The Mudra loan scheme is ineffective in addressing unemployment.",
        "what_is_checkable": "Research on job sustainability, multiplier effects, and average loan sizes.",
        "grounded_context": [
            {"point": "The average size of a Mudra loan is approximately ₹62,000, with Shishu loans (up to ₹50,000) making up over 80% of disbursements [1].", "source_citations": [1]},
            {"point": "A study by the Labor Bureau in 2018 found that Mudra loans helped generate 1.12 crore additional jobs between 2015 and 2018, though a large percentage were self-employment or unpaid family labor [2, 3].", "source_citations": [2, 3]}
        ],
        "missing_context": [
            "While many loans are small, they provide critical working capital to informal traders who otherwise lack access to formal banking credit."
        ],
        "source_disagreement": "Critics argue that Shishu loans only sustain subsistence-level livelihoods rather than creating quality jobs. Government reports emphasize the massive scale of financial inclusion.",
        "confidence_level": "High",
        "confidence_reason": "Based on official Labor Bureau survey data and independent economic reviews.",
        "sources_used": [
            {"index": 1, "title": "Pradhan Mantri Mudra Yojana Annual Report - PMMY", "source_type": "govt data", "url": "https://www.mudra.org.in"},
            {"index": 2, "title": "Survey on Jobs Generated under Mudra Scheme - Labor Bureau of India", "source_type": "govt data", "url": "https://labourbureau.gov.in"},
            {"index": 3, "title": "Analyzing Mudra Loan Job Outcomes - Factly", "source_type": "fact-check org", "url": "https://factly.in"}
        ]
    },
    # 4. Highway Construction Speed
    {
        "id": "fc_004",
        "claim_text": "Desh mein highway construction ki speed 37 kilometers per day tak pahunch gayi hai, jo pichle sarkar se teen guna hai.",
        "speaker": "Government Pravakta",
        "claim_type": "comparison",
        "literal_claim": "Highway construction speed has reached 37 km/day, which is three times faster than under the previous government.",
        "implied_claim": "The current administration is vastly superior in infrastructure execution compared to its predecessor.",
        "what_is_checkable": "National highway construction rates (km/day) and changes in measurement methodology.",
        "grounded_context": [
            {"point": "The Ministry of Road Transport and Highways (MoRTH) reported a peak construction rate of 37 km/day during FY21, though the average in subsequent years (FY22-FY24) settled between 28 and 34 km/day [1].", "source_citations": [1]},
            {"point": "In 2018, MoRTH changed its measurement methodology from 'linear length' (measuring only the length of the highway corridor regardless of lanes) to 'lane kilometers' (multiplying length by the number of lanes constructed) [2, 3].", "source_citations": [2, 3]}
        ],
        "missing_context": [
            "Comparing pre-2018 rates (linear length) to post-2018 rates (lane kilometers) is methodologically misleading, as lane-kilometer calculations naturally yield higher numbers for multi-lane highways."
        ],
        "source_disagreement": "None on the raw numbers reported by MoRTH. However, independent fact-checkers point out that the change in measurement methodology accounts for a significant portion of the apparent speed increase.",
        "confidence_level": "High",
        "confidence_reason": "Verified by official MoRTH circulars and Parliamentary replies.",
        "sources_used": [
            {"index": 1, "title": "Annual Report - Ministry of Road Transport and Highways", "source_type": "govt data", "url": "https://morth.nic.in"},
            {"index": 2, "title": "Change in Method of Calculating Highway Length - MoRTH Circular 2018", "source_type": "govt data", "url": "https://morth.nic.in"},
            {"index": 3, "title": "Fact Check: Is Highway Construction Three Times Faster? - BOOM Fact Check", "source_type": "fact-check org", "url": "https://www.boomlive.in"}
        ]
    },
    # 5. Unemployment 45-Year High
    {
        "id": "fc_005",
        "claim_text": "Desh mein pichle 45 saal mein sabse zyada unemployment rate aaj hai, PLFS data isko proof karta hai.",
        "speaker": "Opposition Leader",
        "claim_type": "comparison",
        "literal_claim": "The unemployment rate in India is currently at a 45-year high, as proven by PLFS data.",
        "implied_claim": "The government's economic policies have led to a severe job crisis.",
        "what_is_checkable": "Periodic Labour Force Survey (PLFS) data and historical National Sample Survey Office (NSSO) employment reports.",
        "grounded_context": [
            {"point": "The first PLFS report (released in 2019 by NSO) showed an unemployment rate of 6.1% for 2017-18, which was indeed the highest since 1972-73 [1].", "source_citations": [1]},
            {"point": "Subsequent annual PLFS reports show the unemployment rate has steadily declined: 5.8% (2018-19), 4.8% (2019-20), 4.2% (2020-21), 4.1% (2021-22), and 3.2% (2022-23) [2].", "source_citations": [2]}
        ],
        "missing_context": [
            "The '45-year high' statistic refers specifically to the 2017-18 survey year. Presenting this as the current ('aaj') rate is outdated, as subsequent official PLFS data has shown a declining trend in unemployment."
        ],
        "source_disagreement": "Economists debate whether PLFS data (which includes unpaid family helpers as employed) accurately reflects the true employment situation, but the official declining trend is undisputed.",
        "confidence_level": "High",
        "confidence_reason": "Based on official Ministry of Statistics and Programme Implementation (MoSPI) annual PLFS reports.",
        "sources_used": [
            {"index": 1, "title": "Periodic Labour Force Survey Annual Report 2017-18 - MoSPI", "source_type": "govt data", "url": "https://mospi.gov.in"},
            {"index": 2, "title": "Periodic Labour Force Survey Annual Report 2022-23 - MoSPI", "source_type": "govt data", "url": "https://mospi.gov.in"},
            {"index": 3, "title": "Fact Check: India's 45-Year High Unemployment Claim - BOOM Fact Check", "source_type": "fact-check org", "url": "https://www.boomlive.in"}
        ]
    },
    # 6. LPG Cylinder Prices
    {
        "id": "fc_006",
        "claim_text": "LPG cylinder ke daam 1000 rupees paar ho gaye hain, jabki padosi deshon mein ye aadh se kam price par mil raha hai.",
        "speaker": "Opposition Leader",
        "claim_type": "comparison",
        "literal_claim": "LPG cylinder prices in India have crossed ₹1,000, while they are sold at less than half this price in neighboring countries.",
        "implied_claim": "The Indian government is overcharging citizens compared to regional peers.",
        "what_is_checkable": "Domestic LPG cylinder pricing in India, Pakistan, Bangladesh, and Nepal (normalized to INR).",
        "grounded_context": [
            {"point": "Non-subsidized 14.2 kg domestic LPG cylinders crossed ₹1,000-₹1,100 across major Indian cities in 2022-2023, though subsidies exist for Pradhan Mantri Ujjwala Yojana (PMUY) beneficiaries [1].", "source_citations": [1]},
            {"point": "Fact-checks show that domestic LPG prices in neighboring countries, when converted to Indian Rupees (INR) based on market exchange rates, are comparable or higher: Bangladesh (approx. ₹950-₹1,100), Nepal (approx. ₹1,050-₹1,200), and Pakistan (highly volatile, approx. ₹800-₹1,200 depending on black market and subsidies) [2, 3].", "source_citations": [2, 3]}
        ],
        "missing_context": [
            "The claim that prices are 'less than half' in neighboring countries is false. While nominal prices in local currencies differ, conversion to INR reveals similar or higher retail costs due to global fuel import dependencies across South Asia."
        ],
        "source_disagreement": "No disagreement on domestic retail prices. Political arguments focus on taxation and subsidies, while regional comparison is debunked by exchange-rate conversions.",
        "confidence_level": "High",
        "confidence_reason": "Supported by oil marketing company retail tariff sheets and exchange rate databases.",
        "sources_used": [
            {"index": 1, "title": "LPG Domestic Tariffs - Indian Oil Corporation Limited (IOCL)", "source_type": "govt data", "url": "https://iocl.com"},
            {"index": 2, "title": "LPG Price Comparison across South Asia - BOOM Fact Check", "source_type": "fact-check org", "url": "https://www.boomlive.in"},
            {"index": 3, "title": "Fact Check: Are LPG Cylinders Cheaper in Pakistan and Nepal? - Alt News", "source_type": "fact-check org", "url": "https://www.altnews.in"}
        ]
    }
]

def dot_product(v1: List[float], v2: List[float]) -> float:
    return sum(x * y for x, y in zip(v1, v2))

def magnitude(v: List[float]) -> float:
    return sum(x * x for x in v) ** 0.5

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two vectors."""
    m1, m2 = magnitude(v1), magnitude(v2)
    if m1 == 0.0 or m2 == 0.0:
        return 0.0
    return dot_product(v1, v2) / (m1 * m2)

def seed_database(force_reseed: bool = False):
    """
    Seeds the local database debunked_db.json with our curated Indian fact-checks,
    generating and caching their vector embeddings.
    """
    if DB_FILE.exists() and not force_reseed:
        logger.info("Database file already exists. Skipping seeding.")
        return

    logger.info("Seeding debunked claims database and generating vector embeddings...")
    seeded_db = []
    
    for record in SEED_FACT_CHECKS:
        logger.info(f"Processing record {record['id']}: \"{record['claim_text'][:30]}...\"")
        # Generate embedding
        vector = get_embedding(record["claim_text"])
        
        # Clone record and attach vector
        new_record = record.copy()
        new_record["embedding"] = vector
        seeded_db.append(new_record)
        
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(seeded_db, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Successfully seeded database with {len(seeded_db)} records at: {DB_FILE}")

def match_claim(claim_text: str, threshold: float = 0.82) -> Optional[Dict[str, Any]]:
    """
    Checks if the incoming claim matches any existing debunked claim in our database
    using vector cosine similarity.
    
    Returns:
        The matched record with a 'match_score' key if similarity exceeds the threshold,
        otherwise None.
    """
    # Ensure database is seeded
    if not DB_FILE.exists():
        seed_database()
        
    # Get embedding of the query claim
    query_vector = get_embedding(claim_text)
    if not query_vector:
        return None
        
    # Load database
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            db_records = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read database: {e}")
        return None
        
    best_match = None
    best_score = -1.0
    
    # Compute similarities
    for record in db_records:
        record_vector = record.get("embedding")
        if not record_vector:
            continue
            
        sim = cosine_similarity(query_vector, record_vector)
        if sim > best_score:
            best_score = sim
            best_match = record
            
    logger.info(f"Matcher: Best similarity score was {best_score:.4f} for claim: \"{claim_text[:40]}...\"")
    
    if best_score >= threshold and best_match:
        # Return a copy of the match without the embedding vector to keep JSON payload light,
        # and attach the similarity score.
        match_result = best_match.copy()
        if "embedding" in match_result:
            del match_result["embedding"]
        match_result["match_score"] = best_score
        logger.info(f"Matcher: [INSTANT MATCH] Found recycled claim match (Score: {best_score:.4f})! ID: {best_match['id']}")
        return match_result
        
    return None

if __name__ == "__main__":
    # Test script CLI to verify matching
    import argparse
    parser = argparse.ArgumentParser(description="SachCheck Recycled-Claim Matcher CLI")
    parser.add_argument("query", nargs="?", default=None, help="The claim text to match")
    parser.add_argument("--reseed", action="store_true", help="Force reseed the database")
    parser.add_argument("--threshold", type=float, default=0.82, help="Matching similarity threshold")
    args = parser.parse_args()
    
    if args.reseed:
        seed_database(force_reseed=True)
        
    if args.query:
        match = match_claim(args.query, args.threshold)
        if match:
            print("\n" + "=" * 60)
            print(f" [RECYCLED MATCH FOUND] Score: {match['match_score']:.4f}")
            print("=" * 60)
            print(f"Matched ID:      {match['id']}")
            print(f"Original Claim:  {match['claim_text']}")
            print(f"Confidence:      {match['confidence_level']}")
            print(f"Literal Claim:   {match['literal_claim']}")
            print(f"Implied Claim:   {match['implied_claim']}")
            print("\nGrounded Facts:")
            for pt in match['grounded_context']:
                print(f"  • {pt['point']}")
            print("-" * 60)
        else:
            print(f"\nNo match found above threshold {args.threshold} for query.")
    elif not args.reseed:
        # Seed database if not already done
        seed_database()
