"""
Stage 7 -- Fact-Checking with Credible-Source Enforcement
Tadhkirat Dawood Al-Antaqi Project

Local (non-Colab) adaptation. Validates herb <-> disease treatment claims from
disease_treatment_english_v1.xlsx against modern sources, using gemini-3-flash-preview
+ Google Search grounding, with a real credibility check on the URLs actually
returned (not just prompt trust).

Auth: uses Application Default Credentials (ADC). Run once, locally, before
this script if you haven't already:

    gcloud auth application-default login

This script will check for valid ADC on startup and tell you to run that
command if it's missing -- it will not attempt to open a browser itself.
"""

import os
import random
import re
import sys
import time

import pandas as pd
import requests
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError

# -----------------------------------------------------------------------------
# PATHS (local, relative to this script's folder -- was /content/drive/MyDrive/...)
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

INPUT_FILE = os.path.join(DATA_DIR, "disease_treatment_english_v1.csv")
IDENTIFICATION_CSV = os.path.join(DATA_DIR, "plant_identification_v2.csv")
OUTPUT_CSV = os.path.join(DATA_DIR, "factcheck_credible_v1.csv")
PROGRESS_FILE = os.path.join(DATA_DIR, "factcheck_progress_v1.txt")

# -----------------------------------------------------------------------------
# SAMPLING (toggleable -- Stage 7 test run vs. full run)
# -----------------------------------------------------------------------------
SAMPLE_MODE = True          # set False to process the full dataset
SAMPLE_SEED = 42
SAMPLE_NUM_BLOCKS = 3
SAMPLE_BLOCK_SIZE = 100

# -----------------------------------------------------------------------------
# AUTH & CLIENT SETUP
# -----------------------------------------------------------------------------
try:
    google_auth_default()
except DefaultCredentialsError:
    sys.exit(
        "No Application Default Credentials found.\n"
        "Run this once in your terminal, then re-run this script:\n\n"
        "    gcloud auth application-default login\n"
    )

client = genai.Client(
    vertexai=True,
    project=os.environ.get("VERTEX_PROJECT_ID", "your-gcp-project-id"),
    location="global",  # required for gemini-3-flash-preview to support grounding
    http_options=types.HttpOptions(api_version="v1"),
)

MODEL = "gemini-3-flash-preview"

# -----------------------------------------------------------------------------
# CREDIBLE DOMAIN ALLOW-LIST (post-hoc verification, not a search filter)
# -----------------------------------------------------------------------------
# Vertex's Google Search grounding tool only supports exclude_domains, not an
# allow-list, so credibility is enforced by checking the ACTUAL citation URLs
# returned in groundingMetadata against this list.
# -----------------------------------------------------------------------------
CREDIBLE_DOMAIN_PATTERNS = [
    # Medical / scientific literature databases
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "nih.gov", "who.int",
    "cochranelibrary.com", "sciencedirect.com", "springer.com", "springerlink.com",
    "wiley.com", "onlinelibrary.wiley.com", "mdpi.com", "frontiersin.org",
    "nature.com", "cell.com", "plos.org", "tandfonline.com", "jstor.org",
    "bmj.com", "thelancet.com", "jamanetwork.com", "elsevier.com",
    "researchgate.net", "sciencedaily.com", "academic.oup.com",
    # Botanical / taxonomic authorities
    "gbif.org", "kew.org", "worldfloraonline.org", "powo.science.kew.org",
    "ipni.org", "tropicos.org", "efloras.org", "plantsoftheworldonline.org",
    # Government / institutional (broad patterns)
    ".gov", ".edu",
    ".ac.",  # academic ccTLD universities (.ac.ir/.ac.uk/.ac.jp/...), sibling of .edu
    "ema.europa.eu", "efsa.europa.eu", "fda.gov",
]

# Domains known to be low-quality / unreliable for medical claims --
# used to seed exclude_domains on the FIRST pass already.
KNOWN_LOW_QUALITY_DOMAINS = [
    "pinterest.com", "quora.com", "reddit.com", "answers.com",
    "healthline.com",  # decent for general audience but not primary source; excluded to force primary lit
    "webmd.com",        # same reasoning
    "wikihow.com",
]


