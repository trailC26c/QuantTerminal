# QuanTerminal

QuanTerminal is a modular Python toolkit for macro‑market analysis, data processing, and interactive visualization.  
This repository contains the core scripts, pipeline logic, and utilities used to generate barometer charts, rolling indicators, and other analytical outputs.

---

## Features

- Modular script architecture (`scripts/`)
- Clean project structure with virtual environment support
- Plotly‑based interactive charts
- Batch‑driven pipeline execution
- Archive folder for legacy or experimental versions
- Git‑tagged stable releases

---

## Project Structure

QuantTerminal/
│
├── scripts/
│   ├── main.py
│   ├── macro_barometer.py
│   ├── processor.py
│   └── archive/        # older versions, ignored by Git
│
├── data/               # input data (ignored by Git)
├── output/             # generated charts & results (ignored by Git)
├── .venv/              # virtual environment
├── .gitignore
└── README.md

---

## Setup

### 1. Create and activate virtual environment
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
python scripts/main.py
scripts/run_pipeline.bat



git checkout master
git merge dev
git push
git tag v0.2
git push origin v0.2

## commit

git status
git diff --check
git add scripts/macro_barometer.py
git diff --cached
git commit -m "Align OBV extrema signals with TOS behavior"
git tag -a v.12 -m "Release v.12"
git push origin dev
git push origin v.12
git status

git add scripts/macro_barometer.py requirements.txt

git status
git add README.md
git commit -m "Document project workflow"
git push origin dev

git log -3 --oneline
git status
