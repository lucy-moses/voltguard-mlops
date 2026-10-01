# Viva questions and answers (VoltGuard)

## Project and ML

**1. What problem does VoltGuard solve?** It predicts a lithium-ion cell's State of Health (SOH, % of nominal capacity) and Remaining Useful Life (RUL, cycles until SOH <= 70 %) from per-cycle measurements, and serves the prediction through an API - with the full MLOps lifecycle around it.

**2. Which dataset and why?** NASA PCoE Li-ion aging data (cells B0005/6/7/18): public, widely cited, contains voltage/current/temperature/time per cycle and measured capacity, so both labels can be derived honestly.

**3. How are SOH and RUL defined?** SOH = capacity / 2.0 Ah x 100. RUL = EOL cycle - current cycle, where EOL is the first cycle with SOH <= 70 %. Cells that never reach EOL get no RUL label (censored) rather than an invented one.

**4. What is data leakage and how did you prevent it?** Leakage is information in training that would not exist at prediction time (or that reveals the target). I exclude `capacity`/SOH/RUL from features, use only same-cycle signals, fit scaler/imputer on train only, and split **by battery** so no cell is in two splits. A test asserts forbidden columns are not features.

**5. Why split by battery and not randomly by row?** Neighbouring cycles of one cell are almost identical, so a random split would put near-duplicates in train and test and inflate scores. Battery-wise splitting measures generalisation to an unseen cell.

**6. Any remaining leakage-like concern?** `discharge_duration` is a near-proxy of capacity under constant-current discharge (documented in `docs/features.md`). It is legitimate at inference (measured in the same cycle) but makes SOH easier; RUL is the more meaningful task.

**7. Which models did you compare and why?** Linear/Ridge (baselines), Random Forest, sklearn Gradient Boosting, XGBoost (non-linear, tabular strong). Baselines show whether complexity actually helps.

**8. How is the best model chosen?** Deterministic rule in `params.yaml`: lowest validation RMSE; models within 1 % are tied and broken by lowest MAE then highest R2. The winner is evaluated once on the test set.

**9. Why RMSE as primary?** It is in the target's units and penalises large errors - important for RUL where big misses are costly. MAE and R2 add robustness/interpretability.

**10. Why validation for selection and test for reporting?** Selecting on test would leak test information into the choice and make the reported score optimistic.

## DVC / Git / reproducibility

**11. What is DVC and why not just Git?** DVC versions large data/model files by content hash in remote storage, keeping tiny pointer files in Git. Git handles code but not GB-sized binaries.

**12. What is in `dvc.yaml` vs `dvc.lock`?** `dvc.yaml` declares stages (cmd, deps, params, outs). `dvc.lock` records the exact hashes of deps/outs from the last run - it is the reproducibility receipt and is committed.

**13. What does `dvc repro` do?** Walks the DAG, re-runs only stages whose deps, params or commands changed, and updates `dvc.lock`.

**14. How do you reproduce an old result?** `git checkout <commit>`, `dvc pull`, `dvc repro`. Seeds are fixed (`params.yaml: seed`) and dependency versions are pinned.

**15. Data versioning vs model versioning?** Data versioning = which dataset snapshot (`data/raw.dvc`). Model versioning = which trained artifact (DVC output `voltguard_bundle.joblib` + MLflow registry version). Both are tied to a Git commit.

**16. DVC vs MLflow - who does what?** DVC: data/artifact versioning + pipeline reproducibility. MLflow: experiment tracking + model registry/aliases. `manifest.json` links them.

**17. Why is the DVC remote S3?** Durable, cheap, IAM-controlled, and reachable from CI and EC2. Credentials come from env/IAM roles, never from Git.

## MLflow / registry

**18. What is tracked in MLflow?** Params, metrics (train/val/test, training time), feature importances, artifacts, tags per run; registered model versions and aliases.

**19. What is the model registry?** A catalogue of model versions with lifecycle labels. Here `VoltGuard-Battery-RUL` has versions; alias `candidate` = newest, `champion` = serving version.

**20. Why aliases instead of stages?** MLflow deprecated fixed stages (Staging/Production) in favour of flexible aliases; deployments reference an alias, not a version number.

