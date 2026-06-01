# Validation Pipeline Documentation
### Tadhkirat Uli al-Albab — Herbal Medicine Claim Validation
**Status:** Approved by Doctor Taher  
**Version:** 2.0  

---

## Overview

This document is the reference for the validation layer of the Tadhkirat Uli al-Albab project. The goal of this layer is to take structured claims extracted from a 16th-century Arabic medical manuscript and validate each one against modern academic and peer-reviewed literature.

The pipeline receives its input from the preprocessing layer and produces a fully scored, citation-backed Excel output — one row per original claim.

---

## The Core Problem This Pipeline Solves

With 10,948 claims, a naive approach would call an LLM once per claim — producing ~11,000 costly LLM API calls — and query academic databases once per claim — producing redundant, weak searches with overlapping results.

This pipeline solves both, but with different priorities:

**Primary goal — Minimize LLM calls (the expensive part)**  
By grouping claims into search units (`herb + disease cluster`), multiple claims that share the same herb and disease reuse the same retrieved evidence and the same LLM scoring. The LLM is called once per search unit (~1,000–3,000 calls), not once per claim (10,948 calls).

**Secondary goal — Build richer, more comprehensive search queries**  
Academic APIs (PubMed, Europe PMC, Semantic Scholar) are free, but searching once per claim still causes problems: narrow queries miss relevant papers, and redundant searches waste rate-limited API capacity. By searching once per search unit with a rich query (scientific name + all disease synonyms + mechanism terms), we retrieve more relevant papers in a single well-constructed call.

**The key insight:**  
> Search once per *herb + disease group* with rich vocabulary. Score claims individually against cached evidence.

---

## Dataset (From last semester's Preprocessing Output)

| Metric | Value |
|---|---|
| Total claims (rows) | 10,948 |
| Unique herbs | 2,082 |
| Unique disease expressions (before clustering) | 3,204 |
| Average claims per herb | ~5.3 |

The 3,204 unique disease expressions contain many variations of the same condition. Clustering them is what makes the search count realistic.

Note: This was last semester's output, we dont know if there will be changes in this semester's preprocessing output

---

## Pipeline at a Glance

```
Preprocessing Output (Excel File 1 + File 2)
        │
        ▼
  Stage 0 — Herb Linking
        │   Merge Arabic synonyms → unique herb_id per plant
        │
        ▼
  Stage 1 — Disease Normalization & Clustering
        │   Translate historical terms → modern biomedical vocabulary
        │   Group similar diseases into clusters
        │
        ▼
  Stage 2 — Search Unit Creation
        │   Combine herb_id + disease_cluster → unique search units
        │   (10,948 claims collapse into far fewer units)
        │
        ▼
  Stage 3 — Academic Search
        │   Query PubMed, Europe PMC, Semantic Scholar per search unit
        │   Retrieve papers with full metadata including journal/venue
        │   No result → document as "No Evidence Found"
        │
        ▼
  Stage 4 — LLM Scoring
        │   Send claim + top 1–3 abstracts to LLM
        │   Score: Source Reliability + Disease/Effect/Treatment support
        │   Claims sharing a search unit reuse the same scoring
        │
        ▼
  Stage 5 — Excel Output
        │   One row per original claim, all scores + citations appended
        │   Supporting sheets: herb table, clusters, search log
```

---

## Stage 0 — Herb Linking

**Purpose:** Ensure the same herb is never searched more than once.

**The problem it solves:**  
The preprocessing layer may produce multiple Arabic names pointing to the same plant. For example, *الينسون* and *اطريول* both refer to *Ammi majus*. Without linking, these would be treated as separate herbs and searched separately.

**What this stage does:**
1. Load both preprocessing Excel files
2. Group rows by shared scientific name
3. Assign a stable `herb_id` to each unique plant
4. Merge all Arabic name variants under that `herb_id`

**Output — Herb Authority Table:**

| Column | Description |
|---|---|
| `herb_id` | Stable unique identifier (e.g. HERB_001) |
| `arabic_names_all` | All Arabic names/synonyms from the book |
| `english_name` | Common English name |
| `scientific_name` | Latin/scientific name |
| `identity_confidence` | Verified / Likely / Uncertain |

