"""
Build distinctive-compound lists for each plant, two ways, and compare them
(per Dr. Taher): LLM picks (run once, saved) vs quantitative species-count ranking.

Output: data/distinctive_compounds.json
  { sci_name: { "full": [...], "counts": {compound: n_species},
                "quant": [...rarest few...], "llm": [...] } }

The LLM picks drive the enrichment re-run; the quant list is the benchmark.
"""
import json
import os
import time

import pandas as pd
import requests
from google.genai import types

import stage7_retrieve_judge as rj

DATA_DIR = rj.DATA_DIR
OUT = os.path.join(DATA_DIR, "distinctive_compounds.json")
WIKIDATA = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "TadhkiratDawoodFactCheck/1.0 (research)"}
N_KEEP = 5  # how many distinctive compounds to keep per plant
_FAST = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))


def wikidata_compounds_with_counts(sci):
    """Return {compound_name: n_species_it_is_found_in} for a plant (clean names only)."""
    q = ('SELECT ?cL (COUNT(DISTINCT ?t2) AS ?taxa) WHERE { '
         '?p wdt:P225 "%s". ?c wdt:P703 ?p. ?c rdfs:label ?cL. FILTER(LANG(?cL)="en"). '
         '?c wdt:P703 ?t2. } GROUP BY ?cL ORDER BY ?taxa' % sci)
    for attempt in range(3):
        try:
            r = requests.get(WIKIDATA, params={"query": q, "format": "json"}, headers=HEADERS, timeout=40)
            if r.status_code == 200:
                out = {}
                for b in r.json()["results"]["bindings"]:
                    name = b["cL"]["value"]
                    if rj._clean_compound(name):
                        out[name] = int(b["taxa"]["value"])
                return out
        except (requests.RequestException, KeyError, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    return {}


def llm_pick(sci, compounds):
    if not compounds:
        return []
    prompt = (
        "You are a pharmacognosy expert. Below are chemical compounds recorded as found in "
        f"the plant {sci}.\n\nSelect ONLY the compounds that are DISTINCTIVE or characteristic "
        "markers of this plant (or its genus/family) -- the specialized secondary metabolites "
        "that define its pharmacology. EXCLUDE ubiquitous primary metabolites found in most "
        "plants: common sterols (beta-sitosterol, stigmasterol, cholesterol, campesterol), "
        "common fatty acids (palmitic, stearic, oleic, linoleic, myristic, lauric), common "
        "sugars (sucrose, glucose), and generic terpenes (alpha-pinene, limonene, myrcene).\n\n"
        f"Compounds: {', '.join(compounds)}\n\n"
        "Respond with ONLY the distinctive compound names, comma-separated, most characteristic "
        "first, maximum 6. If none qualify, respond NONE.")
    resp = rj.llm_with_backoff(rj.client.models.generate_content, model=rj.NORMALIZE_MODEL,
                               contents=prompt, config=_FAST)
    text = (resp.text or "").strip()
    if text.upper().startswith("NONE"):
        return []
    picks = [t.strip() for t in text.split(",") if t.strip()]
    # keep only picks that were actually in the provided list (case-insensitive)
    low = {c.lower(): c for c in compounds}
    return [low[p.lower()] for p in picks if p.lower() in low][:6]


def main():
    A = pd.read_csv(os.path.join(DATA_DIR, "_exp_baseline_A_300.csv"))
    plants = sorted(A["scientific_name"].dropna().unique())
    result = {}
    for i, sci in enumerate(plants, 1):
        counts = wikidata_compounds_with_counts(sci)
        full = list(counts.keys())
        quant = sorted(full, key=lambda c: counts[c])[:N_KEEP]  # rarest = most distinctive
        llm = llm_pick(sci, full)
        result[sci] = {"full": full, "counts": counts, "quant": quant, "llm": llm}
        inter = set(quant) & set(llm)
        print(f"[{i}/{len(plants)}] {sci}: {len(full)} compounds | "
              f"quant={quant} | llm={llm} | overlap={sorted(inter)}")
        time.sleep(1.0)  # pace Wikidata
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(result)} plants to {OUT}")


if __name__ == "__main__":
    main()