def is_credible_url(url: str) -> bool:
    url = (url or "").lower()
    return any(pattern in url for pattern in CREDIBLE_DOMAIN_PATTERNS)


def is_credible_source(source: dict) -> bool:
    # Checks both the resolved URL and the title (Vertex sets grounding_chunk
    # web.title to the source's bare domain, e.g. "nih.gov") so a source still
    # counts as credible even if redirect resolution below fails.
    return is_credible_url(source.get("url", "")) or is_credible_url(source.get("domain_hint", ""))


# -----------------------------------------------------------------------------
# PROMPTS (hybrid Arabic/English, consistent with project convention)
# -----------------------------------------------------------------------------
def build_prompt(arabic_name, sci_name, disease_en, treatment_en, effect_en, strict=False):
    strict_clause = ""
    if strict:
        strict_clause = """
تنبيه: المحاولة الأولى فشلت في العثور على مصدر علمي موثوق. في هذه المحاولة،
ابحث حصرياً في المصادر التالية: الأبحاث المنشورة في PubMed أو NCBI، منظمة الصحة
العالمية (WHO)، المجلات العلمية المحكمة (Elsevier, Springer, Wiley, MDPI, Frontiers,
Nature)، أو المواقع الحكومية (.gov) والأكاديمية (.edu). تجاهل المواقع الصحية العامة
أو المدونات أو المنتديات تماماً.
"""

    return f"""أنت صيدلاني وباحث علمي متخصص في التحقق من صحة الادعاءات الطبية التقليدية
مقابل الأدلة العلمية الحديثة.

النبات: {arabic_name} ({sci_name})
الادعاء من كتاب تذكرة داود الأنطاكي:
- الحالة/المرض: {disease_en}
- طريقة العلاج: {treatment_en}
- الأثر المتوقع: {effect_en}
{strict_clause}
ابحث على الإنترنت عن أدلة علمية حديثة (أبحاث محكمة، قواعد بيانات طبية، منظمات صحية
رسمية) تؤيد أو تدحض فعالية هذا النبات لهذه الحالة تحديداً.

قواعد التقييم:
١. اعتمد فقط على مصادر أولية موثوقة: أبحاث محكمة، PubMed/NCBI، WHO، مواقع .gov أو .edu،
   مجلات علمية معروفة. لا تعتمد على مواقع صحية عامة أو مدونات أو منتديات.
٢. إذا لم تجد أي مصدر موثوق يتناول هذه الحالة تحديداً، صرّح بذلك بوضوح ولا تخترع دليلاً.
٣. اختلاف طريقة التحضير أو الجرعة عن الاستخدام الحديث لا يعني عدم الفعالية، طالما
   النبات نفسه مثبت الفعالية لهذه الحالة.
٤. مهم جداً: تحقق أن المصدر يتناول هذه الحالة/العلاج تحديداً، وليس فوائد عامة أخرى
   لنفس النبات لا علاقة لها بهذا الادعاء. إذا كان كل ما وجدته أبحاث عن النبات في
   استخدامات أخرى غير هذه الحالة، فهذا لا يُعتبر دليلاً مؤيداً أو مدحضاً، واذكر ذلك
   صراحة في التعليل واجعل الحكم "Insufficient Evidence" أو "Neutral" بحسب الحال.

Respond ONLY in this exact format with no extra text:
VERDICT: [Strongly Agree/Agree/Neutral/Disagree/Strongly Disagree/Insufficient Evidence]
CONFIDENCE: [0.0 to 1.0]
REASON: [three to five sentences in Arabic. State specifically what the source(s)
found regarding THIS EXACT condition/treatment (not just general uses of the
plant), then explain concretely why that finding agrees or disagrees with the
book's claim above, naming the source type/journal (e.g. PubMed meta-analysis,
WHO monograph). If the sources only cover the plant in general and not this
specific condition, say so explicitly instead of implying support.]
"""


