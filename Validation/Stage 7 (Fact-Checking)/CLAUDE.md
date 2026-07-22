# Stage 7 — Fact-Checking — Working Notes (CLAUDE.md)

Living document for this work. **Update the Session Log (bottom) after each meaningful action.**

---

## Reporting protocol (how to present results — follow every time)

**The noise floor is ~7% row-level** (two identical runs at temperature=0 disagree on ~7% of
rows; it was 18% before). Always judge results against it:
- **Aggregate distributions are trustworthy** — flips cancel, so category %s wobble only ~1–2pt.
  Report these with confidence.
- **Per-claim verdicts are still ~7% unstable** — never present a single row's verdict as final
  without noting this (consensus/majority-vote is the open fix for the per-claim deliverable).
- A config's effect is **real only if its row-churn vs baseline clearly exceeds ~7%** AND the
  aggregate moves beyond ~1–2pt. Otherwise call it noise. State this explicitly.

**When reporting to the user:** (1) lead with the honest bottom line — real effect or noise;
(2) show the category comparison; (3) explain the mechanism from retrieval stats (db-hits,
papers-after-filter), not hand-waving; (4) flag caveats — never oversell, never cherry-pick
(if showing one example, say it's an example and give the mixed reality); (5) recommend the
next step. The user values blunt honesty over good news.

**When drafting a message to Dr. Taher** (he gets a WhatsApp text, relayed by the user):
- Plain text. **No emojis. No greeting** — open with "Update on the test" or go straight to
  the point.
- Numbers as plain-text lists or `before -> after` lines, **never markdown tables** (they don't
  render in WhatsApp). Right-align mentally; keep it scannable.
- Add a one-line legend for verdict categories he may not recall (Neutral, No Modern
  Equivalent, Insufficient) when they appear.
- Be honest about what's real vs noise vs a lateral move. Include a short "caveat" line.
- End with **proposed next steps in priority order + your recommendation**.
- Offer an Arabic version at the end.
- Keep it tight and to the point — he is technical and busy.

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
- **ALL LLM stages run at `temperature=0`** (greedy) as of 2026-07-20. This roughly HALVED
  the run-to-run noise (18% → ~7% row-level churn) but did NOT eliminate it — the pipeline is
  **NOT fully deterministic**. Measured 2026-07-20: identical config, two runs, 7/100 rows flip
  verdict (all adjacent-category boundary flips: Agree↔Neutral, Neutral↔Insufficient, SA↔Agree).
  Gemini is not bit-reproducible even at greedy decoding. So "one run each suffices" is FALSE;
  a residual ~7% noise floor remains and majority-vote/consensus is still the lever to kill it.
- Every row fully traced to `data/factcheck_trace_v1<tag>.jsonl` (all prompts, raw
  responses, query string, papers found/kept). Fail-safe: append + flush + fsync per row.

## Current results (300-row sample) — RE-MEASURED at temperature=0 (2026-07-20)

Runs: `base_det` (names off, enrich off), `names_det` (names on), `enr_det` (enrich on, llm
distinctive compounds). One run each, full 300 rows, 0 errors. Noise floor from `base_det2`
(identical config re-run, 100-row every-3rd subset) = **7.0% row-level self-churn**.

| Category | Baseline | Name-expansion | Enriched-distinctive |
|---|---:|---:|---:|
| Strongly Agree | 5.3% | 4.7% | 3.7% |
| Agree | 8.7% | 9.0% | 7.3% |
| Neutral | 27.0% | 28.7% | 37.0% |
| Disagree | 1.3% | 1.0% | 0.7% |
| Strongly Disagree | 1.0% | 0.7% | 0.7% |
| No Modern Equivalent | 1.0% | 0.7% | 1.0% |
| Insufficient Evidence | 55.7% | 55.3% | 49.7% |

Row-level churn vs baseline: **names = 12.7%** (barely above the 7% noise floor → ~5.7pp real),
**enriched = 33.8%** (well above floor → real). Retrieval means: baseline retrieved 15.9 /
after-filter 2.33 / db-hits 98.9; enriched retrieved 19.3 / after-filter **1.73** / db-hits **287.5**.

**Verdict — which improvements are real:**
- **Name expansion (as wired): NOT a real verdict change.** Aggregate is flat (Neutral +1.7,
  Insufficient −0.4, both within noise) and row-churn (12.7%) barely clears the 7% floor. The
  +44–143% retrieval recall is real but stuck behind the 25-paper cap (extra names reshuffle,
  don't add). Keep it (methodologically correct), but it only matters AFTER the per-name-merge fix.
- **Enrichment: a REAL but LATERAL effect.** db-hits ~3× (98.9→287.5) but after-filter DROPS
  (2.33→1.73): the compound papers are mostly off-claim pharmacology, the filter discards more,
  and the few that pass are mechanism papers → **Neutral**. Net: Neutral +10pp (27→37),
  Insufficient −6pp, and confident verdicts (SA+Agree) slightly DROP (14.0→11.0). It converts
  "no study" into "plausible but unproven" — it does NOT produce more confident agreement/refutation.

The high Insufficient rate (~56%) is largely **genuine** — verified by reading papers: many
obscure plant×condition pairs simply have no modern study. ≤10% Insufficient is not
achievable without fabricating.

## Cost model (measured 2026-07-20, from real `usage_metadata`)

`gemini-3-flash-preview` on Vertex ≈ **$0.50/1M input, $3.00/1M output** (3rd-party aggregators;
confirm vs actual billing). Per-stage tokens (representative random sample, baseline config):
- normalize: in 222 / out 31 (thinking off) — 300 calls per 300 rows
- filter: in 2,162 / out 4 (thinking off) — 267 calls
- judge: in 1,923 / **out ~5,242 (of which ~5,056 are THINKING tokens)** — 193 calls
- **Per row ≈ 3,383 in / 3,406 out.** Output (≈85% of cost) is dominated by the judge's thinking.

Full file (7,362 rows), baseline config:
- **×1 ≈ $88** (input $12 + output $75).  **×3 ≈ $263** (input $37 + output $226).
- **$70 is NOT enough for even one full run.** The lever is the judge's thinking budget (currently
  default/dynamic ~5k tok). Capping it (e.g. thinking_budget=0, like the filter) would cut output
  ~10× → 3× full ≈ **~$45–50** (fits $70) — but must A/B on the sample first to confirm verdicts hold.
  Enrichment config costs MORE (judges more rows). Only judged rows (~64%) incur the big thinking cost.

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
1. ~~Re-measure baseline vs name-expansion vs enriched.~~ **DONE 2026-07-20** (see Current
   results). CORRECTION: pipeline is NOT deterministic — ~7% residual noise floor remains at
   temperature=0, so "one run suffices" was false. Name expansion = no real verdict change (yet);
   enrichment = real but lateral (Insufficient→Neutral, no confident gain).

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

- **2026-07-20 (later)** — Re-measuring baseline/name-expansion/enriched on the 300 sample
  now that temperature=0 makes the pipeline deterministic (one run each suffices). Clean 3-way
  design, each config differs from a common baseline by ONE toggle: `base_det` (EXP_NAMES=0,
  no enrich), `names_det` (EXP_NAMES=1), `enr_det` (EXP_NAMES=0, EXP_ENRICH=1, COMPOUND_SET=llm
  distinctive). Launched all three in parallel (distinct EXP_TAG → distinct output files, so
  file-safe; the old corruption was two runs on the SAME csv). ~9s/row. Analysis pending.
- **2026-07-20 (later, cont.)** — RESULTS IN + a big correction. Ran all three (300 rows, 0
  errors) via `analyze_det_runs.py`. THEN checked the "deterministic" premise: re-ran baseline
  (`base_det2`, every-3rd 100-row subset, identical config) → **7/100 rows still flip verdict**.
  So temperature=0 did NOT make the pipeline deterministic; it halved the noise (18%→~7%) but a
  residual floor remains (Gemini not bit-reproducible at greedy). All flips are adjacent-category
  boundary calls. Corrected the CLAUDE.md body claims. FINDINGS vs the 7% floor: (1) name
  expansion is NOT a real verdict change — aggregate flat, row-churn 12.7% barely clears floor;
  recall gain is real but capped, needs per-name-merge to matter. (2) Enrichment IS real but
  LATERAL — db-hits ~3× yet after-filter DROPS 2.33→1.73, shifting ~Insufficient→Neutral (+10pp
  Neutral) while confident verdicts slightly drop; "plausible but unproven", not proof. So the
  single-run aggregates are trustworthy (aggregates far more stable than row-churn) but row-level
  reproducibility needs consensus/majority-vote. NEXT: proceed to the two scoped fixes
  (per-name merge; safety-vs-efficacy judge). Consensus is re-opened as the noise-floor lever.
- **2026-07-20 (later, cont.)** — COST MODEL measured (user asked: does $70 credit cover 3×
  full runs?). Measured real `usage_metadata` on random samples of each stage. Answer: NO —
  $70 covers neither 3× (~$263) nor even 1× (~$88) full run at current settings. Driver = the
  judge's THINKING tokens (~5,056/claim, billed as output at $3/1M); output ≈85% of cost. Full
  cost model written to the new "Cost model" section. KEY LEVER: capping the judge thinking
  budget (like the filter) cuts output ~10× → 3× full ≈ $45–50 (fits $70), but needs a sample
  A/B to confirm verdicts hold first. Pricing $0.50/$3.00 per 1M from 3rd-party aggregators —
  confirm vs actual Vertex billing. Proposed next action: run the reduced-thinking A/B on the
  300 sample (~$1–2) to see if the cheap 3× path is viable.
- **2026-07-20 (later, cont.)** — DECISION (Dr. Taher, relayed by user): accept the ~7% variance
  (no 3–5× consensus — too expensive) and DO THE FULL RUN. Rationale accepted: flips never cross
  support↔contradiction (only strength wobbles at boundaries), aggregates stable ±1–2pt, and the
  ~7% unstable rows = low-confidence/borderline claims → flag those for human review instead of
  re-running. USER PERMISSION FOR FULL RUN: GRANTED (this satisfies the hard rule). Plan: single
  full baseline run + borderline-flagging. BUDGET BLOCKER: full-thinking full run ≈ $88 > $70
  credit → must use a leaner judge. Added env toggle `EXP_JUDGE_THINK` (caps judge thinking_budget;
  built `_JUDGE_CONFIG`). Running an A/B first (`base_lean`, EXP_JUDGE_THINK=0, 300 sample) vs
  `base_det` (full thinking): if churn ≈ the 7% floor, the leaner judge is statistically identical
  → use it for the full run (≈$15–25, fits budget). Full run config = baseline (names off:
  plant_names only has 25 plants; enrich off: lateral, not adopted). Heads-up: full run ≈ 18h
  wall-clock single-process at ~9s/row (leaner judge should be faster). NOT launched yet —
  awaiting A/B result + user go on runtime/thinking setting.
- **2026-07-20 (later, cont.)** — Judge thinking-budget A/B (baseline, 300 sample) vs full-thinking
  `base_det`: EXP_JUDGE_THINK=0 → **25.8% disagreement** (>> 7% floor) and a big aggregate shift
  (Insufficient 56→42, Neutral 27→42) — thinking-off is systematically MORE LENIENT (calls
  no-evidence "plausible"). No support↔contradiction crossings, but not a faithful substitute.
  Was mid-testing 2048/3072 middle budgets when the user said STOP, then decided: **run the FULL
  file at FULL cost/thinking; when credit runs out it pauses, user tops up and re-runs to finish.**
- **2026-07-20 (later, cont.)** — FULL RUN LAUNCHED (user permission granted). Config: SAMPLE_MODE=0,
  EXP_NAMES=0 (baseline), full dynamic thinking, EXP_TAG=full → `data/factcheck_retrieve_judge_v1_full.csv`
  (+ `_full` trace/progress/log). Est ~$88 / ~18h. Made the run RESUME-ROBUST first (needed for the
  top-up-and-continue plan): (1) SAMPLE_MODE is now an env toggle; (2) resume RE-ATTEMPTS ERROR/
  PARSE_ERROR rows (previously they were marked done and skipped forever → would have silently
  dropped every row after credit ran out); (3) circuit breaker aborts cleanly after 12 consecutive
  failures (credit/quota exhaustion) instead of ERROR-flooding thousands of rows.
  **RESUME PROCEDURE** (after topping up credit): re-run the EXACT same command —
  `SAMPLE_MODE=0 EXP_NAMES=0 EXP_TAG=full python3 stage7_retrieve_judge.py` — done rows are skipped,
  failed rows are re-attempted. Monitor: `data/factcheck_rj_progress_v1_full.txt`, log `data/run_full.log`.
- **2026-07-22** — FULL RUN COMPLETE. All **7,362 rows, 0 errors**, no credit cutout (finished
  before funds ran out → the ~$88 estimate was high; real judge-thinking averaged below the
  20-sample figure). Output: `data/factcheck_retrieve_judge_v1_full.csv` (645 entries, 478 plants).
  FINAL DISTRIBUTION: Strongly Agree 460 (6.2%), Agree 727 (9.9%), Neutral 1,747 (23.7%),
  Disagree 95 (1.3%), Strongly Disagree 52 (0.7%), No Modern Equivalent 81 (1.1%), Insufficient
  4,200 (57.0%). Supported 1,187 (16.1%) vs Refuted 147 (2.0%) → ~8:1. 65.1% reached the judge
  with evidence. needs_human_review = 4,200 (all Insufficient). Matches the 300-sample within
  ~1pt — no drift at scale. NEXT: (a) build the human-review shortlist (start with low-confidence
  Neutral/Agree — the ~7% wobble lives there — and the 147 refutations for the safety-vs-efficacy
  check); (b) the two scoped code fixes (per-name merge, safety-vs-efficacy) still pending;
  (c) deliver summary to Dr. Taher. Git: committed through 2026-07-20; full-run outputs uncommitted.
- **2026-07-22** — Dr. Taher REFRAMED the deliverable: stop dwelling on the 57% Insufficient;
  instead ask "which heavily-researched modern diseases does the (already-validated) book answer?"
  and start trusting the book — treat Insufficient/Neutral as credible untested LEADS, not
  disproven. Built the disease-area view: heuristic keyword grouping of the archaic conditions
  into 15 modern areas (`data/_full_themed.csv`, script `build_report.py`). Supported (1,187) by
  area, top: Digestive/liver 202, Cancer/tumors 135, Infection/antimicrobial 108, Mental/neuro 87,
  Respiratory 85, Skin 84. Highest research-volume matches (db_total_hits) are anti-tumor (Vitis,
  Nigella, Punica), antioxidant/anti-toxin (Zingiber, Nigella, Allium), anti-inflammatory (Hordeum,
  Spinacia), depression/anxiety (Hypericum). DELIVERABLE: `data/Stage7_book_answers_by_disease.xlsx`
  (5 sheets: Read me, All claims 7362, By disease area, Confirmed 1187, Refuted 147). Summary counts
  written as VALUES not COUNTIFS (no LibreOffice here to recalc formulas). Dr. Taher's point that
  "Insufficient needs checking" ties to the per-name-merge recall fix — some Insufficient is
  under-retrieval, not true absence. NEXT: per-name-merge fix; Arabic version of summary if asked.

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
