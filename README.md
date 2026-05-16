# Validation Pipeline

A collaborative Python project for validating historical herbal medicine claims.

## Project Overview

This pipeline processes and validates herbal medicine data, ensuring accuracy and consistency in herb identity and nomenclature.

## Stages

### Stage 0: Herb Linking & Normalization

Handles herb identity normalization and scientific name cleaning. Links herbal references to a standardized authority table.

## Getting Started

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Project Structure

- `data/` — Input data files
- `output/` — Generated output files
- `stages/` — Pipeline stage implementations
- `tests/` — Test suite
- `utils/` — Utility functions and helpers