# -----------------------------------------------------------------------------
# TRANSIENT-ERROR BACKOFF (new -- API-level retry, separate from the
# credibility-driven 1-retry-on-failure logic in factcheck_row below)
# -----------------------------------------------------------------------------
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def call_with_backoff(fn, *args, max_retries=5, base_delay=2.0, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except genai_errors.APIError as e:
            if e.code not in RETRYABLE_STATUS_CODES or attempt == max_retries:
                raise
        except Exception as e:
            msg = str(e).lower()
            is_retryable = any(
                kw in msg for kw in ("rate limit", "429", "503", "500", "504",
                                      "unavailable", "deadline", "timeout",
                                      "connection")
            )
            if not is_retryable or attempt == max_retries:
                raise
        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
        print(f"    [retry] transient error; backing off {delay:.1f}s "
              f"(attempt {attempt + 1}/{max_retries})")
        time.sleep(delay)


# -----------------------------------------------------------------------------
# SINGLE ROW FACT-CHECK (with grounding + credibility check + 1 retry)
# -----------------------------------------------------------------------------
def parse_response(text):
    verdict = re.search(r"VERDICT:\s*(.+)", text)
    confidence = re.search(r"CONFIDENCE:\s*([\d.]+)", text)
    reason = re.search(r"REASON:\s*(.+)", text, re.DOTALL)
    return {
        "verdict": verdict.group(1).strip() if verdict else "PARSE_ERROR",
        "confidence": float(confidence.group(1)) if confidence else 0.0,
        "reason": reason.group(1).strip() if reason else "",
    }


def resolve_grounding_url(uri: str, timeout: float = 10.0, retries: int = 2) -> str:
    # Vertex's grounding_chunk web.uri is an opaque Google redirect link
    # (vertexaisearch.cloud.google.com/grounding-api-redirect/...), never the
    # publisher's actual domain -- it has to be resolved to be checked against
    # CREDIBLE_DOMAIN_PATTERNS or to be a usable citation link for a human reviewer.
    # Google throttles this redirect endpoint when hit rapidly over a long run,
    # so failures are usually transient -- retry with a short backoff before
    # giving up, otherwise a real (often nih.gov/pubmed) source silently drops.
    for attempt in range(retries + 1):
        try:
            r = requests.head(uri, timeout=timeout, allow_redirects=True)
            if r.status_code < 400 and "vertexaisearch" not in r.url:
                return r.url
        except requests.RequestException:
            pass
        try:
            r = requests.get(uri, timeout=timeout, allow_redirects=True, stream=True)
            r.close()
            if r.status_code < 400 and "vertexaisearch" not in r.url:
                return r.url
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))
    return uri  # resolution failed after retries -- fall back to the raw redirect link


def extract_grounding_urls(response):
    sources = []
    try:
        chunks = response.candidates[0].grounding_metadata.grounding_chunks
        for c in chunks:
            if hasattr(c, "web") and c.web and c.web.uri:
                sources.append({
                    "url": resolve_grounding_url(c.web.uri),
                    "domain_hint": getattr(c.web, "title", "") or "",
                })
    except (AttributeError, IndexError, TypeError):
        pass
    return sources


# Google Search grounding is non-deterministic: the same query returns
# different sources each call, so a single pass has high variance and a row
# with real credible evidence can randomly surface none. We exploit that by
# re-rolling the SAME broad search up to MAX_BROAD_ATTEMPTS times; the first
# attempt that surfaces a credible source wins. Set to 1 to disable best-of-N.
MAX_BROAD_ATTEMPTS = 3


def _run_search(arabic_name, sci_name, disease_en, treatment_en, effect_en,
                 exclude_domains, strict):
    tool = types.Tool(google_search=types.GoogleSearch(exclude_domains=exclude_domains))
    config = types.GenerateContentConfig(tools=[tool])
    prompt = build_prompt(arabic_name, sci_name, disease_en, treatment_en, effect_en, strict=strict)
    resp = call_with_backoff(client.models.generate_content, model=MODEL, contents=prompt, config=config)
    # resp.text can come back None (e.g. recitation/safety filtering on grounded
    # content) even with finish_reason STOP -- treat that as a dead attempt.
    sources = extract_grounding_urls(resp) if resp.text is not None else []
    return resp, sources