> **Note:** The preprocessing team has already excluded non-plant substances (minerals, animal products, mixtures). No additional flagging is needed here.

**Implementation expectations:**
- Load both preprocessing Excel files, group by scientific name, assign herb_id
- Validate: every herb in File 2 must resolve to a herb_id — any orphan is an error to fix before moving on
- Expected output size: ~2,082 rows
- Expected time: under 5 minutes (simple Pandas grouping, no API calls)

---

## Stage 1 — Disease Normalization & Clustering

**Purpose:** Ensure that two claims describing the same condition in different words are not searched separately.

**The problem it solves:**  
The book uses 16th-century Arabic medical terminology. PubMed does not. Terms like "old wound mark", "scars", and "cicatrix" all describe the same concept but will return different (or no) results if searched literally. Additionally, 3,204 unique disease expressions contain many surface-level duplicates and historical terms that need translation into modern biomedical vocabulary.

**This stage works on the unique disease list only** (~300–1,000 expressions after initial cleaning), not on all 10,948 rows.

### Three Passes:

**Pass 1 — Automatic text cleaning** *(no model needed)*  
Merge obvious surface duplicates using simple rules:
```
scar / scars / scarring       → same entry
headache / headaches           → same entry
stomach pain / pain in stomach → same entry
```

**Pass 2 — Medical synonym mapping** *(semi-automatic)*  
Translate historical and informal disease terms into modern biomedical vocabulary that academic databases actually use:

| Book term | Normalized term |
|---|---|
| Old wound mark | wound healing / cicatrix |
| Kidney stones | nephrolithiasis / urolithiasis |
| Shortness of breath | dyspnea |
| Skin whitening disorder | vitiligo / hypopigmentation |
| Phlegm of the trachea | respiratory mucus / expectoration |

Built using a manually curated table, MeSH terms, and LLM assistance for ambiguous cases.

**Pass 3 — LLM cluster grouping** *(LLM on unique list only)*  
Ask the LLM: *"Group these disease terms if they are medically similar enough to use the same literature search query."*

Example output:
```
Cluster: wound healing
  → scar, cicatrix, ulcer, tissue repair, wound, old wound mark

Cluster: skin pigmentation disorders  
  → vitiligo, leukoderma, skin discoloration, leukoma

Cluster: urinary tract conditions
  → kidney stones, bladder stones, urolithiasis, dysuria, ascites
```

The team does a **quick manual review** of all clusters before they are used downstream. You are reviewing hundreds of clusters — not 10,948 rows.

**Output per disease expression:**

| Column | Description |
|---|---|
| `raw_disease` | Original text from the book |
| `normalized_disease` | Cleaned modern equivalent |
| `synonyms` | All related terms |
| `broader_category` | e.g. skin/wound, respiratory, digestive |
| `mechanism_terms` | e.g. anti-inflammatory, antimicrobial, collagen |
| `cluster_id` | Assigned cluster |

**Implementation expectations:**
- Pass 1 is fully automated with a short Python script — no API calls
- Pass 2 requires the team to build a manual mapping table for at least the most common 100–200 disease terms before running; LLM fills gaps for the rest
- Pass 3 sends only the unique disease list to the LLM (not 10,948 rows), then the team reviews the cluster output manually
- Validate: every disease in File 2 must map to a cluster_id — any unmapped term goes back to Pass 2
- Expected output size: 300–600 clusters (after 3,204 expressions are deduplicated and grouped)
- Expected time: 3–5 hours including manual review of clusters

---

## Stage 2 — Search Unit Creation

**Purpose:** Define the actual unit we will search and score.

**What this stage does:**  
Combine `herb_id` + `disease_cluster` into unique search units. Every claim that shares the same herb and disease cluster maps to the same search unit.

**Example:**

| Search Unit | Herb | Disease Cluster | Claims it covers |
|---|---|---|---|
| SU_001 | Ammi majus | wound healing | 4 claims |
| SU_002 | Ammi majus | skin pigmentation | 2 claims |
| SU_003 | Nigella sativa | diabetes | 7 claims |

