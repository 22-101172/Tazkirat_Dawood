"""
Stage 7 (alternative approach) -- Retrieve-then-Judge
Tadhkirat Dawood Al-Antaqi Project

Instead of Gemini + Google Search grounding (expensive, model-locked, gives
snippets), this:
  1. RETRIEVES peer-reviewed papers for each herb-disease claim from OpenAlex
     (free, official, no API key, no scraping, no account juggling), with real
     abstracts + citation counts + DOIs.
  2. JUDGES the claim by handing those abstracts to a cheap LLM (Gemini 3.0
     Flash / gemini-3-flash-preview). No web search in the LLM call -- the model
     only READS provided evidence, which is why the cheap model works here.

Benefits vs. grounding: retrieval is free (cost collapses), the corpus is
already peer-reviewed (credibility is inherent -- no URL resolution / allow-list
needed), and relevance is judged on real abstracts, not snippets.

Verdict schema is unchanged: Strongly Agree / Agree / Neutral / Disagree /
Strongly Disagree / Insufficient Evidence.

Auth: uses ADC (same as the grounding script). Run once if needed:
    gcloud auth application-default login
"""

import json
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
# PATHS (local, same data dir as the grounding script)
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

INPUT_FILE = os.path.join(DATA_DIR, "disease_treatment_english_v1.csv")
IDENTIFICATION_CSV = os.path.join(DATA_DIR, "plant_identification_v2.csv")
_TAG = os.environ.get("EXP_TAG", "")
_SUFFIX = ("_" + _TAG) if _TAG else ""
OUTPUT_CSV = os.path.join(DATA_DIR, f"factcheck_retrieve_judge_v1{_SUFFIX}.csv")
PROGRESS_FILE = os.path.join(DATA_DIR, f"factcheck_rj_progress_v1{_SUFFIX}.txt")
# Full per-row provenance trace (JSONL, one object per row, appended + flushed as
# each row finishes -> fail-safe: a crash never loses already-written rows).
# Captures every prompt, raw model response, the search query string, papers found
# (title/DOI/year/venue) and papers kept by the filter. Post-run analysis source.
TRACE_FILE = os.path.join(DATA_DIR, f"factcheck_trace_v1{_SUFFIX}.jsonl")

# -----------------------------------------------------------------------------
# SAMPLING (SAME seed/blocks as the grounding run -> identical 300 rows for a
# fair head-to-head comparison)
# -----------------------------------------------------------------------------
SAMPLE_MODE = True
SAMPLE_SEED = 42
SAMPLE_NUM_BLOCKS = 3
SAMPLE_BLOCK_SIZE = 100
# For fast method experiments: process every Nth row of the sample (spans all
# blocks/plants so it's representative). None = all 300. (env: EXP_EVERY)
EXPERIMENT_EVERY_NTH = int(os.environ.get("EXP_EVERY", "0")) or None

# --- Experiment toggles (A/B/C comparison; all off = current baseline) ---
# (env-controllable so variants run without editing the file)
USE_NUTRITIONAL_ENRICHMENT = os.environ.get("EXP_ENRICH") == "1"  # B: DB-sourced compounds in retrieval
USE_BROAD_CONDITION = os.environ.get("EXP_BROAD") == "1"          # C: broad category, not specific symptom
OUTPUT_TAG = os.environ.get("EXP_TAG", "")  # suffix for the output filename

# -----------------------------------------------------------------------------
# RETRIEVAL / JUDGE CONFIG
# -----------------------------------------------------------------------------
# Retrieval backend:
#   "europepmc" -- free, no key, very tolerant, biomedical + preprints (safe default)
#   "openalex"  -- free, no key, broadest coverage (429s an IP for hours if bursted)
#   "both"      -- query both and merge+dedupe (max recall; degrades gracefully if
#                  one source errors/rate-limits)
# Tested "both": OpenAlex bans this IP for ~24h after ~70 dual-source requests
# even with the polite pool + pacing, AND it added negligible recall (avg papers
# 5.0 -> 5.2). Europe PMC (= PubMed + preprints) already saturates recall for this
# biomedical task, so europepmc-only is the decision.
RETRIEVAL_SOURCE = "europepmc"

OPENALEX_BASE = "https://api.openalex.org/works"
OPENALEX_MAILTO = os.environ.get("CONTACT_EMAIL", "your-email@example.com")  # "polite pool" contact; set via env
EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Two-stage design (per Dr. Taher): retrieve a WIDE pool, let a cheap LLM filter
# it down to the papers actually relevant to this specific claim, then hand only
# those to the judging agent. Widening the pool catches on-topic papers that the
# database's keyword ranking buries below the top-10; filtering keeps the judge's
# input clean.
USE_RELEVANCE_FILTER = True
RETRIEVE_POOL = 25     # papers pulled from the DB before filtering
N_PAPERS = 10          # max papers (post-filter) handed to the judge
ABSTRACT_MAX_CHARS = 1200  # truncate each abstract to control token cost
MAX_BACKOFF = 60.0     # never sleep longer than this on a single retry

