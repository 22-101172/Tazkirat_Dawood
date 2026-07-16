"""One-off diagnostic: for a few rows, show what the model + grounding ACTUALLY
return on both passes, before factcheck_row's logic forces a verdict."""
from stage7_factcheck import (client, MODEL, build_prompt, extract_grounding_urls,
                               is_credible_source, KNOWN_LOW_QUALITY_DOMAINS)
from google.genai import types
from urllib.parse import urlparse

CASES = [
    ("أرجوان", "Cercis siliquastrum", "Coldness of the stomach, kidneys, and liver", "As the plant is generally used", "Beneficial for the coldness of these organs"),
    ("ريحان", "Ocimum basilicum", "Corruption of bodily humors (chymes)", "As the plant is generally used", "Corrects them"),
    ("خزامى", "Lavandula stoechas", "Distress and nausea", "Corrected by taking Sekanjabin", "Relieves it"),
]

def run_pass(arabic, sci, dis, tx, eff, strict, exclude):
    tool = types.Tool(google_search=types.GoogleSearch(exclude_domains=exclude))
    cfg = types.GenerateContentConfig(tools=[tool])
    p = build_prompt(arabic, sci, dis, tx, eff, strict=strict)
    resp = client.models.generate_content(model=MODEL, contents=p, config=cfg)
    srcs = extract_grounding_urls(resp) if resp.text is not None else []
    return resp, srcs

for arabic, sci, dis, tx, eff in CASES:
    print("=" * 80)
    print(f"{sci} | {dis}")
    # pass 1
    resp, srcs = run_pass(arabic, sci, dis, tx, eff, False, KNOWN_LOW_QUALITY_DOMAINS)
    print(f"  PASS1 finish={resp.candidates[0].finish_reason} text_is_none={resp.text is None} n_sources={len(srcs)}")
    print(f"        model_text(first 240): {(resp.text or '')[:240]!r}")
    for s in srcs:
        print(f"        src: {s['domain_hint']:20s} {s['url'][:80]}  credible={is_credible_source(s)}")
    # pass 2
    retry_exclude = list(set(KNOWN_LOW_QUALITY_DOMAINS) | {urlparse(s['url']).netloc for s in srcs if s['url']})
    resp2, srcs2 = run_pass(arabic, sci, dis, tx, eff, True, retry_exclude)
    print(f"  PASS2 finish={resp2.candidates[0].finish_reason} text_is_none={resp2.text is None} n_sources={len(srcs2)}")
    print(f"        model_text(first 240): {(resp2.text or '')[:240]!r}")
    for s in srcs2:
        print(f"        src: {s['domain_hint']:20s} {s['url'][:80]}  credible={is_credible_source(s)}")
    print()
