"""Pydantic request/response schemas. Field set mirrors src.features.engineering.FEATURE_COLUMNS
(enforced by tests/test_api.py::test_schema_matches_feature_columns)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BatteryFeatures(BaseModel):
    """Per-discharge-cycle measurements summarised as in the training pipeline."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        # Illustrative values shaped like NASA cells - NOT taken from a specific measurement.
        "cycle_number": 120, "ambient_temperature": 24.0,
        "voltage_mean": 3.45, "voltage_std": 0.25, "voltage_min": 2.70, "voltage_range": 1.45,
        "current_mean": -2.0, "temperature_mean": 33.0, "temperature_max": 38.0, "temperature_rise": 8.0,
        "discharge_duration": 3000.0, "charge_duration": 9500.0}})

    cycle_number: int = Field(ge=1, le=100_000, description="Discharge cycle index (1-based)")
    ambient_temperature: float = Field(ge=-20, le=90, description="deg C")
    voltage_mean: float = Field(ge=0, le=5, description="Mean terminal voltage during discharge (V)")
    voltage_std: float = Field(ge=0, le=5, description="Std of voltage during discharge (V)")
    voltage_min: float = Field(ge=0, le=5, description="Minimum voltage during discharge (V)")
    voltage_range: float = Field(ge=0, le=5, description="max - min voltage (V)")
    current_mean: float = Field(ge=-50, le=50, description="Mean current (A); negative = discharge in NASA data")
    temperature_mean: float = Field(ge=-20, le=120, description="Mean cell temperature (deg C)")
    temperature_max: float = Field(ge=-20, le=120, description="Max cell temperature (deg C)")
    temperature_rise: float = Field(ge=0, le=100, description="max - min cell temperature (deg C)")
    discharge_duration: float = Field(gt=0, le=1e6, description="Seconds")
    charge_duration: float | None = Field(default=None, gt=0, le=1e6,
                                          description="Seconds; optional - imputed with training median if omitted")

    @model_validator(mode="after")
    def _consistency(self) -> "BatteryFeatures":
        if self.temperature_max + 1e-6 < self.temperature_mean:
            raise ValueError("temperature_max must be >= temperature_mean")
        if self.voltage_min - 1e-6 > self.voltage_mean:
            raise ValueError("voltage_min must be <= voltage_mean")
        return self


class PredictionResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    predicted_soh: float = Field(description="State of health, percent of nominal capacity")
    predicted_rul: float | None = Field(description="Remaining useful life in cycles (null if no RUL model)")
    model_name: str
    model_version: str
    model_alias: str
    timestamp: str
    model_metadata: dict[str, Any]


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    status: str
    model_loaded: bool
    model_version: str | None = None