def factcheck_row(arabic_name, sci_name, disease_en, treatment_en, effect_en,
                   exclude_domains=None):
    exclude_domains = list(exclude_domains or KNOWN_LOW_QUALITY_DOMAINS)
    all_sources_seen = []
    last_resp = None  # keep the most recent non-empty response to preserve its raw verdict

    # --- BROAD ATTEMPTS: re-roll the same wide search to beat grounding variance ---
    for attempt in range(1, MAX_BROAD_ATTEMPTS + 1):
        resp, sources = _run_search(arabic_name, sci_name, disease_en, treatment_en,
                                     effect_en, exclude_domains, strict=False)
        if resp.text is not None:
            last_resp = resp
        all_sources_seen.extend(s["url"] for s in sources)
        credible_sources = [s["url"] for s in sources if is_credible_source(s)]
        if resp.text is not None and credible_sources:
            parsed = parse_response(resp.text)
            parsed.update({
                "credible_sources": credible_sources,
                "all_sources": all_sources_seen,
                "credibility_check": f"Passed (broad attempt {attempt})",
                "retried": attempt > 1,
                "raw_model_verdict": parsed["verdict"],
                "raw_model_reason": parsed["reason"],
            })
            return parsed

    # --- STRICT RETRY: primary-source-biased prompt, but NO domain ban.
    # (The old retry excluded every domain pass 1 saw, which suppressed grounding
    # and returned zero sources -- worse recall, not better. We only tighten the
    # prompt, keeping the search wide.) ---
    resp, sources = _run_search(arabic_name, sci_name, disease_en, treatment_en,
                                 effect_en, exclude_domains, strict=True)
    if resp.text is not None:
        last_resp = resp
    all_sources_seen.extend(s["url"] for s in sources)
    credible_sources = [s["url"] for s in sources if is_credible_source(s)]
    if resp.text is not None and credible_sources:
        parsed = parse_response(resp.text)
        parsed.update({
            "credible_sources": credible_sources,
            "all_sources": all_sources_seen,
            "credibility_check": "Passed (strict retry)",
            "retried": True,
            "raw_model_verdict": parsed["verdict"],
            "raw_model_reason": parsed["reason"],
        })
        return parsed

    # --- Still nothing credible: force verdict, flag for review, but PRESERVE
    # what the model actually concluded (often a substantive Neutral/Agree with
    # reasoning) in raw_model_* so no judgement is silently discarded. ---
    raw = parse_response(last_resp.text) if last_resp is not None and last_resp.text else {"verdict": "", "reason": "", "confidence": 0.0}
    return {
        "verdict": "Insufficient Evidence",
        "confidence": 0.0,
        "reason": "لم يتم العثور على مصدر علمي موثوق بعد عدة محاولات بحث.",
        "credible_sources": [],
        "all_sources": all_sources_seen,
        "credibility_check": "Failed after retry",
        "retried": True,
        "raw_model_verdict": raw["verdict"],
        "raw_model_reason": raw["reason"],
    }


# -----------------------------------------------------------------------------
# SAMPLING: pick N random contiguous blocks (reproducible via fixed seed)
# -----------------------------------------------------------------------------
def pick_sample_blocks(n_rows, num_blocks, block_size, seed):
    rng = random.Random(seed)
    max_start = n_rows - block_size
    if max_start < 0:
        raise ValueError(f"Dataset has only {n_rows} rows, smaller than block_size={block_size}")

    blocks = []
    attempts = 0
    while len(blocks) < num_blocks:
        attempts += 1
        if attempts > 10000:
            raise RuntimeError("Could not place non-overlapping sample blocks; "
                                "reduce SAMPLE_NUM_BLOCKS or SAMPLE_BLOCK_SIZE")
        start = rng.randint(0, max_start)
        end = start + block_size - 1
        if any(not (end < s or start > e) for (s, e) in blocks):
            continue  # overlaps an existing block, try again
        blocks.append((start, end))

    blocks.sort()
    return blocks


