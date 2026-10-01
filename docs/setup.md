# Local setup

Tested in a Linux sandbox with Python 3.12 (the project targets 3.11, which CI and Docker use).

```bash
git clone <your-repo-url> voltguard-mlops && cd voltguard-mlops
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt          # or: make install
```

## Verify the toolchain WITHOUT real data (synthetic, for testing only)

```bash
pytest -q                     # 35 tests
ruff check .
python scripts/smoke_test.py  # whole pipeline on synthetic data in a temp dir
```

Synthetic data lives only in `tests/synthetic.py`. Its results are meaningless and must never appear in your report.

## Real data + pipeline

```bash
python scripts/download_data.py            # or place files manually (data/README.md)
dvc add data/raw                           # version the dataset
git add data/raw.dvc data/.gitignore && git commit -m "Track raw data"
dvc repro                                  # ingest -> preprocess -> train -> evaluate -> register
python scripts/quality_gate.py
mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db --port 5000   # http://localhost:5000
git add dvc.lock artifacts/metrics && git commit -m "Pipeline run"
```

`dvc.lock` is **generated** by the first `dvc repro` (it records hashes of every dep/out). It cannot be pre-written, and it must be committed: the Docker image and CD pipeline rely on it.

## Run the API locally

```bash
MODEL_SOURCE=local uvicorn api.main:app --port 8000     # uses artifacts/models/
curl localhost:8000/health
```

Open <http://localhost:8000/docs> for interactive docs.