FILTER_MODEL = "gemini-3-flash-preview"  # cheap; the filter is a simple relevance task

# Stage 0: normalize the book's archaic/compound condition into modern, searchable
# terms before retrieval. Two failure modes this fixes: (1) COMPOUND conditions
# ("Chest diseases, cough, and expectoration of phlegm") whose ANDed words match
# nothing -- decomposed + OR'd they hit real studies; (2) pure HUMORAL concepts
# ("thick humors", "coldness of the stomach") that have NO modern equivalent and
# should be labelled as such, not lumped into "Insufficient Evidence".
USE_CONDITION_NORMALIZATION = True
NORMALIZE_MODEL = "gemini-3-flash-preview"
NO_MODERN_EQUIVALENT = "No Modern Equivalent"  # distinct label for untranslatable humoral claims

JUDGE_MODEL = "gemini-3-flash-preview"  # 3.0 Flash: fine for reading provided text (no grounding)

# -----------------------------------------------------------------------------
# AUTH & CLIENT
# -----------------------------------------------------------------------------
try:
    google_auth_default()
except DefaultCredentialsError:
    sys.exit(
        "No Application Default Credentials found.\n"
        "Run this once in your terminal, then re-run:\n\n"
        "    gcloud auth application-default login\n"
    )

client = genai.Client(
    vertexai=True,
    project=os.environ.get("VERTEX_PROJECT_ID", "your-gcp-project-id"),
    location="global",
    http_options=types.HttpOptions(api_version="v1"),
)

# -----------------------------------------------------------------------------
# BACKOFF (shared shape for both HTTP retrieval and the LLM call)
# -----------------------------------------------------------------------------
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RateLimitedError(Exception):
    """Backend is rate-limiting this IP beyond our backoff cap. Not a
    requests.RequestException on purpose, so the retry loop won't catch and
    re-retry it -- it aborts the call immediately (fast fail in 'both' mode)."""


