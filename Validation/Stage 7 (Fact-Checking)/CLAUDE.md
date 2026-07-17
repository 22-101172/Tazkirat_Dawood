# Stage 7 — Fact-Checking — Working Notes (CLAUDE.md)

Living document for this work. **Update the Session Log (bottom) after each meaningful action.**

---

## Goal

Validate the herb–disease treatment claims from *Tadhkirat Dawood al-Antaki* (a 17th-c.
Arabic materia medica) against modern scientific evidence, assigning each claim a verdict.

## Verdict schema (fixed)

`Strongly Agree` / `Agree` / `Neutral` / `Disagree` / `Strongly Disagree` /
`Insufficient Evidence` / `No Modern Equivalent`

- **Neutral** = documented (traditional/ethnobotanical) or mechanistically plausible, but
  no modern study directly tested it.
- **No Modern Equivalent** = pure humoral concept with no modern counterpart (e.g. "thick
  humors", "coldness of the stomach") — untranslatable, not unstudied.
- **Insufficient Evidence** = real modern condition, but no relevant study exists for this
  specific plant+condition.

## Current architecture (retrieve-then-judge)

`stage7_retrieve_judge.py`, pipeline per claim:
0. **Normalize** condition → modern search terms; pure-humoral → `No Modern Equivalent`.
1. **Retrieve** up to 25 papers from **Europe PMC** (free, no key; = PubMed + preprints).
   (Optional: widen query with the plant's distinctive compounds — see Enrichment.)
2. **Filter** (fast LLM, thinking off) → keep only papers relevant to the specific claim.
3. **Judge** (LLM, thinking on) on the filtered papers → verdict + Arabic reason.

- Model: `gemini-3-flash-preview` (Vertex AI, location `global`).
- Every row fully traced to `data/factcheck_trace_v1<tag>.jsonl` (all prompts, raw
  responses, query string, papers found/kept). Fail-safe: append + flush + fsync per row.

## Current results (300-row sample, 2 runs each, 2026-07-17)

Run-to-run variance is small (≤1.3 percentage points on any category) → pipeline is stable.

| Category | Baseline (avg) | Enriched-distinctive (avg) |
|---|---:|---:|
| Strongly Agree | 4.3% | 3.7% |
| Agree | 8.7% | 7.5% |
| Neutral | 27.2% | 36.0% |
| Disagree | 1.0% | 1.3% |
| Strongly Disagree | 1.2% | 0.1% |
| No Modern Equivalent | 1.3% | 1.0% |
| Insufficient Evidence | 56.4% | 50.2% |

**Enrichment's only above-noise effect:** moves ~6 pts Insufficient → Neutral (+8.8 Neutral,
−6.1 Insufficient). It does NOT increase confident verdicts (Agree/SA flat within noise).
It surfaces mechanism/pharmacology papers = "plausible but unproven", not proof.

The high Insufficient rate (~56%) is largely **genuine** — verified by reading papers: many
obscure plant×condition pairs simply have no modern study. ≤10% Insufficient is not
achievable without fabricating.

## Key files (in this folder)

- `stage7_retrieve_judge.py` — main pipeline (retrieve → filter → judge).
- `stage7_factcheck.py` — earlier Vertex + Google Search grounding version (deprecated path).
- `build_distinctive_compounds.py` — builds per-plant distinctive-compound lists (LLM vs
  quant species-count) from Wikidata → `data/distinctive_compounds.json`.
- `data/` — inputs, result CSVs (`_base1/2`, `_enr1/2`, `_expB/C/Bllm`), JSONL traces,
  `_*_backup/` snapshots.
- `.env` (gitignored) — real `VERTEX_PROJECT_ID` / `CONTACT_EMAIL`. `.env.example` is the template.

## How to run

```bash
source ../../venv/bin/activate           # venv is at repo root
python3 stage7_retrieve_judge.py         # reads .env automatically
```
- `SAMPLE_MODE = True` → reproducible 300-row sample (seed 42, 3 blocks).
- Experiment env toggles: `EXP_ENRICH=1`, `EXP_COMPOUND_SET=llm|quant|raw`,
  `EXP_BROAD=1`, `EXP_TAG=<name>`, `EXP_EVERY=<n>`.

## Hard constraints

- **NEVER run the full ~7,362-row file** (`SAMPLE_MODE = False`) without explicit user
  permission. Sample runs are fine.
- **NEVER handle the user's GitHub token / GCP credentials.** The user does auth/push.

## Problems hit & fixes (this session)

1. **Grounding returned Google redirect URLs**, not real domains → credibility check always
   failed → resolve each redirect to its real URL before checking.
2. **Grounding is non-deterministic** → best-of-N re-rolls (in the grounding version).
3. **`resp.text` sometimes None** (recitation/safety) crashed parsing → treated as a failed pass.
4. **Gemini 3.0 Flash won't reliably invoke web search** on our prompt → pivoted to
   retrieve-then-judge (we fetch papers; model only reads → cheap model works).
5. **OpenAlex 429-bans the IP for up to ~24h** after bursts → use Europe PMC only.
6. **Europe PMC `sort=relevance` param returns empty** → drop it (default is relevance).
7. **Filter LLM took 43s/row** (over-thinking) → `thinking_budget=0` → 2.5s.
8. **Two runs wrote the same CSV** (stray process survived pkill) → corruption → unique tags
   + verify single process.
9. **Enrichment with all compounds added noise** (generic cholesterol/palmitic acid, 7×
   hit inflation) → distinctive compounds (LLM picks > quant "rarest", which picks DB noise).
10. **Sanitizing project ID for GitHub broke local runs** (placeholder → 403) → added `.env`
    loader + gitignored `.env` with real values.
11. **git push failed HTTP 400 / sideband** → `http.postBuffer=500MB` + `http.version=HTTP/1.1`.

## GitHub

- Repo: `https://github.com/22-101172/Tazkirat_Dawood` (public; user is a collaborator).
- Our work lives under `Validation/Stage 7 (Fact-Checking)/`. Owner's `Preprocessing/` and
  other `Validation/` stages untouched.
- Pushed through commit `899c522`. Email + project ID scrubbed from all committed code/notebook.

## Next steps / open decisions

- **Adopt enrichment?** (Dr. Taher's call) — it trades ~6 pts Insufficient for Neutral;
  baseline is the more conservative/high-confidence config.
- **Suggested improvements (proposed, not yet done):**
  1. Make enrichment a *fallback* (only when plain search returns nothing) to keep dense
     evidence on covered claims.
  2. Raise retrieval recall (real bottleneck ~2.5 relevant papers/claim): test MeSH-term
     mapping and a second DB (Semantic Scholar).
- Commit the 4 variance result files + `.env` loader fix (pending user go-ahead).
- Report full variance results to Dr. Taher (draft ready).

---

## Session Log

_Append a dated entry after each meaningful action. Newest at the bottom._

- **2026-07-17** — Created this CLAUDE.md. State at creation: retrieve-then-judge pipeline
  finalized; baseline vs enriched-distinctive variance runs complete (2×2, ≤1.3pt noise);
  work uploaded to GitHub under `Validation/Stage 7 (Fact-Checking)/`; `.env` loader added
  so local runs work post-sanitization. Pending: decide on enrichment adoption; commit
  variance results + loader fix; send variance report to Dr. Taher.
- **2026-07-17** — Investigated Disagree/Strongly-Disagree root cause (Dr. Taher request).
  12 rows across 4 runs → 9 unique claims. **Not mistranslation** (Arabic→English accurate).
  Three buckets: (1) GENUINE & valuable — Asarum/aristolochic-acid nephrotoxicity, basil
  "generates worms" vs anti-helminthic, chamomile/fatigue null meta-analysis; (2) OVER-STRONG
  LOGIC (main issue) — toxicity/adverse-event/wrong-plant-part treated as efficacy refutation
  (Melia azedarach ×3: own toxicity + a pseudo-obstruction case report used to refute
  purgative/antidote claims; Cyclamen: pollen allergen used to refute tuber anti-asthma use);
  (3) run-to-run variance (chamomile/ophthalmia flips Agree↔Disagree). Proposed fix: judge
  should separate SAFETY from EFFICACY — a toxicity/adverse finding raises a safety flag, not
  a "Disagree", unless a study actually tested efficacy for that condition and found it fails.
