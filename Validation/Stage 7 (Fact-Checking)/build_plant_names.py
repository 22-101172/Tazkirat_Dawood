"""
Build a validated literature-name set for each plant (per Dr. Taher: "having the
right name is crucial"). Every retrieval query is anchored on the plant name, so a
plant studied under a synonym our exact name misses is invisible to the pipeline.

Approach (precise, not "add all synonyms"):
  candidates = accepted scientific name + GBIF synonyms + LLM-known literature
               synonyms + our other_known_names
  keep only candidates that actually RETURN papers (Europe PMC hitCount >= MIN_HITS)
  -> the names the modern literature really uses. Built once, saved.

Output: data/plant_names.json = { sci_name: {"names":[...], "hits":{name:count}} }
"""
import json
import os
import time

import pandas as pd
import requests
from google.genai import types

import stage7_retrieve_judge as rj

DATA_DIR = rj.DATA_DIR
OUT = os.path.join(DATA_DIR, "plant_names.json")
GBIF = "https://api.gbif.org/v1"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
HEADERS = {"User-Agent": "TadhkiratDawoodFactCheck/1.0 (research)"}
MIN_HITS = 30      # a name must return at least this many papers to count as "used in the literature"
MAX_NAMES = 4      # cap the OR-set so queries stay clean
_FAST = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))


def gbif_synonyms(name):
    try:
        m = requests.get(f"{GBIF}/species/match", params={"name": name}, headers=HEADERS, timeout=20).json()
        key = m.get("usageKey")
        if not key:
            return []
        syn = requests.get(f"{GBIF}/species/{key}/synonyms", params={"limit": 50}, headers=HEADERS, timeout=20).json()
        return [s["canonicalName"] for s in syn.get("results", []) if s.get("canonicalName")]
    except (requests.RequestException, KeyError, ValueError):
        return []


def gbif_accepted(name):
    """Accepted species name GBIF resolves this name to (synonyms point to their accepted sp.)."""
    try:
        m = requests.get(f"{GBIF}/species/match", params={"name": name}, headers=HEADERS, timeout=20).json()
        return (m.get("species") or m.get("canonicalName") or "").strip()
    except (requests.RequestException, KeyError, ValueError):
        return ""


def llm_literature_names(sci_name, common):
    prompt = (
        f"Plant: {sci_name}" + (f" (common name: {common})" if common else "") + ".\n"
        "List the scientific binomial names under which THIS plant is published in modern "
        "biomedical/pharmacological literature (PubMed) — the current accepted name plus any "
        "widely-used synonym names. Real botanical binomials only, no common names, no author "
        "citations. Comma-separated, max 4.")
    resp = rj.llm_with_backoff(rj.client.models.generate_content, model=rj.NORMALIZE_MODEL,
                               contents=prompt, config=_FAST)
    return [n.strip() for n in (resp.text or "").split(",") if n.strip()]


def epmc_hits(name):
    try:
        r = requests.get(EPMC, params={"query": f'"{name}"', "format": "json", "pageSize": 1},
                         headers=HEADERS, timeout=20)
        return int(r.json().get("hitCount", 0))
    except (requests.RequestException, KeyError, ValueError):
        return -1


def build_name_set(sci_name, common):
    plant_accepted = gbif_accepted(sci_name) or sci_name
    cands, seen = [], set()
    for n in [sci_name] + gbif_synonyms(sci_name) + llm_literature_names(sci_name, common):
        n = (n or "").strip()
        # keep binomials only (Genus species); skip genus-only ("Pinus spp.") and junk ("? violaceum")
        if (n and n.lower() not in seen and len(n.split()) >= 2 and "spp" not in n.lower()
                and "?" not in n and n[0].isupper()):
            seen.add(n.lower())
            cands.append(n)
    hits, verified = {}, {}
    for n in cands:
        if n == sci_name:
            continue
        # PRECISION GATE: keep only names GBIF resolves to the SAME accepted species
        acc = gbif_accepted(n)
        time.sleep(0.2)
        if acc and acc == plant_accepted:
            hits[n] = epmc_hits(n)
            time.sleep(0.2)
            if hits[n] >= MIN_HITS:
                verified[n] = hits[n]
    # always keep the accepted name; add verified true-synonyms, best-first
    kept = [sci_name] + sorted(verified, key=lambda n: -verified[n])
    return kept[:MAX_NAMES], hits


def main():
    A = pd.read_csv(os.path.join(DATA_DIR, "_exp_baseline_A_300.csv"))
    ident = pd.read_csv(os.path.join(DATA_DIR, "plant_identification_v2.csv"))
    common_map = dict(zip(ident["entry_id"], ident.get("common_english_name", pd.Series(dtype=str))))
    sci_common = {}
    for _, r in A.iterrows():
        sci = r["scientific_name"]
        if pd.notna(sci) and sci not in sci_common:
            c = common_map.get(r["entry_id"], "")
            sci_common[sci] = "" if pd.isna(c) else str(c)

    result = {}
    for i, (sci, common) in enumerate(sorted(sci_common.items()), 1):
        names, hits = build_name_set(sci, common)
        result[sci] = {"names": names, "hits": hits}
        extra = [n for n in names if n != sci]
        tag = f"+{len(extra)} synonym(s): {extra}" if extra else "(single name)"
        print(f"[{i}/{len(sci_common)}] {sci}: {tag}")
        time.sleep(0.4)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    multi = sum(1 for v in result.values() if len(v["names"]) > 1)
    print(f"\nSaved {len(result)} plants to {OUT}. {multi} gained extra literature names.")


if __name__ == "__main__":
    main()