# -----------------------------------------------------------------------------
# MAIN LOOP: resume-safe, saves after every row (project convention)
# -----------------------------------------------------------------------------
def main():
    if not os.path.exists(INPUT_FILE):
        sys.exit(f"Input file not found: {INPUT_FILE}\n"
                  f"Place disease_treatment_english_v1.csv in {DATA_DIR}/")
    if not os.path.exists(IDENTIFICATION_CSV):
        sys.exit(f"Input file not found: {IDENTIFICATION_CSV}\n"
                  f"Place plant_identification_v2.csv in {DATA_DIR}/")

    df = pd.read_csv(INPUT_FILE)            # ~7,362 rows: entry_id, arabic_name, disease_or_condition_en, ...
    ident = pd.read_csv(IDENTIFICATION_CSV) # for scientific_name, linked by entry_id

    sci_name_map = dict(zip(ident["entry_id"], ident.get("scientific_name", ident["entry_id"])))

    if SAMPLE_MODE:
        blocks = pick_sample_blocks(len(df), SAMPLE_NUM_BLOCKS, SAMPLE_BLOCK_SIZE, SAMPLE_SEED)
        print(f"SAMPLE_MODE enabled (seed={SAMPLE_SEED}): processing {len(blocks)} block(s) "
              f"of {SAMPLE_BLOCK_SIZE} rows out of {len(df)} total rows.")
        for s, e in blocks:
            print(f"  - rows {s}..{e} (entry_id {df.iloc[s]['entry_id']}..{df.iloc[e]['entry_id']})")
        sample_indices = []
        for s, e in blocks:
            sample_indices.extend(range(s, e + 1))
        df_to_process = df.iloc[sample_indices]
    else:
        df_to_process = df

    # Resume: load existing output if present
    if os.path.exists(OUTPUT_CSV):
        done_df = pd.read_csv(OUTPUT_CSV)
        done_ids = set(zip(done_df["entry_id"], done_df["disease_or_condition_en"]))
        results = done_df.to_dict("records")
    else:
        done_ids = set()
        results = []

    total = len(df_to_process)
    for n, (i, row) in enumerate(df_to_process.iterrows(), start=1):
        key = (row["entry_id"], row["disease_or_condition_en"])
        if key in done_ids:
            continue

        sci_name = sci_name_map.get(row["entry_id"], "")

        try:
            result = factcheck_row(
                arabic_name=row["arabic_name"],
                sci_name=sci_name,
                disease_en=row["disease_or_condition_en"],
                treatment_en=row["treatment_method_en"],
                effect_en=row["expected_effect_en"],
            )
        except Exception as e:
            result = {
                "verdict": "ERROR", "confidence": 0.0, "reason": str(e),
                "credible_sources": [], "all_sources": [],
                "credibility_check": "Error", "retried": False,
            }

        record = {
            "entry_id": row["entry_id"],
            "arabic_name": row["arabic_name"],
            "scientific_name": sci_name,
            "disease_or_condition_en": row["disease_or_condition_en"],
            "treatment_method_en": row["treatment_method_en"],
            "verdict": result["verdict"],
            "confidence": result["confidence"],
            "reason": result["reason"],
            "raw_model_verdict": result.get("raw_model_verdict", result["verdict"]),
            "raw_model_reason": result.get("raw_model_reason", result["reason"]),
            "credible_sources": " | ".join(result["credible_sources"]),
            "all_sources": " | ".join(result["all_sources"]),
            "credibility_check": result["credibility_check"],
            "retried": result["retried"],
            "needs_human_review": result["credibility_check"] == "Failed after retry",
        }
        results.append(record)

        # save after every single row (project convention -- no data loss on interruption)
        pd.DataFrame(results).to_csv(OUTPUT_CSV, index=False)
        with open(PROGRESS_FILE, "w") as f:
            f.write(f"{n}/{total} rows processed (SAMPLE_MODE={SAMPLE_MODE})\n")

        print(f"  [{n}/{total}] entry_id={row['entry_id']} -> {record['verdict']}"
              f"{' (retried)' if record['retried'] else ''}")

        time.sleep(0.3)  # light throttle, adjust if hitting rate limits

    print(f"Done. {len(results)} total rows in {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