def llm_with_backoff(fn, *args, max_retries=5, base_delay=2.0, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except genai_errors.APIError as e:
            if e.code not in RETRYABLE_STATUS_CODES or attempt == max_retries:
                raise
        except Exception as e:
            msg = str(e).lower()
            retryable = any(k in msg for k in ("rate limit", "429", "503", "500",
                                                "504", "unavailable", "deadline",
                                                "timeout", "connection"))
            if not retryable or attempt == max_retries:
                raise
        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
        print(f"    [llm retry] backing off {delay:.1f}s (attempt {attempt + 1})")
        time.sleep(delay)


# OpenAlex "polite pool" wants BOTH a mailto AND a descriptive User-Agent; without
# them bursts get 429'd fast (learned the hard way). We also pace requests to stay
# under the ~10 req/s ceiling and honor Retry-After on 429.
_OA_SESSION = requests.Session()
_OA_SESSION.headers.update({
    "User-Agent": f"TadhkiratDawoodFactCheck/1.0 (mailto:{OPENALEX_MAILTO})",
    "Accept": "application/json",
})
_OA_MIN_INTERVAL = 0.4   # seconds between OpenAlex calls (global pacing)
_oa_last_call = [0.0]


def http_get_with_backoff(url, params, timeout=25, max_retries=6, base_delay=2.0):
    for attempt in range(max_retries + 1):
        # global pacing so we never burst OpenAlex
        wait = _OA_MIN_INTERVAL - (time.monotonic() - _oa_last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = _OA_SESSION.get(url, params=params, timeout=timeout)
            _oa_last_call[0] = time.monotonic()
            if r.status_code < 400:
                return r
            if r.status_code == 429:
                # respect server's Retry-After, but CAP it -- a hostile server can
                # return a multi-hour value (OpenAlex returned 18054s = 5h after an
                # abusive burst); we never sleep more than MAX_BACKOFF, we give up
                # on the call instead and let the row fall through.
                ra = r.headers.get("Retry-After")
                server_delay = float(ra) if (ra and ra.isdigit()) else 0.0
                if server_delay > MAX_BACKOFF:
                    raise RateLimitedError(
                        f"429 with Retry-After={server_delay:.0f}s exceeds cap "
                        f"({MAX_BACKOFF}s) -- backend is rate-limiting this IP; aborting call.")
                delay = max(server_delay, base_delay * (2 ** attempt)) + random.uniform(0, 1)
                delay = min(delay, MAX_BACKOFF)
                if attempt == max_retries:
                    r.raise_for_status()
                print(f"    [429] backing off {delay:.1f}s (attempt {attempt + 1})")
                time.sleep(delay)
                continue
            if r.status_code not in RETRYABLE_STATUS_CODES or attempt == max_retries:
                r.raise_for_status()
        except requests.RequestException:
            _oa_last_call[0] = time.monotonic()
            if attempt == max_retries:
                raise
        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
        print(f"    [http retry] backing off {delay:.1f}s (attempt {attempt + 1})")
        time.sleep(delay)


# -----------------------------------------------------------------------------
# RETRIEVAL (OpenAlex)
# -----------------------------------------------------------------------------
def _abstract_from_inverted(inv):
    """OpenAlex returns abstracts as an inverted index {word: [positions]}."""
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    text = " ".join(w for _, w in positions)
    return text[:ABSTRACT_MAX_CHARS]


def _clean_condition(disease_en):
    # Drop parenthetical clarifications and punctuation so the condition doesn't
    # over-constrain an AND query (e.g. "Favus (scalp ulcers)" -> "Favus scalp ulcers").
    s = re.sub(r"\(.*?\)", " ", disease_en or "")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _retrieve_openalex(sci_name, common_name, disease_en, n):
    # OpenAlex 'search' is free-text, relevance-ranked -- concatenation works.
    query = " ".join(x for x in [sci_name, common_name, disease_en] if x).strip()
    params = {
        "search": query,
        "per-page": n,
        "mailto": OPENALEX_MAILTO,
        "select": "title,publication_year,cited_by_count,doi,abstract_inverted_index,primary_location",
    }
    data = http_get_with_backoff(OPENALEX_BASE, params).json()
    papers = []
    for w in data.get("results", []):
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {}).get("display_name", "") if loc else ""
        papers.append({
            "title": w.get("title") or "",
            "year": w.get("publication_year"),
            "cites": w.get("cited_by_count", 0),
            "doi": w.get("doi") or "",
            "venue": src,
            "abstract": _abstract_from_inverted(w.get("abstract_inverted_index")),
        })
    return papers, data.get("meta", {}).get("count", 0), query


def _condition_clause(disease_en, terms):
    # Prefer normalized modern terms OR'd together (recovers compound conditions);
    # fall back to the cleaned raw condition string.
    if terms:
        quoted = [f'"{t}"' if " " in t else t for t in terms]
        return "(" + " OR ".join(quoted) + ")"
    cond = _clean_condition(disease_en)
    return f"({cond})" if cond else ""


def _retrieve_europepmc(sci_name, common_name, disease_en, n, terms=None):
    # Europe PMC ANDs terms; quote the scientific name and AND the (OR'd) condition.
    clause = _condition_clause(disease_en, terms)
    if sci_name and clause:
        query = f'"{sci_name}" AND {clause}'
    elif sci_name:
        query = f'"{sci_name}"'
    else:
        query = clause
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",   # includes abstractText
        "pageSize": n,
        # NOTE: no 'sort' param -- Europe PMC returns an empty result if given an
        # invalid sort value, and its default ordering is already relevance.
    }
    data = http_get_with_backoff(EUROPEPMC_BASE, params).json()
    hitcount = data.get("hitCount") or 0
    papers = []
    for w in data.get("resultList", {}).get("result", []):
        abstract = (w.get("abstractText") or "")[:ABSTRACT_MAX_CHARS]
        papers.append({
            "title": w.get("title") or "",
            "year": w.get("pubYear"),
            "cites": w.get("citedByCount", 0),
            "doi": w.get("doi") or "",
            "venue": w.get("journalTitle") or w.get("source") or "",
            "abstract": abstract,
        })
    return papers, hitcount, query


def _norm_key(paper):
    doi = (paper.get("doi") or "").lower().replace("https://doi.org/", "").strip()
    if doi:
        return "doi:" + doi
    return "title:" + re.sub(r"[^\w]", "", (paper.get("title") or "").lower())[:60]


def _merge_dedupe(list_a, list_b, n):
    merged, seen = [], set()
    # interleave so both sources are represented in the top-N
    for pair in zip(list_a, list_b):
        for p in pair:
            k = _norm_key(p)
            if k and k not in seen and p.get("title"):
                seen.add(k)
                merged.append(p)
    for rest in (list_a[len(list_b):], list_b[len(list_a):]):
        for p in rest:
            k = _norm_key(p)
            if k and k not in seen and p.get("title"):
                seen.add(k)
                merged.append(p)
    return merged[:n]