**The collapse:**
```
10,948 original claims
        ↓
  unique herb + disease cluster pairs
        ↓
  estimated 1,000–3,000 search units
```

The exact number will be confirmed after Stage 1 clustering is complete.

**Output — Search Unit Table:**

| Column | Description |
|---|---|
| `search_unit_id` | Unique ID |
| `herb_id` | From Stage 0 |
| `scientific_name` | For query construction |
| `disease_cluster_id` | From Stage 1 |
| `disease_synonyms` | All terms to include in query |
| `mechanism_terms` | Broadening terms for richer queries |
| `claim_ids_covered` | List of original claim IDs this unit represents |

**Implementation expectations:**
- A simple join operation: File 2 rows → lookup herb_id (Stage 0 table) → lookup cluster_id (Stage 1 table) → group by (herb_id, cluster_id)
- Validate: every claim in File 2 must map to exactly one search unit
- The exact search unit count is unknown until Stage 1 clustering is complete — this is the number that determines how many API calls and LLM calls the full pipeline will make
- Expected output size: 1,000–3,000 search units
- Expected time: under 5 minutes

---

## Stage 3 — Academic Search

**Purpose:** Retrieve real peer-reviewed papers for each search unit.

**Sources (in order):**
1. PubMed / MEDLINE *(via Entrez API — free)*
2. Europe PMC *(REST API — free)*
3. Semantic Scholar *(API — free)*

**Query structure:**

For each search unit, we construct a query using the scientific name and the full set of disease synonyms and mechanism terms:

```
"Ammi majus" AND ("wound healing" OR scar OR cicatrix OR "tissue repair")
```

**Metadata collected per paper:**

| Field | Source |
|---|---|
| Title | All |
| Abstract | All |
| PMID | PubMed, Europe PMC |
| DOI | All |
| Year | All |
| Journal / Conference name | All — native field in all three APIs |
| Publication type / Study type | PubMed tags (Clinical Trial, Review, Meta-Analysis, etc.) |

> **On journal/venue:** All three APIs return journal and venue data natively. PubMed provides publication type tags directly (e.g. "Randomized Controlled Trial"). No additional sources or scraping are needed.

**Paper selection:**  
Keep the top 1–3 papers per search unit that mention both the herb and the disease or mechanism. Papers are filtered by relevance before being passed to Stage 4.

**If no papers are found:**  
Document the search unit as `No Evidence Found` and move on. No fallback is triggered within the pipeline.

> **Optional suggestion (outside the pipeline):**  
> For search units that return no evidence, a discovery pass using Gemini or Serper (Google Scholar API) could be added as a post-processing step to surface potential sources. Any source found this way must be verified against PubMed or a valid DOI before being treated as evidence. This is not part of the core pipeline but could be considered if coverage gaps are significant.

**Output — Evidence Table:**

| Column | Description |
|---|---|
| `search_unit_id` | Links back to Stage 2 |
| `paper_title` | Title of the paper |
| `abstract` | Full abstract text |
| `pmid` | PubMed ID |
| `doi` | Digital Object Identifier |
| `source` | PubMed / Europe PMC / Semantic Scholar |
| `year` | Publication year |
| `journal_or_venue` | Journal name or conference — native field in all three APIs |
| `study_type` | Clinical trial / animal / in-vitro / review / ethnobotanical |

**Implementation expectations:**
- Query PubMed first for every search unit; move to Europe PMC and Semantic Scholar only if PubMed returns fewer than 3 relevant papers
- Apply rate limiting: PubMed allows 10 requests/sec with a free API key — throttle accordingly
- Cache all retrieved papers locally (CSV or SQLite) so the search never needs to be re-run
- All three APIs return journal/venue as a native field — no scraping needed
- Search log must record every query string, source, number of results, and timestamp for full reproducibility
- Expected volume: 1,000–3,000 API search calls total (one per search unit)
- Expected time: 2–5 hours depending on rate limits and search unit count

---

## Stage 4 — LLM Scoring

**Purpose:** Use a language model to evaluate how well the retrieved evidence supports each claim.

**LLM:** To be decided based on cost, quality, and rate limits at our scale.

