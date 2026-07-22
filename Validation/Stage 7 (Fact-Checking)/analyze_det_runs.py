"""Compare the deterministic 300-sample runs: base_det vs names_det vs enr_det.

Reports the aggregate verdict distribution per config, row-level churn vs baseline
(now that temperature=0, this is real signal, not noise), and retrieval stats.
"""
import os
import sys

import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

CONFIGS = {
    "baseline": "factcheck_retrieve_judge_v1_base_det.csv",
    "names": "factcheck_retrieve_judge_v1_names_det.csv",
    "enriched": "factcheck_retrieve_judge_v1_enr_det.csv",
}

VERDICT_ORDER = [
    "Strongly Agree", "Agree", "Neutral", "Disagree", "Strongly Disagree",
    "No Modern Equivalent", "Insufficient Evidence", "PARSE_ERROR", "ERROR",
]

KEY = ["entry_id", "disease_or_condition_en"]


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def dist(df):
    n = len(df)
    vc = df["verdict"].value_counts()
    return {v: 100.0 * vc.get(v, 0) / n for v in VERDICT_ORDER}, n


def main():
    dfs = {k: load(v) for k, v in CONFIGS.items()}
    present = {k: v for k, v in dfs.items() if v is not None}
    if not present:
        sys.exit("No result CSVs yet.")

    print("=== Row counts ===")
    for k, v in present.items():
        print(f"  {k:10s}: {len(v)} rows")

    print("\n=== Aggregate verdict distribution (%) ===")
    header = f"{'Verdict':<22}" + "".join(f"{k:>12}" for k in present)
    print(header)
    dists = {k: dist(v)[0] for k, v in present.items()}
    for verdict in VERDICT_ORDER:
        vals = [dists[k].get(verdict, 0.0) for k in present]
        if all(x == 0.0 for x in vals):
            continue
        row = f"{verdict:<22}" + "".join(f"{dists[k].get(verdict,0.0):>11.1f}" for k in present)
        print(row)

    # Row-level churn vs baseline (only over rows present in BOTH, matched by key)
    if "baseline" in present:
        base = present["baseline"].set_index(KEY)["verdict"]
        print("\n=== Row-level change vs baseline (matched rows) ===")
        for k in present:
            if k == "baseline":
                continue
            other = present[k].set_index(KEY)["verdict"]
            common = base.index.intersection(other.index)
            b = base.loc[common]
            o = other.loc[common]
            changed = (b.values != o.values).sum()
            print(f"  {k:10s}: {changed}/{len(common)} rows changed "
                  f"({100.0*changed/len(common):.1f}%)")

    # Retrieval stats
    print("\n=== Retrieval (mean papers) ===")
    for k, v in present.items():
        ret = v["n_papers_retrieved"].mean() if "n_papers_retrieved" in v else float("nan")
        filt = v["n_papers_after_filter"].mean() if "n_papers_after_filter" in v else float("nan")
        hits = v["db_total_hits"].mean() if "db_total_hits" in v else float("nan")
        print(f"  {k:10s}: retrieved={ret:.2f}  after_filter={filt:.2f}  db_total_hits={hits:.1f}")


if __name__ == "__main__":
    main()
