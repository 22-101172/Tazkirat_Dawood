import pandas as pd
from pathlib import Path


# =========================================================
# FILE PATHS
# =========================================================

INPUT_FILE = "output/validation_input_clean.xlsx"

OUTPUT_FILE = "output/unique_diseases.xlsx"


# =========================================================
# CLEAN DISEASE TEXT
# =========================================================

def clean_disease_text(text):

    if pd.isna(text):
        return None

    text = str(text).strip()

    # remove repeated spaces
    text = " ".join(text.split())

    return text


# =========================================================
# EXTRACT UNIQUE DISEASES
# =========================================================

def extract_unique_diseases(df):

    disease_column = "disease_or_condition"

    # clean disease text
    df[disease_column] = (
        df[disease_column]
        .apply(clean_disease_text)
    )

    # remove empty diseases
    disease_df = df[
        df[disease_column].notna()
    ].copy()

    disease_df = disease_df[
        disease_df[disease_column] != ""
    ]

    # count frequencies
    frequency_df = (
        disease_df[disease_column]
        .value_counts()
        .reset_index()
    )

    frequency_df.columns = [
        "raw_disease",
        "frequency"
    ]

    # add future normalization columns
    frequency_df["normalized_disease"] = ""

    frequency_df["english_translation"] = ""

    frequency_df["cluster_id"] = ""

    frequency_df["broader_category"] = ""

    frequency_df["notes"] = ""

    return frequency_df


# =========================================================
# EXPORT OUTPUT
# =========================================================

def export_output(df):

    Path("output").mkdir(exist_ok=True)

    df.to_excel(
        OUTPUT_FILE,
        index=False
    )

    print("\nExport complete.")

    print(f"Saved file: {OUTPUT_FILE}")


# =========================================================
# MAIN
# =========================================================

def main():

    print("\n===================================")
    print("Stage 1 — Extract Unique Diseases")
    print("===================================\n")

    # load merged dataset
    df = pd.read_excel(INPUT_FILE)

    print(f"Loaded rows: {len(df)}")

    print("\nColumns found:")

    print(df.columns.tolist())

    # extract diseases
    unique_diseases_df = (
        extract_unique_diseases(df)
    )

    print(
        f"\nUnique diseases found: "
        f"{len(unique_diseases_df)}"
    )

    print("\nTop 10 most common diseases:\n")

    print(
        unique_diseases_df.head(10)
    )

    # export
    export_output(unique_diseases_df)

    print("\nStage 1 completed successfully.\n")


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()