**How it works:**  
This stage operates on **all 10,948 claims individually**, but uses the cached evidence from Stage 3. For each claim, the pipeline looks up which search unit it belongs to, retrieves the papers already collected for that unit, and sends the claim + papers to the LLM.

Most of the scoring (disease support, effect support, source reliability, safety signal) is the same across all claims sharing a search unit — so in practice these scores are computed once and reused. The only score assessed per individual claim is **Treatment Match**, since treatment plans differ across claims even when the herb and disease are the same.

```
Search Unit SU_001: Ammi majus + wound healing
  Papers retrieved: P1, P2, P3

  Claim A: treatment = "ointment with honey"
    → Disease support: Agree       (from cached unit scoring)
    → Effect support: Agree        (from cached unit scoring)
    → Source reliability: Medium   (from cached unit scoring)
    → Safety signal: No            (from cached unit scoring)
    → Treatment match: Partial     (assessed for this claim specifically)
    → Final status: Partially Supported

  Claim B: treatment = "crushed powder applied"
    → Disease support: Agree       (reused from Claim A)
    → Effect support: Agree        (reused from Claim A)
    → Source reliability: Medium   (reused from Claim A)
    → Safety signal: No            (reused from Claim A)
    → Treatment match: Not Assessed (assessed for this claim specifically)
    → Final status: Partially Supported
```

### Scores Returned:

| Score | Options | Notes |
|---|---|---|
| **Source Reliability** | High / Medium / Low | Based on study type — clinical trial = High, in-vitro = Low |
| **Disease Support** | Strongly Agree / Agree / Neutral / Disagree / Strongly Disagree | Does the evidence address the specific disease claimed? |
| **Effect Support** | Strongly Agree / Agree / Neutral / Disagree / Strongly Disagree | Does the evidence support the claimed effect? |
| **Treatment Match** | Exact / Partial / Not Assessed | Does the preparation method align with what was studied? Assessed per claim. |
| **Safety Signal** | Yes / No | Does any evidence suggest harm or contraindication? |
| **Final Status** | See table below | Derived from the above scores |

### Final Status Mapping:

| Situation | Final Status |
|---|---|
| High/Medium reliability + Disease/Effect Agree or above | ✅ Supported |
| Low reliability + Disease/Effect Agree or above | 🟡 Partially Supported |
| Neutral evidence | ⚪ Inconclusive |
| Disagree or Strongly Disagree | ❌ Contradicted |
| No papers retrieved in Stage 3 | ⬜ No Evidence Found |
| Safety signal detected | ⚠️ Safety Concern |

**Why dual scoring matters:**  
Source reliability and claim support are stored as separate scores, not merged. An in-vitro paper may strongly support a claim while remaining low clinical reliability — a distinction that a single verdict would hide, and one that matters when interpreting evidence from a 16th-century medical text.

**Implementation expectations:**
- The LLM receives a structured prompt and must return a structured response (JSON) — Python code parses the response and writes it to the output table automatically. No manual work involved.
- All LLM responses are cached by search_unit_id so no unit is ever scored twice
- Rate limiting and exponential backoff must be implemented to handle API limits reliably
- Expected LLM calls: ~1,000–3,000 (per search unit) + lightweight per-claim treatment match assessment
- Expected time: depends on chosen LLM and rate limits — to be confirmed once LLM is selected

---

## Stage 5 — Excel Output

**Purpose:** Write all results back to a structured Excel workbook automatically.

**Important:** Excel writing is fully automated. The LLM returns structured JSON responses; Python code (OpenPyXL) parses them and writes every sheet. No manual data entry is involved.

The workbook is organized into 5 sheets, each serving a distinct purpose — so any reader can go directly to what they need without being overwhelmed.

---

### Sheet 1 — `claims_summary` *(the quick-read sheet)*
One row per original claim. This is the first sheet anyone opens.

