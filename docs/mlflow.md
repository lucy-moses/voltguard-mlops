# MLflow

## Setup

Default backend: SQLite (`mlflow/mlflow.db`) + local artifact folder - needed because the Model Registry requires a database backend. To share results across machines/CI, run a tracking server and export `MLFLOW_TRACKING_URI=http://host:5000` (and add it as the optional `MLFLOW_TRACKING_URI` secret for CI).

```bash
mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db --port 5000
```

## What is tracked

Experiment `voltguard-battery`; one run per **(target, model)** = 10 runs by default (5 models x SOH/RUL):

* params: hyper-parameters, seed, n_features
* metrics: `train_*`, `val_{rmse,mae,r2}`, `training_time_s`; the selected run also gets `test_*` (logged once, after selection)
* artifacts: candidate model file, `feature_importance.json` (tree importances or |standardised coefficients|)
* tags: `target`, `model_type`, `stage=experiment`

## Model selection rule (`params.yaml: selection`)

1. Per target, on the **validation** split, the lowest **RMSE** wins.
2. Models within `tie_tolerance` (1 %) of the best RMSE are tied -> lowest **MAE**, then highest **R2**, then name (deterministic).
3. The winner is scored on the **test** split exactly once - test data never influences selection.

## Registry

Registered model `VoltGuard-Battery-RUL` (a pyfunc that returns both SOH and RUL; `src/models/pyfunc_model.py`).

| Alias | Meaning |
|---|---|
| `candidate` | newest registered version (always moved) |
| `champion` | version that serves production. Moved to a new version **only if** `soh_test_rmse` improves on the current champion by `min_relative_improvement` (or no champion exists) |

```python
import mlflow
mlflow.set_tracking_uri("sqlite:///mlflow/mlflow.db")
m = mlflow.pyfunc.load_model("models:/VoltGuard-Battery-RUL@champion")
```

Deployment does **not** query MLflow: it loads the DVC-versioned bundle described by `manifest.json`, which records the registry name, version, run ID and aliases. The API refuses to serve if `MODEL_ALIAS` (default `champion`) is not in the manifest, so a non-promoted candidate cannot silently go live.

**Known limitation:** in CI the tracking DB is created fresh on each runner unless `MLFLOW_TRACKING_URI` points at a persistent server; then version numbers restart at 1 and the champion comparison has no history. Use a remote server for real champion/challenger governance.
