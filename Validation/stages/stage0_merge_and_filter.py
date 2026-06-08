# this file should 
#1. Load both CSV files
#2. Remove human verification rows
#3. Merge datasets
#4. Export clean validation input

import pandas as pd
from pathlib import Path


# =========================================================
# FILE PATHS
# =========================================================

DISEASE_FILE = "data/disease_treatment_v1.csv"

PLANT_FILE = "data/plant_identification_v1.csv"

OUTPUT_FILE = "output/validation_input_clean.xlsx"


# =========================================================
# LOAD DATA
# =========================================================

def load_data():

    print("Loading datasets...")

    disease_df = pd.read_csv(DISEASE_FILE)

    plant_df = pd.read_csv(PLANT_FILE)

    print(f"Disease rows: {len(disease_df)}")

    print(f"Plant rows: {len(plant_df)}")

    return disease_df, plant_df


# =========================================================
# FILTER HUMAN VERIFICATION
# =========================================================

def filter_human_verification(plant_df):

    print("\nFiltering rows requiring human verification...")

    # adjust column name if needed
    verification_column = "needs_human_review"

    # keep only rows NOT marked Yes
    filtered_df = plant_df[
        plant_df[verification_column]
        .astype(str)
        .str.lower()
        != "yes"
    ]

    removed_rows = len(plant_df) - len(filtered_df)

    print(f"Removed rows: {removed_rows}")

    print(f"Remaining rows: {len(filtered_df)}")

    return filtered_df


# =========================================================
# MERGE DATASETS
# =========================================================

def merge_datasets(disease_df, plant_df):

    print("\nMerging datasets...")

    merged_df = disease_df.merge(
        plant_df,
        on="entry_id",
        how="left"
    )

    print(f"Merged rows: {len(merged_df)}")

    return merged_df


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
    print("Stage 0 — Merge and Filter")
    print("===================================\n")

    disease_df, plant_df = load_data()

    print("\nPlant file columns:")

    print(plant_df.columns.tolist())

    plant_df = filter_human_verification(
        plant_df
    )

    merged_df = merge_datasets(
        disease_df,
        plant_df
    )

    export_output(merged_df)

    print("\nStage 0 completed successfully.\n")


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()