| Column | Description |
|---|---|
| `claim_id` | Original claim ID |
| `herb_arabic` | Arabic herb name from the book |
| `scientific_name` | Resolved scientific name |
| `disease` | Original disease text from the book |
| `treatment_plan` | Treatment as described in the book |
| `effect` | Claimed effect |
| `validation_status` | Final verdict — Supported / Partially Supported / Inconclusive / Contradicted / No Evidence Found / Safety Concern |
| `evidence_summary` | 1–2 sentence human-readable summary of what the literature says |
| `pmid` | PubMed ID (clickable reference) |
| `requires_human_review` | Yes / No — flagged for manual follow-up |

---

### Sheet 2 — `detailed_scores` *(the scoring breakdown sheet)*
One row per claim, linked to Sheet 1 by `claim_id`. For when you need to understand why a claim got its verdict.

| Column | Description |
|---|---|
| `claim_id` | Links to Sheet 1 |
| `source_reliability` | High / Medium / Low |
| `disease_support` | Strongly Agree → Strongly Disagree |
| `effect_support` | Strongly Agree → Strongly Disagree |
| `treatment_match` | Exact / Partial / Not Assessed |
| `safety_signal` | Yes / No |

---

### Sheet 3 — `papers_cited` *(the evidence library)*
One row per paper retrieved. For verifying citations and examining the actual evidence.

| Column | Description |
|---|---|
| `search_unit_id` | Which search unit this paper belongs to |
| `paper_title` | Full paper title |
| `journal_or_venue` | Where it was published |
| `year` | Publication year |
| `study_type` | Clinical trial / animal / in-vitro / review / ethnobotanical |
| `pmid` | PubMed ID |
| `doi` | Digital Object Identifier |
| `abstract_snippet` | First 300 characters of abstract |
| `source` | PubMed / Europe PMC / Semantic Scholar |

---

### Sheet 4 — `search_log` *(the reproducibility sheet)*
One row per query executed. For auditing exactly what was searched and when.

| Column | Description |
|---|---|
| `search_unit_id` | Which unit was searched |
| `scientific_name` | Herb searched |
| `disease_cluster` | Disease cluster searched |
| `query_executed` | Exact query string sent to the API |
| `source` | PubMed / Europe PMC / Semantic Scholar |
| `num_results_returned` | Total papers the API returned |
| `num_results_kept` | Papers kept after relevance filtering |
| `timestamp` | When the query ran |

---

### Sheet 5 — `summary_statistics` *(the big picture sheet)*
Aggregate view of the full validation run.

```
Total claims validated:      10,948
Supported:                    X  (X%)
Partially Supported:          X  (X%)
Inconclusive:                 X  (X%)
Contradicted:                 X  (X%)
No Evidence Found:            X  (X%)
Safety Concern:               X  (X%)

Search units created:         ~1,000–3,000
Total papers retrieved:       X
Claims requiring human review: X

Top 10 most supported herbs
Top 10 herbs with no evidence found
Most common disease clusters
```

---

## Tech Stack

| Component | Tool |
|---|---|
| Data handling | Python, Pandas, OpenPyXL |
| PubMed search | Biopython Entrez API |
| Europe PMC search | Europe PMC REST API |
| Semantic Scholar search | Semantic Scholar API |
| Disease normalization | Manual table + MeSH terms + LLM assistance |
| LLM scoring | To be decided |
| Output | Excel (.xlsx) |

No heavy frameworks, no local models, no vector databases.

---

## Pilot Plan

Before scaling to all 10,948 claims, run the full pipeline on **200 stratified claims**:

| Group | Count |
|---|---|
| Common herbs with clear scientific names | 80 |
| Common diseases (headache, fever, wounds) | 60 |
| Rare herbs with limited literature | 40 |
| Ambiguous or multi-condition claims | 20 |

Manually review 30 outputs with the team and report:
- Retrieval success rate
- Citation validity rate
- Scoring agreement rate
- Average evidence quality

Scale to full dataset only after pilot review.

---

## Approval & History

| Date | Event |
|---|---|
| — | Pipeline designed by validation sub-team |
| — | Submitted to Doctor Taher for review |
| — | Doctor Taher approved — "Proceed" |
| — | Version 2.0 — Updated based on team clarifications: reframed goals, fixed LLM call model, reorganized Excel output sheets |

---

*This document serves as the reference for the validation sub-team. All stages, decisions, and design choices are recorded here for reproducibility and team alignment.*
