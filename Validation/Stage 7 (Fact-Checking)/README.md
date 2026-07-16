# Stage 7 — Fact-Checking with Credible Sources

Validates the herb–disease treatment claims from *Tadhkirat Dawood al-Antaki* against
modern scientific evidence.

## Approach (retrieve-then-judge)

Rather than asking an LLM to search the web (expensive, and the model won't reliably
ground), the pipeline **pulls papers first, then feeds them to the model**:

1. **Normalize** the archaic/compound condition into modern search terms; pure humoral
   concepts (e.g. "thick humors") are labelled *No Modern Equivalent*.
2. **Retrieve** peer-reviewed papers from **Europe PMC** (free, no key; = PubMed +
   preprints). Optional: enrich the query with the plant's distinctive compounds.
3. **Filter** the retrieved pool down to papers actually relevant to the specific claim
   (a fast, cheap LLM screen).
4. **Judge** the claim on the filtered papers only, producing a verdict from a fixed
   schema: Strongly Agree / Agree / Neutral / Disagree / Strongly Disagree /
   Insufficient Evidence / No Modern Equivalent.

Every row is fully traced (all prompts, raw responses, the search query, papers found
and kept) to a fail-safe append-only JSONL for post-run analysis.

## Files

- `stage7_retrieve_judge.py` — the current pipeline (retrieve → filter → judge).
- `stage7_factcheck.py` — the earlier Vertex AI + Google Search grounding version.
- `build_distinctive_compounds.py` — builds per-plant distinctive-compound lists
  (LLM picks vs. quantitative species-count ranking) from Wikidata.
- `Stage7_FactCheck_CredibleSources.ipynb` — original Colab notebook.
- `data/` — input CSVs, result CSVs, JSONL traces, and experiment backups.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
gcloud auth application-default login          # one-time local ADC auth
cp ".env.example" .env                         # then edit .env with your values
export VERTEX_PROJECT_ID=... CONTACT_EMAIL=...  # or use the .env
```

## Run

`SAMPLE_MODE = True` in `stage7_retrieve_judge.py` processes a reproducible 300-row
sample. **Do not run the full ~7,362-row file without intent** — flip `SAMPLE_MODE`
to `False` only when you mean to.

```bash
python3 stage7_retrieve_judge.py
```

Experiment toggles are environment-controlled, e.g.:
`EXP_ENRICH=1 EXP_COMPOUND_SET=llm EXP_TAG=myrun python3 stage7_retrieve_judge.py`
