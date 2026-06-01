# Tazkirat Dawood Validation Pipeline

This repository contains a reproducible validation workflow for historical herbal medicine claims from **Tazkirat Dawood**. The project links plant-identification data with disease-treatment claims, normalizes disease terminology, builds disease clusters, and prepares evidence tables for LLM-assisted biomedical scoring.

The goal is to make the validation process transparent: every intermediate dataset is preserved, the main processing stages are scripted, and the two research notebooks document the semantic clustering and LLM adjudication steps.

## Research Workflow

| Stage | File | Purpose | Main output |
| --- | --- | --- | --- |
| 0 | `stages/stage0_merge_and_filter.py` | Merge disease-treatment claims with plant identification data and remove rows marked for human review. | `output/validation_input_clean.xlsx` |
| 1 | `stages/stage1_extract_unique_diseases.py` | Extract and count unique disease expressions from the cleaned validation input. | `output/unique_diseases.xlsx` |
| 2 | `stages/stage2_cluster_diseases.py` | Build an English disease-clustering workspace with frequencies and summary sheets. | `output/disease_clusters.xlsx` |
| 3 | `notebooks/03_book_clustering.ipynb` | Use notebook-based clustering and correction to refine disease groupings. | `output/clustered_diseases_final.xlsx` |
| 4 | `stages/stage4_merge_corrected_clusters.py` | Merge manual/humoral cluster corrections into the master ontology. | `output/final_disease_ontology.xlsx` |
| 5 | `notebooks/05_llm_evidence_adjudication_vertexai.ipynb` | Score claim-paper evidence pairs with Vertex AI/Gemini and aggregate paper-level and claim-level judgments. | `output/evidence_table_500.xlsx` |

## Repository Structure

```text
.
├── data/                 # Source CSV/XLSX inputs
├── notebooks/            # Research notebooks for clustering and LLM scoring
├── output/               # Generated validation, clustering, ontology, and evidence files
├── stages/               # Reproducible Python pipeline stages
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation
```

## Data Files

The `data/` directory contains the primary project inputs:

- `disease_treatment_v1.csv`: original disease-treatment claim extraction.
- `disease_treatment_english_v1.csv`: translated disease-treatment claims used for English disease normalization.
- `plant_identification_v1.csv`: plant identification table used for linking claims to standardized plant information.
- `plant_identification_v1.xlsx`: spreadsheet version of the plant identification table.

## Generated Outputs

The `output/` directory contains preserved intermediate and final artifacts:

- `validation_input_clean.xlsx`: merged validation input after filtering.
- `unique_diseases.xlsx`: frequency table of unique disease expressions.
- `disease_clusters.xlsx`: disease clustering workspace and summary sheets.
- `clustered_diseases_final.xlsx`: refined disease clusters.
- `humoral_reclustered.xlsx`: curated humoral correction table.
- `final_disease_ontology.xlsx`: final normalized disease ontology.
- `claims_reference_500.xlsx`: claim/reference sample for evidence validation.
- `evidence_table_500.xlsx`: LLM-assisted evidence scoring table.

## Setup

Create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the Scripted Pipeline

Run the reproducible Python stages from the repository root:

```bash
python stages/stage0_merge_and_filter.py
python stages/stage1_extract_unique_diseases.py
python stages/stage2_cluster_diseases.py
python stages/stage4_merge_corrected_clusters.py
```

The notebooks are intentionally kept separate because they contain exploratory research steps and Vertex AI configuration:

- Open `notebooks/03_book_clustering.ipynb` for the disease clustering workflow.
- Open `notebooks/05_llm_evidence_adjudication_vertexai.ipynb` for LLM-based evidence adjudication.

## LLM Evidence Adjudication

Stage 5 uses Google Vertex AI/Gemini to evaluate biomedical evidence for extracted historical claims. The notebook is organized into upload, dependency installation, authentication, pair construction, scoring, export, and aggregation sections. To run it, configure the appropriate Google Cloud project and authentication inside the notebook environment before executing the scoring cells.

## Project Notes

- The pipeline separates deterministic preprocessing scripts from notebook-based research stages.
- Excel outputs are committed so reviewers can inspect intermediate decisions without rerunning external services.
- Disease normalization preserves original Arabic disease expressions alongside English normalized labels where available.
- Manual correction files are kept visible to make ontology changes auditable.

## Suggested Citation

If referencing this repository in a report or presentation, cite it as a validation pipeline for historical herbal medicine claim extraction, disease normalization, clustering, and LLM-assisted evidence adjudication for *Tazkirat Dawood*.
