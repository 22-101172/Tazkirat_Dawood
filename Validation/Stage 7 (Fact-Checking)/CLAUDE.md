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
0b. **Name expansion** — anchor the query on ALL the plant's validated literature names
   (`data/plant_names.json`, built by `build_plant_names.py`), not just one. `USE_NAME_EXPANSION`.
1. **Retrieve** up to 25 papers from **Europe PMC** (free, no key; = PubMed + preprints).
   (Optional: widen query with the plant's distinctive compounds — see Enrichment / `EXP_ENRICH`.)
2. **Filter** (fast LLM, thinking off) → keep only papers relevant to the specific claim.
3. **Judge** (LLM, thinking on) on the filtered papers → verdict + Arabic reason.

- Model: `gemini-3-flash-preview` (Vertex AI, location `global`).
- **ALL LLM stages run at `temperature=0`** (greedy) as of 2026-07-20 → pipeline is now
  reproducible. (Before this, default temperature made normalization non-deterministic →
  ~18% row-level verdict churn between identical runs.)
- Every row fully traced to `data/factcheck_trace_v1<tag>.jsonl` (all prompts, raw
  responses, query string, papers found/kept). Fail-safe: append + flush + fsync per row.

## Current results (300-row sample)

Aggregate distribution (baseline, ~unchanged by naming; enrichment shifts Insufficient→Neutral):

| Category | Baseline | Enriched-distinctive | Name-expansion |
|---|---:|---:|---:|
| Strongly Agree | 4.3% | 3.7% | 4.7% |
| Agree | 8.7% | 7.5% | 8.3% |
| Neutral | 27.2% | 36.0% | 29.0% |
| Disagree | 1.0% | 1.3% | 0.3% |
| Strongly Disagree | 1.2% | 0.1% | 1.0% |
| No Modern Equivalent | 1.3% | 1.0% | 1.3% |
| Insufficient Evidence | 56.3% | 50.2% | 55.3% |

**IMPORTANT (2026-07-20):** the naming and enriched numbers above were measured BEFORE the
temperature=0 fix, when a ~18% row-level noise floor buried real effects. They should be
**re-measured now that the pipeline is deterministic** — that is the immediate next task.
Retrieval recall from naming is real (+44% chamomile, +143% Dioscorea) but the 25-paper cap
means extra names reshuffle rather than add — needs the per-name-merge fix to reach the judge.

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

## Next steps / open decisions (as of 2026-07-20, start of next session)

**Immediate (do first):**
1. **Re-measure baseline vs name-expansion vs enriched NOW that temperature=0 makes the
   pipeline deterministic.** The prior numbers were taken under ~18% noise; the real effects
   were buried. Re-run the 300 sample for each config (they'll now be reproducible, so one run
   each suffices) and compare cleanly.

**Then, two targeted fixes already scoped:**
2. **Per-name merge** for name expansion: retrieve each plant name separately and merge the
   top papers from each, instead of OR-ing all names into one 25-capped pool (which reshuffles
   rather than adds). This lets the +44–143% recall actually reach the judge.
3. **Safety vs efficacy** in the judge: a toxicity/adverse-effect finding should raise a
   SAFETY FLAG, not score as `Disagree` with a therapeutic claim, unless a study tested that
   use and found it fails. Fixes the over-strong Disagrees (Melia "counteracts toxins" →
   confidently wrong; Cyclamen pollen-allergen). See the Melia trace.

**Then:**
4. **Run the full ~7,362-row file** (`SAMPLE_MODE = False`) — the deliverable. NEEDS EXPLICIT
   USER PERMISSION each time (hard rule). Also run `build_plant_names.py` over all 645 plants
   first (currently only the 25 sample plants are built).

**Open decisions (Dr. Taher):** adopt enrichment? (lateral: shifts ~6pt Insufficient→Neutral,
adds no confident verdicts). Full-file projected split (baseline): ~960 supported, ~2,000
Neutral, ~160 refuted, ~4,150 Insufficient.

**Git:** everything through 2026-07-20 committed locally; user pushes with `git push`.
Source book PDF + full OCR live in `../../tadhkirat_dawood_Drive/` (local, gitignored, NOT
committed — large + scanned-edition). Trace PDFs saved in `traces/`.

---

## Session Log (continued)

- **2026-07-20** — ROOT-CAUSED the 18% instability (Dr. Taher pushed back on the consensus
  band-aid). Isolated each stage on one claim, 5 repeats holding input fixed: RETRIEVAL
  deterministic (identical papers); JUDGE deterministic (5/5 same verdict on same papers);
  NORMALIZATION fully stochastic (5/5 different term-sets); FILTER partly (2/5). Cause: LLM
  stages ran at the model DEFAULT temperature (~1.0). Normalization generating different
  search terms each call cascaded → different query → different papers → different verdict
  (the judge just faithfully reflected changed input). FIX: set temperature=0 on all LLM
  configs (_NORMALIZE_CONFIG, _FILTER_CONFIG, _BROAD_CONFIG, and the judge call). Verified:
  normalize now 1/5 term-sets; full judge_row run twice per claim = IDENTICAL verdicts.
  Pipeline is now reproducible. This supersedes the earlier "consensus" proposal. NEXT:
  re-measure naming/enrichment now that the 18% noise is gone (their true effect was buried).

- **2026-07-18** — Started step #4 (retrieval recall), reframed by Dr. Taher as "the right
  name is crucial." Found plant names are clean (642/645 GBIF-validated) but literature uses
  SYNONYMS our single-name search misses — e.g. chamomile is published as *Matricaria
  chamomilla* (2,407), *Matricaria recutita* (1,199), AND *Chamomilla recutita* (401): ~1,600
  papers missed. Built `build_plant_names.py` → `data/plant_names.json`: per-plant validated
  name-set = accepted name + GBIF synonyms + LLM literature names, gated by (a) GBIF
  same-accepted-species check (rejects same-genus impostors like Bryonia dioica≠alba) and
  (b) Europe PMC hit-count ≥30. On the 25 sample plants, 6 gained true synonyms; recall gain
  +44% (chamomile), +143% (Dioscorea communis). Wired into retrieval as `_plant_clause` (OR
  of the name-set), toggle `USE_NAME_EXPANSION` / env `EXP_NAMES`. NEXT: re-run sample to
  measure verdict impact; run the builder over all 645 plants for the full file.
- **2026-07-20** — Ran name-expansion sample (tag `names`) vs baseline/enriched. KEY FINDING:
  verdict impact is WITHIN NOISE. Row-level noise floor (base1 vs base2, identical config) =
  18% of rows flip from LLM judge non-determinism alone. Name-expansion overall churn vs
  base = 18% (= noise); on multi-name plants 31% vs 26% noise floor. Aggregate Insufficient
  56.3%→55.3% (−1pp, within noise). Cause: (1) 25-paper cap → extra names reshuffle the top-25
  rather than add (avg retrieved 21.1→21.5, flat), (2) the 18% judge variance swamps the
  effect. Retrieval recall gain is real (+44–143% raw hits) and methodologically correct, keep
  it, but it must actually reach the judge. TWO FIXES: (a) retrieve per-name and MERGE (union
  of top papers/name) instead of OR-into-capped-pool; (b) bigger lever — reduce the 18% judge
  variance via consensus (run each claim 2–3× / majority vote). The 18% instability is the
  ceiling on every other improvement.

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
- **2026-07-17** — Built a full book→decision trace for a Strongly Disagree (Dr. Taher request).
  User provided `tadhkirat_dawood_Drive/` (has the source PDF `Tathkerat Dawood Alantaqi.pdf`,
  852 scanned pages = the "OCR images"; plus `raw_pages/` full OCR text). Traced entry 47
  (Asarum europaeum): book PDF p.53 (printed ٥١) → OCR text (conf 0.85) → claim "purifies the
  kidneys" → normalize → Europe PMC query → 17 found → 3 kept → Strongly Disagree, because
  Asarum contains aristolochic acid (aristolochic acid nephropathy = irreversible renal
  fibrosis/carcinogen). Genuine safety-critical contradiction, correct. Rendered p.53 via
  PyMuPDF (installed to venv); published visual trace as a Claude artifact. Note: repo `ocr/`
  is text only; page IMAGES live in the Drive PDF, not committed.
- **2026-07-17** — Built a CONTRAST trace (Melia azedarach, entry 43 "Toxins", Strongly
  Disagree, conf 1.0) to avoid cherry-picking. Shows a category error: condition "counteracts
  toxins" got normalized to "toxicity/poisoning" → search returned papers on Melia's OWN
  toxicity → judge concluded "plant is toxic, so not an antidote" (a safety fact used as an
  efficacy verdict). Both traces exported as PDFs in `tadhkirat_dawood_Drive/` (Asarum_trace.pdf
  = correct SD, Melia_trace.pdf = flawed SD) + published as artifacts, for the user to send
  Dr. Taher. Honest framing: of 9 Disagree/SD, ~3 genuinely correct, ~2 over-strong logic,
  ~1 variance.
- **2026-07-17** — Committed (locally, pending user push): top-level `ocr/` folder = 373 OCR
  raw page text files (renamed from `raw_pages_v2/`, per user request); plus Stage 7 variance
  result CSVs + traces, this CLAUDE.md, and the `.env` loader. Two commits ahead of
  `origin/main` (`f36be0a` ocr, `921487c` stage7). User to run `git push`.