def retrieve_papers(sci_name, disease_en, common_name="", n=N_PAPERS, terms=None):
    # Returns (papers, total_hits, query_string). query_string is recorded in the
    # trace as the "strings that matched" the retrieved papers.
    if RETRIEVAL_SOURCE == "openalex":
        return _retrieve_openalex(sci_name, common_name, disease_en, n)
    if RETRIEVAL_SOURCE == "europepmc":
        return _retrieve_europepmc(sci_name, common_name, disease_en, n, terms=terms)

    # "both": query each source independently; a failure in one (e.g. OpenAlex
    # rate-limiting) must not kill the row -- fall back to whatever succeeded.
    epmc, epmc_total, oa, oa_total = [], 0, [], 0
    qparts = []
    try:
        epmc, epmc_total, q1 = _retrieve_europepmc(sci_name, common_name, disease_en, n, terms=terms)
        qparts.append("EuropePMC: " + q1)
    except Exception as e:
        print(f"    [europepmc failed] {str(e)[:80]}")
    try:
        oa, oa_total, q2 = _retrieve_openalex(sci_name, common_name, disease_en, n)
        qparts.append("OpenAlex: " + q2)
    except Exception as e:
        print(f"    [openalex failed] {str(e)[:80]}")
    return _merge_dedupe(epmc, oa, n), max(epmc_total, oa_total), " || ".join(qparts)


# -----------------------------------------------------------------------------
# EXPERIMENT B: nutritional/phytochemical enrichment. Compounds are pulled from
# Wikidata's curated "natural product found in taxon" data -- SOURCED, not
# LLM-generated, so no hallucination (addresses Dr. Taher's concern). Used only
# to WIDEN retrieval; the strict judge is unchanged.
# -----------------------------------------------------------------------------
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_compound_cache = {}

# Which compound set drives enrichment (env EXP_COMPOUND_SET):
#   "raw"   -- top-6 straight from Wikidata (original B; includes generic compounds)
#   "llm"   -- LLM-picked distinctive markers (from build_distinctive_compounds.py)
#   "quant" -- rarest-by-species-count markers (benchmark)
COMPOUND_SET = os.environ.get("EXP_COMPOUND_SET", "raw")
_DISTINCTIVE_FILE = os.path.join(DATA_DIR, "distinctive_compounds.json")
_DISTINCTIVE = {}
if COMPOUND_SET in ("llm", "quant") and os.path.exists(_DISTINCTIVE_FILE):
    with open(_DISTINCTIVE_FILE, encoding="utf-8") as _f:
        _DISTINCTIVE = json.load(_f)


def _clean_compound(name):
    # keep only clean common names -- drop long IUPAC / bracketed strings
    first = name.split()[0] if name.split() else ""
    return len(name) <= 24 and "[" not in name and "(" not in name and not any(ch.isdigit() for ch in first)


def fetch_plant_compounds(sci_name, top=6):
    if not sci_name:
        return []
    if sci_name in _compound_cache:  # only successful lookups are cached
        return _compound_cache[sci_name]
    query = ('SELECT ?cL WHERE { ?t wdt:P225 "%s". ?c wdt:P703 ?t. '
             '?c rdfs:label ?cL. FILTER(LANG(?cL)="en") } LIMIT 40' % sci_name)
    for attempt in range(3):
        try:
            r = requests.get(WIKIDATA_SPARQL, params={"query": query, "format": "json"},
                             headers={"User-Agent": "TadhkiratDawoodFactCheck/1.0 (research)"}, timeout=30)
            if r.status_code == 200:
                names = [b["cL"]["value"] for b in r.json()["results"]["bindings"]]
                compounds = [n for n in names if _clean_compound(n)][:top]
                _compound_cache[sci_name] = compounds  # cache only on a real success
                return compounds
        except (requests.RequestException, KeyError, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    return []  # transient failure -- do NOT cache, so a later row can retry


# -----------------------------------------------------------------------------
# EXPERIMENT C: broad-condition mapping. Instead of judging each hyper-specific
# symptom, map it to a broad clinical category and evaluate at that level.
# -----------------------------------------------------------------------------
_BROAD_CONFIG = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))
BROAD_CATEGORIES = ["Respiratory", "Digestive/Gastrointestinal", "Skin/Dermatological",
                    "Urinary/Renal", "Cardiovascular", "Musculoskeletal/Joint",
                    "Neurological", "Reproductive", "Metabolic/Endocrine",
                    "Infectious/Antimicrobial", "Eye", "Ear/Nose/Throat", "Pain/Inflammation",
                    "Liver/Hepatic", "Other"]


def map_broad_category(disease_en):
    prompt = (f'Map this historical medical condition to ONE broad clinical category.\n'
              f'Condition: "{disease_en}"\n'
              f'Categories: {", ".join(BROAD_CATEGORIES)}\n'
              f'Respond with ONLY the single best category name from the list.')
    resp = llm_with_backoff(client.models.generate_content, model=NORMALIZE_MODEL,
                            contents=prompt, config=_BROAD_CONFIG)
    text = (resp.text or "").strip()
    for cat in BROAD_CATEGORIES:
        if cat.lower() in text.lower():
            return cat
    return "Other"


# -----------------------------------------------------------------------------
# STAGE 0: condition normalization -- archaic/compound condition -> modern search
# terms, and detection of pure-humoral concepts with no modern equivalent.
# -----------------------------------------------------------------------------
_NORMALIZE_CONFIG = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))


