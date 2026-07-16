import re
from pathlib import Path

import openpyxl  # noqa: F401 - ensures the Excel writer engine is available
import pandas as pd


# =========================================================
# FILE PATHS
# =========================================================

INPUT_FILE = "data/disease_treatment_english_v1.csv"

OUTPUT_FILE = "output/disease_clusters.xlsx"


# =========================================================
# COLUMN NAMES
# =========================================================

RAW_DISEASE_COLUMN = "disease_or_condition"

ENGLISH_DISEASE_COLUMN = "disease_or_condition_en"


# =========================================================
# CLEAN DISEASE TEXT
# =========================================================

def clean_disease_text(text):
    """Normalize disease text for duplicate detection and future clustering."""

    if pd.isna(text):
        return ""

    text = str(text).lower().strip()

    # Collapse repeated whitespace into a single space.
    text = re.sub(r"\s+", " ", text)

    return text


def clean_display_text(text):
    """Clean text for display while preserving the original casing."""

    if pd.isna(text):
        return ""

    text = str(text).strip()

    # Collapse repeated whitespace into a single space.
    text = re.sub(r"\s+", " ", text)

    return text


# =========================================================
# LOAD DATA
# =========================================================

def load_data(input_file):
    """Load the translated disease-treatment claims file."""

    print("Loading translated disease-treatment data...")

    df = pd.read_csv(input_file)

    print(f"Loaded claims: {len(df)}")
    print(f"Columns found: {df.columns.tolist()}")

    return df


def validate_columns(df):
    """Ensure the required disease columns exist before processing."""

    required_columns = [
        RAW_DISEASE_COLUMN,
        ENGLISH_DISEASE_COLUMN,
    ]

    missing_columns = [
        column for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing_columns)
        )


# =========================================================
# BUILD CLUSTERING WORKSPACE
# =========================================================

def build_disease_clusters(df):
    """Create one clustering workspace row per unique English disease."""

    working_df = df[
        [
            RAW_DISEASE_COLUMN,
            ENGLISH_DISEASE_COLUMN,
        ]
    ].copy()

    working_df["raw_disease_ar_clean"] = (
        working_df[RAW_DISEASE_COLUMN]
        .apply(clean_display_text)
    )

    working_df["disease_en_clean"] = (
        working_df[ENGLISH_DISEASE_COLUMN]
        .apply(clean_display_text)
    )

    working_df["normalized_disease"] = (
        working_df[ENGLISH_DISEASE_COLUMN]
        .apply(clean_disease_text)
    )

    # Keep only rows with usable English disease expressions.
    working_df = working_df[
        working_df["normalized_disease"] != ""
    ].copy()

    print(
        "Claims with usable English disease expressions: "
        f"{len(working_df)}"
    )

    frequency_df = (
        working_df["normalized_disease"]
        .value_counts()
        .rename_axis("normalized_disease")
        .reset_index(name="frequency")
    )

    display_df = (
        working_df
        .groupby("normalized_disease", as_index=False)
        .agg(
            disease_en=("disease_en_clean", first_non_empty),
            raw_disease_ar=("raw_disease_ar_clean", join_unique_values),
        )
    )

    cluster_df = display_df.merge(
        frequency_df,
        on="normalized_disease",
        how="left",
    )

    # Empty fields are intentionally prepared for future semantic clustering.
    cluster_df["cluster_id"] = ""
    cluster_df["broader_category"] = ""
    cluster_df["cluster_label"] = ""
    cluster_df["notes"] = ""

    cluster_df = cluster_df[
        [
            "raw_disease_ar",
            "disease_en",
            "normalized_disease",
            "frequency",
            "cluster_id",
            "broader_category",
            "cluster_label",
            "notes",
        ]
    ].sort_values(
        by=["frequency", "normalized_disease"],
        ascending=[False, True],
    )

    return cluster_df.reset_index(drop=True)


def first_non_empty(values):
    """Return the first non-empty value from a pandas Series."""

    for value in values:
        if value:
            return value

    return ""


def join_unique_values(values):
    """Join unique non-empty values in their first-seen order."""

    unique_values = []
    seen_values = set()

    for value in values:
        if not value or value in seen_values:
            continue

        unique_values.append(value)
        seen_values.add(value)

    return "; ".join(unique_values)


# =========================================================
# SUMMARY STATISTICS
# =========================================================

def build_summary_stats(total_claims, cluster_df):
    """Create summary statistic tables for the Excel workbook."""

    unique_diseases = len(cluster_df)

    summary_df = pd.DataFrame(
        [
            {
                "metric": "total claims",
                "value": total_claims,
            },
            {
                "metric": "unique diseases",
                "value": unique_diseases,
            },
        ]
    )

    top_20_df = cluster_df[
        [
            "disease_en",
            "normalized_disease",
            "frequency",
            "raw_disease_ar",
        ]
    ].head(20)

    return summary_df, top_20_df


# =========================================================
# EXPORT OUTPUT
# =========================================================

def export_output(cluster_df, summary_df, top_20_df, output_file):
    """Export the disease clustering workspace and summary sheets."""

    Path(output_file).parent.mkdir(exist_ok=True)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        cluster_df.to_excel(
            writer,
            sheet_name="disease_clusters",
            index=False,
        )

        summary_df.to_excel(
            writer,
            sheet_name="summary",
            index=False,
        )

        top_20_df.to_excel(
            writer,
            sheet_name="top_20_frequent",
            index=False,
        )

    print("\nExport complete.")
    print(f"Saved file: {output_file}")


# =========================================================
# MAIN
# =========================================================

def main():
    print("\n===================================")
    print("Stage 2 - Disease Clustering Prep")
    print("===================================\n")

    df = load_data(INPUT_FILE)

    validate_columns(df)

    cluster_df = build_disease_clusters(df)

    summary_df, top_20_df = build_summary_stats(
        total_claims=len(df),
        cluster_df=cluster_df,
    )

    print(f"\nUnique diseases found: {len(cluster_df)}")

    print("\nTop 20 most frequent diseases:\n")
    print(top_20_df.to_string(index=False))

    export_output(
        cluster_df=cluster_df,
        summary_df=summary_df,
        top_20_df=top_20_df,
        output_file=OUTPUT_FILE,
    )

    print("\nStage 2 completed successfully.")
    print("No AI clustering or PubMed search was performed.\n")


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
