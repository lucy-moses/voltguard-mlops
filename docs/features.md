# Feature and label documentation

## Labels (targets)

| Target | Definition | Why |
|---|---|---|
| `soh` (%) | `capacity / nominal_capacity_ah * 100`, nominal = 2.0 Ah (`params.yaml`) | Standard capacity-based State of Health |
| `rul` (cycles) | `EOL_cycle - cycle_number`, floored at 0; EOL = first cycle with SOH <= `eol_soh_percent` (70 %) | Remaining cycles before end-of-life. Batteries that never reach EOL in the data get `NaN` (right-censored) and are excluded from RUL training - the value is *not* invented. |

## Features (`src/features/engineering.py::FEATURE_COLUMNS`)

| Feature | Meaning | Why it is used |
|---|---|---|
| `cycle_number` | Discharge cycle index | Ageing is monotonic in usage; strongest generic degradation signal |
| `ambient_temperature` | Test ambient temperature (deg C) | Temperature accelerates ageing; separates operating conditions |
| `voltage_mean` | Mean terminal voltage in discharge | Shifts as internal resistance grows |
| `voltage_std` | Std of discharge voltage | Curve shape changes with ageing |
| `voltage_min` | Lowest discharge voltage (cut-off proximity) | Aged cells reach cut-off sooner/harder |
| `voltage_range` | max - min discharge voltage | Usable voltage window |
| `current_mean` | Mean discharge current | Load context (constant-current in NASA protocol) |
| `temperature_mean` | Mean cell temperature in discharge | Self-heating rises with resistance |
| `temperature_max` | Peak cell temperature | Thermal stress indicator |
| `temperature_rise` | max - min temperature in the cycle | Heat generated during discharge |
| `discharge_duration` (s) | Time to reach cut-off | Under constant current this is ~ capacity/I: **very strong capacity proxy** |
| `charge_duration` (s) | Duration of the preceding charge | Charge time changes as capacity/resistance change; may be NaN -> median-imputed |

## Leakage analysis

* `capacity`, `soh`, `rul`, `battery_id` are **excluded** (asserted in `tests/test_features.py` and at preprocess time).
* No feature uses other rows (no future cycles, no per-battery statistics computed over the whole life), so a single request contains everything the model needs.
* Splits are **by battery**: cells in validation/test never appear in training. Row-wise random splits would leak because consecutive cycles of one cell are nearly identical.
* Scaler/imputer are fit on the training split only.
* **Caveat (be upfront in the viva):** `discharge_duration` under constant-current discharge is nearly proportional to the capacity that defines SOH. It is measured *during the same cycle* and available at inference, so it is legitimate for "assess a battery after a discharge", but it makes the SOH task easier than a partial-charge / online scenario. RUL is the harder and more informative task. To study the effect, drop it from `FEATURE_COLUMNS` and compare.
* Rolling/lagged features were deliberately left out so the API stays stateless; they would require the client to send history.