**21. When is a candidate promoted to champion?** Only if its `soh_test_rmse` beats the current champion by at least `min_relative_improvement` (or there is no champion). Otherwise the manifest carries only `candidate` and the API refuses to serve it.

**22. How does deployment know which model to load?** The DVC-versioned `manifest.json` names the bundle file, SHA-256 and aliases; `MODEL_ALIAS` must be in it. No filename is hard-coded in the API.

## API / Docker / AWS

**23. Why FastAPI?** Type-hint-driven validation (Pydantic), automatic OpenAPI docs, async-capable, fast, and easy to test with `TestClient`.

**24. How is input validated?** Pydantic schema with types, ranges (e.g. voltage 0-5 V), `extra="forbid"`, and cross-field checks; invalid input returns 422 without touching the model.

**25. What does `/predict` return?** `predicted_soh`, `predicted_rul`, `model_name`, `model_version`, `model_alias`, `timestamp`, `model_metadata` (run ID, selected models, checksum, units).

**26. Why Docker?** Identical runtime everywhere, dependency isolation, immutable versioned deployment unit.

**27. Why is the model not baked into the image?** Per the architecture it is fetched from the DVC remote at start - the image stays small, no weights or secrets are in the registry, and the model version is governed by DVC/MLflow, not by image rebuilds.

**28. What is ECR and how are images tagged?** AWS's private container registry. Each build is tagged with the Git commit SHA (immutable, traceable, used for deploys) and `latest` (convenience).

**29. Why EC2 and not Kubernetes?** One small stateless service does not need orchestration; EC2 + Docker is simpler, cheaper and matches the brief. Trade-off: no auto-scaling/self-healing beyond Docker's restart policy.

**30. How does the EC2 host authenticate to ECR and S3 without stored keys?** Through an IAM instance role (least-privilege read policies). The container reaches it via IMDSv2 (hop limit 2).

**31. What are the security-group rules?** 22 from a restricted source for deploy, 80 for the API; everything else closed. Metrics/MLflow are not exposed publicly.

**32. How do you secure the API?** Input validation, optional `X-API-Key` (constant-time compare), non-root container, least-privilege IAM, secrets only in GitHub Secrets/IAM. Missing: HTTPS termination, rate limiting, user auth - listed as future work.

## CI/CD / testing / monitoring

**33. Explain the CI/CD flow.** Push to main -> lint + pytest -> `dvc repro` on real data with quality gate -> `dvc push` model -> `docker build` with that `dvc.lock` -> push to ECR (SHA + latest) -> SSH to EC2 -> `deploy.sh` pulls image -> container pulls model via DVC -> health check -> rollback on failure.

**34. What is the quality gate?** A script failing CI if held-out test RMSE exceeds thresholds in `params.yaml`, preventing deployment of a bad model. (Thresholds are policy values you must tune after the first real run.)

**35. What do the tests cover?** Parsing/validation/cleaning, features and leakage guard, label logic, battery-wise splits, selection rule, bundle predictions, MLflow tracking and registry aliases/promotion, API validation/health/predict/auth/metrics, loader alias & checksum checks.

**36. Why test with synthetic data, and is that valid?** Tests check *code correctness* (shapes, contracts, edge cases) - they do not need real data and make CI fast/offline. Synthetic results are never reported as performance.

**37. What monitoring exists?** Prometheus `/metrics`: request count, latency histogram, prediction count, error count by status, and a model-info gauge with version/alias. Plus `/health` and Docker health check. Not included: data drift or accuracy monitoring (needs ground truth).

**38. How would you detect model drift?** Log incoming feature distributions and compare with training statistics (PSI/KS), and compare predictions to actual capacity/RUL when measurements arrive; retrain via the same DVC pipeline when thresholds are crossed.

**39. What would you do if a new model is worse in production?** Redeploy the previous image SHA (its `dvc.lock` pins the earlier model), or repoint the `champion` alias and re-run the pipeline from the previous commit.

**40. Main limitations?** Only four cells; battery-wise generalisation with so few cells is uncertain; lab conditions differ from EVs; per-cycle summary features need a full discharge cycle; single EC2 instance; MLflow store is local unless a server is provided.
