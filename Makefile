VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
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
	python3 -m venv $(VENV)
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
