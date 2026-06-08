import pandas as pd


# =====================================================
# FILE PATHS
# =====================================================

MASTER_FILE = "output/clustered_diseases_final.xlsx"

OVERRIDE_FILE = "output/humoral_reclustered.xlsx"

OUTPUT_FILE = "output/final_disease_ontology.xlsx"


# =====================================================
# LOAD FILES
# =====================================================

print("Loading files...")

master_df = pd.read_excel(MASTER_FILE)

override_df = pd.read_excel(OVERRIDE_FILE)

print(f"Master rows: {len(master_df)}")

print(f"Override rows: {len(override_df)}")


# =====================================================
# CLEAN MERGE KEY
# =====================================================

master_df["normalized_disease"] = (
    master_df["normalized_disease"]
    .astype(str)
    .str.strip()
    .str.lower()
)

override_df["normalized_disease"] = (
    override_df["normalized_disease"]
    .astype(str)
    .str.strip()
    .str.lower()
)


# =====================================================
# KEEP ONLY NEEDED COLUMNS
# =====================================================

override_df = override_df[
    [
        "normalized_disease",
        "cluster_label",
        "broader_category"
    ]
]


# =====================================================
# RENAME OVERRIDE COLUMNS
# =====================================================

override_df = override_df.rename(
    columns={
        "cluster_label": "new_cluster_label",
        "broader_category": "new_broader_category"
    }
)


# =====================================================
# MERGE
# =====================================================

merged_df = master_df.merge(
    override_df,
    on="normalized_disease",
    how="left"
)


# =====================================================
# COUNT UPDATES
# =====================================================

updated_rows = (
    merged_df["new_cluster_label"]
    .notna()
    .sum()
)

print(f"\nDiseases updated: {updated_rows}")


# =====================================================
# APPLY OVERRIDES
# =====================================================

merged_df["cluster_label"] = (
    merged_df["new_cluster_label"]
    .combine_first(
        merged_df["cluster_label"]
    )
)

merged_df["broader_category"] = (
    merged_df["new_broader_category"]
    .combine_first(
        merged_df["broader_category"]
    )
)


# =====================================================
# DROP TEMP COLUMNS
# =====================================================

merged_df = merged_df.drop(
    columns=[
        "new_cluster_label",
        "new_broader_category"
    ]
)


# =====================================================
# EXPORT
# =====================================================

merged_df.to_excel(
    OUTPUT_FILE,
    index=False
)

print("\nMerge completed successfully.")

print(f"Saved: {OUTPUT_FILE}")


# =====================================================
# SHOW SAMPLE UPDATED ROWS
# =====================================================

sample_updates = merged_df[
    merged_df["normalized_disease"].isin(
        override_df["normalized_disease"]
    )
].head(10)

print("\nSample updated rows:\n")

print(
    sample_updates[
        [
            "normalized_disease",
            "cluster_label",
            "broader_category"
        ]
    ]
)