def normalize_condition(disease_en):
    prompt = f"""You convert a historical medical condition (from a 17th-century Arabic
materia medica) into modern search terms for a scientific literature search.

Condition: "{disease_en}"

1. MODERN_EQUIVALENT: does this have ANY recognizable modern medical counterpart or
symptom that could appear in modern scientific literature? Answer "no" ONLY for
purely humoral/archaic concepts with no modern counterpart (e.g. "thick humors",
"coldness of the stomach", "vitiated humors", "bilious acrimony"). Answer "yes" for
anything with a real symptom/disease, including compound lists (split them).
2. TERMS: if yes, give 2-6 concise modern medical search terms or synonyms (single
words or short phrases), separated by semicolons. If a compound condition, list each
distinct symptom. If no, leave blank.

Respond in EXACTLY this format:
MODERN_EQUIVALENT: yes/no
TERMS: term1; term2; term3"""
    resp = llm_with_backoff(client.models.generate_content, model=NORMALIZE_MODEL,
                            contents=prompt, config=_NORMALIZE_CONFIG)
    text = resp.text or ""
    m = re.search(r"MODERN_EQUIVALENT:\s*(\w+)", text, re.I)
    has_equiv = bool(m) and m.group(1).lower().startswith("y")
    tmatch = re.search(r"TERMS:\s*(.+)", text, re.I | re.S)
    terms = []
    if tmatch:
        terms = [t.strip() for t in re.split(r"[;\n]", tmatch.group(1)) if t.strip()]
    return has_equiv, terms, {"prompt": prompt, "response": text}


# -----------------------------------------------------------------------------
# RELEVANCE FILTER (stage 1 of 2): a cheap LLM keeps only the papers that could
# actually inform a judgment on THIS specific claim, before the judge sees them.
# -----------------------------------------------------------------------------
def build_filter_prompt(sci_name, disease_en, papers):
    blocks = []
    for i, p in enumerate(papers, 1):
        snippet = (p["abstract"] or p["title"] or "")[:600]
        blocks.append(f"[{i}] {p['title']}\n    {snippet}")
    listing = "\n\n".join(blocks)
    return f"""You are screening scientific papers for relevance before a fact-check.

CLAIM TO EVALUATE:
- Plant: {sci_name}
- Medical condition / use: {disease_en}

Below is a list of papers returned by a database search. Select ONLY the papers
that could genuinely inform whether this plant treats/affects THIS specific
condition. A paper is RELEVANT if it does any of:
  - studies this plant (or a closely related species of the same genus) in
    relation to this condition or a clear synonym of it, OR
  - documents/records this plant being used for this condition (including
    ethnobotanical or traditional-medicine reports), OR
  - reports a pharmacological property of this plant that is directly mechanistic
    to this condition.
A paper is NOT relevant if the plant or the condition only appears incidentally
or in an unrelated context (e.g. the plant used as a nanoparticle substrate, or
a survey that lists the condition for other plants).

PAPERS:
{listing}

Respond with ONLY the numbers of the relevant papers, comma-separated (e.g.
"1, 4, 7"). If none are relevant, respond with exactly "NONE"."""


# Relevance screening is a simple task -- disable the model's "thinking" for it
# (cuts the filter call from ~43s to ~2.5s with no quality loss). The judge keeps
# thinking enabled, where the extra reasoning is worth it.
_FILTER_CONFIG = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))


