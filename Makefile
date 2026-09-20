# PYTHON_BIN picks the interpreter used to CREATE the venv (setup only).
# Git Bash on Windows usually has `python`, not `python3` - prefer python3
# when it exists, fall back to python otherwise.
PYTHON_BIN := $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

VENV := .venv
# PY/PIP point INTO the venv once it exists. A POSIX venv (Linux/macOS/WSL)
# lays out .venv/bin/; a venv made by a native Windows Python (even from Git
# Bash) lays out .venv/Scripts/ instead - detect whichever is actually there.
PY   := $(shell [ -x $(VENV)/bin/python ] && echo $(VENV)/bin/python || echo $(VENV)/Scripts/python.exe)
PIP  := $(shell [ -x $(VENV)/bin/pip ] && echo $(VENV)/bin/pip || echo $(VENV)/Scripts/pip.exe)
PORT ?= 8000

.PHONY: help setup run demo test lint scenarios snapshots snapshots-live hf-push clean

help:
	@echo "Prahari — dual-channel geohazard early warning"
	@echo ""
	@echo "  make setup      Create venv and install dependencies"
	@echo "  make run        Start the dashboard (live feeds, replay fallback)"
	@echo "  make demo       Start in guaranteed-offline replay mode  <- use on stage"
	@echo "  make test       Run the test suite"
	@echo "  make scenarios  Regenerate the scenario corpus"
	@echo "  make snapshots  Refresh the offline world-hazard snapshots"
	@echo "  make hf-push    Publish the incident corpus to the Hugging Face Hub"
	@echo ""

setup:
	$(PYTHON_BIN) -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "Ready. Now run: make run"

run:
	$(PY) -m uvicorn backend.main:app --host 0.0.0.0 --port $(PORT) --reload

demo:
	PRAHARI_SOURCE_MODE=replay $(PY) -m uvicorn backend.main:app --host 0.0.0.0 --port $(PORT)

test:
	$(PY) -m pytest tests/ -q

scenarios:
	$(PY) scripts/build_scenarios.py

snapshots:
	$(PY) scripts/build_snapshots.py

snapshots-live:
	$(PY) scripts/build_snapshots.py --live

hf-push:
	$(PY) scripts/push_to_hf.py

clean:
	rm -rf __pycache__ */__pycache__ */*/__pycache__ .pytest_cache prahari.db
