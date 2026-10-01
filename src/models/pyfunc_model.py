"""MLflow pyfunc wrapper so the champion bundle is a first-class registered MLflow model."""
from __future__ import annotations

import joblib
import pandas as pd

import mlflow.pyfunc


class VoltGuardPyfunc(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        self.bundle = joblib.load(context.artifacts["bundle"])

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        b = self.bundle
        X = b["preprocessor"].transform(model_input[b["features"]])
        out = {"predicted_soh": b["models"]["soh"].predict(X)}
        if "rul" in b["models"]:
            out["predicted_rul"] = b["models"]["rul"].predict(X)
        return pd.DataFrame(out)