def filter_relevant_papers(sci_name, disease_en, papers):
    if not papers:
        return [], {"prompt": "", "response": "", "kept_indices": []}
    prompt = build_filter_prompt(sci_name, disease_en, papers)
    resp = llm_with_backoff(client.models.generate_content, model=FILTER_MODEL,
                            contents=prompt, config=_FILTER_CONFIG)
    text = (resp.text or "").strip()
    if "none" in text.lower() and not re.search(r"\d", text):
        return [], {"prompt": prompt, "response": text, "kept_indices": []}
    idxs = [int(x) for x in re.findall(r"\d+", text)]
    keep = [papers[i - 1] for i in idxs if 1 <= i <= len(papers)]
    # de-dup while preserving order
    seen, out = set(), []
    for p in keep:
        k = _norm_key(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out, {"prompt": prompt, "response": text, "kept_indices": idxs}


# -----------------------------------------------------------------------------
# JUDGE PROMPT (reads provided abstracts; does NOT search. Verdict schema
# preserved; REASON in Arabic per project convention.)
# -----------------------------------------------------------------------------
def build_judge_prompt(arabic_name, sci_name, disease_en, treatment_en, effect_en, papers):
    blocks = []
    for i, p in enumerate(papers, 1):
        abstract = p["abstract"] or "(no abstract available)"
        blocks.append(
            f"[{i}] {p['title']} ({p['year']}, {p['venue']}, citations={p['cites']})\n"
            f"    Abstract: {abstract}"
        )
    evidence = "\n\n".join(blocks) if blocks else "(no papers were found in the scientific database)"

    return f"""أنت صيدلاني وباحث علمي متخصص في التحقق من صحة الادعاءات الطبية التقليدية
مقابل الأدلة العلمية الحديثة.

النبات: {arabic_name} ({sci_name})
الادعاء من كتاب تذكرة داود الأنطاكي:
- الحالة/المرض: {disease_en}
- طريقة العلاج: {treatment_en}
- الأثر المتوقع: {effect_en}

فيما يلي أبحاث علمية محكمة استُرجعت من قواعد بيانات علمية موثوقة (PubMed/Europe PMC،
جميعها مصادر أولية منشورة ومحكّمة). اعتمد حصرياً على هذه الأبحاث المعطاة أدناه ولا
تخترع أو تفترض أي دليل غير موجود فيها:

{evidence}

قواعد التقييم:
١. احكم فقط بناءً على الأبحاث المعطاة أعلاه.
٢. مهم جداً: تحقق أن البحث يتناول هذه الحالة/المرض تحديداً، وليس فوائد عامة أخرى لنفس
   النبات لا علاقة لها بهذا الادعاء. البحث عن النبات في استخدام مختلف لا يُعتبر دليلاً
   مؤيداً أو مدحضاً لهذا الادعاء تحديداً.
٣. اختلاف طريقة التحضير أو الجرعة عن الاستخدام الحديث لا يعني عدم الفعالية، طالما
   النبات نفسه مثبت الفعالية لهذه الحالة في الأبحاث المعطاة.

التمييز المهم بين الأحكام (اتبعه بدقة):
٤. "Agree" أو "Strongly Agree": فقط عندما توجد دراسة تجريبية أو سريرية أو تحليلية حديثة
   اختبرت فعلاً فعالية النبات على هذه الحالة تحديداً وأيّدتها.
٥. "Disagree" أو "Strongly Disagree": عندما تُظهر تلك الدراسات أن النبات غير فعّال أو أن
   له أثراً معاكساً لهذا الادعاء.
٦. "Neutral": عندما يوجد دليل *غير مباشر أو أولي* يجعل الادعاء معقولاً لكنه غير مثبت
   بتجربة حديثة مباشرة — مثل: أبحاث إثنوبوتانية أو مراجعات طب تقليدي تذكر هذا الاستخدام،
   أو خاصية عامة ذات صلة للنبات (كمضاد للالتهاب/الأكسدة) دون اختبار مباشر على هذه الحالة،
   أو دليل على نوع قريب من نفس الجنس. هذه الحالة "معقولة لكن غير مثبتة حديثاً".
٧. "Insufficient Evidence": فقط عندما لا تتضمن الأبحاث المعطاة أي مادة ذات صلة بالنبات
   وهذه الحالة إطلاقاً (لا دليل مباشر ولا غير مباشر). لا تستخدم هذا الحكم إذا وُجد دليل
   تقليدي أو غير مباشر — استخدم "Neutral" في تلك الحالة.

Respond ONLY in this exact format with no extra text:
VERDICT: [Strongly Agree/Agree/Neutral/Disagree/Strongly Disagree/Insufficient Evidence]
CONFIDENCE: [0.0 to 1.0]
REASON: [three to five sentences in Arabic. State specifically what the given
paper(s) found regarding THIS EXACT condition/treatment, cite them by number
(e.g. [1], [3]), and explain why that agrees or disagrees with the book's claim.
If none of the given papers address this specific condition, say so explicitly.]
"""


def parse_response(text):
    verdict = re.search(r"VERDICT:\s*(.+)", text)
    confidence = re.search(r"CONFIDENCE:\s*([\d.]+)", text)
    reason = re.search(r"REASON:\s*(.+)", text, re.DOTALL)
    return {
        "verdict": verdict.group(1).strip() if verdict else "PARSE_ERROR",
        "confidence": float(confidence.group(1)) if confidence else 0.0,
        "reason": reason.group(1).strip() if reason else "",
    }


# -----------------------------------------------------------------------------
# JUDGE ONE ROW
# -----------------------------------------------------------------------------
def _paper_meta(papers):
    # compact per-paper provenance for the trace (no abstract text to keep it small)
    return [{"title": p.get("title", ""), "doi": p.get("doi", ""), "year": p.get("year"),
             "venue": p.get("venue", ""), "cites": p.get("cites", 0),
             "has_abstract": bool(p.get("abstract"))} for p in papers]


def _result(verdict, confidence, reason, n_papers, n_retrieved, total_hits, evidence, judged):
    return {"verdict": verdict, "confidence": confidence, "reason": reason,
            "n_papers": n_papers, "n_retrieved": n_retrieved, "total_hits": total_hits,
            "evidence": evidence, "judged": judged}


def judge_row(arabic_name, sci_name, disease_en, treatment_en, effect_en, common_name=""):
    # Full provenance trace for post-run analysis (Dr. Taher). Every stage records
    # its prompt, raw response, and paper-level detail. Returned alongside result.
    trace = {
        "scientific_name": sci_name, "common_name": common_name,
        "condition_original": disease_en, "condition_used": disease_en,
        "broad_condition": None,
        "config": {"enrichment": USE_NUTRITIONAL_ENRICHMENT, "broad_condition": USE_BROAD_CONDITION,
                   "filter": USE_RELEVANCE_FILTER, "normalization": USE_CONDITION_NORMALIZATION,
                   "retrieval_source": RETRIEVAL_SOURCE, "retrieve_pool": RETRIEVE_POOL},
        "stages": {},
    }

    # EXPERIMENT C -- collapse the hyper-specific symptom into a broad clinical category.
    if USE_BROAD_CONDITION:
        disease_en = map_broad_category(disease_en)
        trace["broad_condition"] = disease_en
        trace["condition_used"] = disease_en

    # STAGE 0 -- normalize archaic/compound condition into modern search terms.
    terms = None
    if USE_CONDITION_NORMALIZATION:
        has_equiv, terms, norm_meta = normalize_condition(disease_en)
        trace["stages"]["normalization"] = {**norm_meta, "has_modern_equivalent": has_equiv,
                                            "search_terms": terms}
        if not has_equiv:
            result = _result(NO_MODERN_EQUIVALENT, 0.0,
                             "هذه الحالة مفهوم طبي تراثي (خلطي) لا يوجد له مقابل في الطب الحديث، "
                             "فلا يمكن التحقق منه مقابل الأدلة العلمية الحديثة.",
                             0, 0, 0, [], True)
            trace["outcome"] = "no_modern_equivalent"
            return result, trace

    # EXPERIMENT B -- widen the retrieval query with DB-sourced plant compounds.
    if USE_NUTRITIONAL_ENRICHMENT:
        if COMPOUND_SET in ("llm", "quant"):
            compounds = (_DISTINCTIVE.get(sci_name, {}) or {}).get(COMPOUND_SET, [])
        else:
            compounds = fetch_plant_compounds(sci_name)
        trace["enrichment_compounds"] = compounds
        trace["compound_set"] = COMPOUND_SET
        if compounds:
            terms = (terms or []) + compounds

    pool = RETRIEVE_POOL if USE_RELEVANCE_FILTER else N_PAPERS
    papers, total_hits, query = retrieve_papers(sci_name, disease_en, common_name, n=pool, terms=terms)
    n_retrieved = len(papers)
    trace["stages"]["retrieval"] = {"query": query, "search_terms": terms, "total_hits": total_hits,
                                    "n_found": n_retrieved, "papers": _paper_meta(papers)}

    if not papers:
        result = _result("Insufficient Evidence", 0.0,
                         "لم تُرجِع قاعدة البيانات العلمية أي أبحاث لهذا النبات وهذه الحالة.",
                         0, n_retrieved, total_hits, [], False)
        trace["outcome"] = "no_papers_retrieved"
        return result, trace

    # STAGE 1 -- relevance filter (Dr. Taher's two-stage design).
    if USE_RELEVANCE_FILTER:
        relevant, filt_meta = filter_relevant_papers(sci_name, disease_en, papers)
        trace["stages"]["filter"] = {**filt_meta, "n_kept": len(relevant),
                                     "kept_papers": _paper_meta(relevant)}
        if not relevant:
            result = _result("Insufficient Evidence", 0.0,
                             "بعد فرز نتائج البحث، لم يتبقَّ أي بحث ذي صلة مباشرة أو غير مباشرة بهذا النبات وهذه الحالة.",
                             0, n_retrieved, total_hits, [], True)
            trace["outcome"] = "filtered_to_zero"
            return result, trace
        papers = relevant[:N_PAPERS]

    # STAGE 2 -- judge on the filtered set.
    prompt = build_judge_prompt(arabic_name, sci_name, disease_en, treatment_en, effect_en, papers)
    resp = llm_with_backoff(client.models.generate_content, model=JUDGE_MODEL, contents=prompt)
    parsed = parse_response(resp.text or "")
    trace["stages"]["judge"] = {"prompt": prompt, "response": resp.text or "",
                                "papers_judged": _paper_meta(papers)}
    result = _result(parsed["verdict"], parsed["confidence"], parsed["reason"],
                     len(papers), n_retrieved, total_hits,
                     [f"{p['title']} ({p['year']}) {p['doi']}".strip() for p in papers], True)
    trace["outcome"] = "judged"
    return result, trace


# -----------------------------------------------------------------------------
# SAMPLING (identical logic/seed to the grounding script)
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
            raise RuntimeError("Could not place non-overlapping sample blocks")
        start = rng.randint(0, max_start)
        end = start + block_size - 1
        if any(not (end < s or start > e) for (s, e) in blocks):
            continue
        blocks.append((start, end))
    blocks.sort()
    return blocks


# -----------------------------------------------------------------------------
# MAIN LOOP: resume-safe, saves after every row
# -----------------------------------------------------------------------------
def main():
    if not os.path.exists(INPUT_FILE):
        sys.exit(f"Input file not found: {INPUT_FILE}")
    if not os.path.exists(IDENTIFICATION_CSV):
        sys.exit(f"Input file not found: {IDENTIFICATION_CSV}")

    df = pd.read_csv(INPUT_FILE)
    ident = pd.read_csv(IDENTIFICATION_CSV)
    sci_name_map = dict(zip(ident["entry_id"], ident.get("scientific_name", ident["entry_id"])))
    common_map = dict(zip(ident["entry_id"], ident.get("common_english_name", pd.Series(dtype=str))))

    if SAMPLE_MODE:
        blocks = pick_sample_blocks(len(df), SAMPLE_NUM_BLOCKS, SAMPLE_BLOCK_SIZE, SAMPLE_SEED)
        print(f"SAMPLE_MODE (seed={SAMPLE_SEED}): {len(blocks)} block(s) of {SAMPLE_BLOCK_SIZE} rows "
              f"out of {len(df)} total.")
        for s, e in blocks:
            print(f"  - rows {s}..{e} (entry_id {df.iloc[s]['entry_id']}..{df.iloc[e]['entry_id']})")
        idxs = []
        for s, e in blocks:
            idxs.extend(range(s, e + 1))
        df_to_process = df.iloc[idxs]
        if EXPERIMENT_EVERY_NTH:
            # representative fast subset spanning all blocks/plants
            df_to_process = df_to_process.iloc[::EXPERIMENT_EVERY_NTH]
            print(f"  EXPERIMENT subset: every {EXPERIMENT_EVERY_NTH}th row -> {len(df_to_process)} rows")
    else:
        df_to_process = df

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
        common = common_map.get(row["entry_id"], "")
        common = "" if pd.isna(common) else str(common)

        try:
            result, trace = judge_row(
                arabic_name=row["arabic_name"],
                sci_name=sci_name,
                disease_en=row["disease_or_condition_en"],
                treatment_en=row["treatment_method_en"],
                effect_en=row["expected_effect_en"],
                common_name=common,
            )
        except Exception as e:
            # Fail-safe: one row's failure never aborts the run; the error is
            # recorded in both the CSV and the trace so it is auditable.
            import traceback as _tb
            result = {
                "verdict": "ERROR", "confidence": 0.0, "reason": str(e),
                "n_papers": 0, "n_retrieved": 0, "total_hits": 0, "evidence": [], "judged": False,
            }
            trace = {"scientific_name": sci_name, "condition_original": row["disease_or_condition_en"],
                     "outcome": "error", "error": str(e), "traceback": _tb.format_exc()}

        record = {
            "entry_id": row["entry_id"],
            "arabic_name": row["arabic_name"],
            "scientific_name": sci_name,
            "disease_or_condition_en": row["disease_or_condition_en"],
            "treatment_method_en": row["treatment_method_en"],
            "verdict": result["verdict"],
            "confidence": result["confidence"],
            "reason": result["reason"],
            "n_papers_retrieved": result.get("n_retrieved", result["n_papers"]),
            "n_papers_after_filter": result["n_papers"],
            "db_total_hits": result["total_hits"],
            "evidence_papers": " | ".join(result["evidence"]),
            "judged_by_llm": result["judged"],
            "needs_human_review": result["verdict"] in ("Insufficient Evidence", "PARSE_ERROR", "ERROR"),
        }
        results.append(record)

        # summary CSV (rewritten each row) + fail-safe append-only JSONL trace
        pd.DataFrame(results).to_csv(OUTPUT_CSV, index=False)
        trace_row = {"entry_id": int(row["entry_id"]), "arabic_name": row["arabic_name"],
                     "verdict": result["verdict"], "confidence": result["confidence"],
                     "reason": result["reason"], **trace}
        with open(TRACE_FILE, "a", encoding="utf-8") as tf:
            tf.write(json.dumps(trace_row, ensure_ascii=False) + "\n")
            tf.flush()
            os.fsync(tf.fileno())
        with open(PROGRESS_FILE, "w") as f:
            f.write(f"{n}/{total} rows processed (SAMPLE_MODE={SAMPLE_MODE})\n")

        print(f"  [{n}/{total}] entry_id={row['entry_id']} papers={result['n_papers']} -> {record['verdict']}")

        time.sleep(0.2)  # politeness throttle

    print(f"Done. {len(results)} total rows in {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
