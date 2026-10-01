import json

import mlflow
from mlflow.tracking import MlflowClient
from src.pipeline.stages import STAGES, main
from src.utils.config import resolve


def test_all_stage_outputs_exist(pipeline_run):
    cfg, _ = pipeline_run
    p, m = resolve(cfg["paths"]["processed_dir"]), resolve(cfg["paths"]["models_dir"])
    for f in (p / "train.csv", p / "val.csv", p / "test.csv", m / "voltguard_bundle.joblib", m / "manifest.json",
              resolve(cfg["paths"]["preprocessors_dir"]) / "preprocessor.joblib",
              resolve(cfg["paths"]["metrics_dir"]) / "evaluation.json"):
        assert f.exists(), f


def test_registry_aliases_and_manifest(pipeline_run):
    cfg, out = pipeline_run
    mlflow.set_tracking_uri(cfg["mlflow"]["tracking_uri"])
    name = cfg["registry"]["model_name"]
    client = MlflowClient()
    assert str(client.get_model_version_by_alias(name, "candidate").version) == "1"
    assert str(client.get_model_version_by_alias(name, "champion").version) == "1"
    man = json.loads((resolve(cfg["paths"]["models_dir"]) / "manifest.json").read_text())
    assert man["model_name"] == name and "champion" in man["aliases"] and len(man["bundle_sha256"]) == 64


def test_registered_model_loads_from_registry(pipeline_run, sample_payload):
    import pandas as pd
    cfg, _ = pipeline_run
    mlflow.set_tracking_uri(cfg["mlflow"]["tracking_uri"])
    model = mlflow.pyfunc.load_model(f"models:/{cfg['registry']['model_name']}@champion")
    pred = model.predict(pd.DataFrame([sample_payload]))
    assert {"predicted_soh", "predicted_rul"} <= set(pred.columns)


def test_worse_candidate_is_not_promoted(pipeline_run):
    """Re-register the same bundle with a required improvement -> stays candidate only."""
    from src.models.registry import run_register
    cfg, _ = pipeline_run
    cfg = {**cfg, "registry": {**cfg["registry"], "min_relative_improvement": 0.5}}
    man = run_register(cfg)
    assert man["model_version"] == "2" and man["aliases"] == ["candidate"] and man["promoted"] is False
    assert str(MlflowClient().get_model_version_by_alias(cfg["registry"]["model_name"], "champion").version) == "1"


def test_stage_cli_rejects_unknown_stage():
    assert main(["nope"]) == 2 and set(STAGES) == {"data_ingestion", "preprocess", "train", "evaluate", "register_model"}
