PY ?= python
.PHONY: install data lint test smoke repro api mlflow-ui docker-build docker-up clean

install:        ## create env + install everything
	$(PY) -m pip install -r requirements-dev.txt
data:           ## download NASA dataset into data/raw (see data/README.md if it fails)
	$(PY) scripts/download_data.py
lint:
	ruff check .
test:
	pytest -q
smoke:          ## whole pipeline on SYNTHETIC data in a temp dir (no real data needed)
	$(PY) scripts/smoke_test.py
repro:          ## reproduce the DVC pipeline on real data
	dvc repro
	$(PY) scripts/quality_gate.py
api:            ## run API locally using artifacts/models
	MODEL_SOURCE=local uvicorn api.main:app --reload --port 8000
mlflow-ui:
	mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db --port 5000
docker-build:
	docker build -t voltguard-api:local .
docker-up:
	docker compose up --build
clean:
	rm -rf .pytest_cache .ruff_cache mlruns
