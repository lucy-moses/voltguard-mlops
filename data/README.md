# Data

**Dataset:** NASA Prognostics Center of Excellence (PCoE) *Li-ion Battery Aging Dataset* (Saha & Goebel, 2007) - 18650 cells (nominal 2 Ah) cycled through charge / discharge / impedance runs until capacity fade. Public, academically standard. The default configuration uses cells **B0005, B0006, B0007, B0018**.

Raw files are **never committed to Git**; they are versioned by DVC (`dvc add data/raw`).

## Expected layout

```
data/
  raw/                 # DVC-tracked (data/raw.dvc is committed, files are not)
    B0005.mat          # any sub-folder depth is fine; files are found recursively
    B0006.mat
    B0007.mat
    B0018.mat
  interim/cycles.csv   # produced by stage data_ingestion (one row per discharge cycle)
  processed/           # produced by stage preprocess: train.csv, val.csv, test.csv
```

## Getting the data

Option A - script (tries the configured URL in `configs/config.yaml`, unzips nested archives):

```bash
python scripts/download_data.py
```

Option B - manual (if the URL has moved; I could not verify the URL from my build environment):

1. Search "NASA PCoE battery data set" on <https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/> and download *Battery Data Set*.
2. Unzip (some archives contain nested zips) and copy `B0005.mat`, `B0006.mat`, `B0007.mat`, `B0018.mat` into `data/raw/`.

Then version it:

```bash
dvc add data/raw
git add data/raw.dvc data/.gitignore
git commit -m "Track raw NASA battery data with DVC"
dvc push
```

## What ingestion extracts

For every **discharge** cycle: summary statistics of voltage / current / temperature, discharge duration, the duration of the immediately preceding charge, ambient temperature, and the measured `Capacity` (Ah). `Capacity` is used only to build the labels (SOH, RUL) - never as a feature.

Cycle indexing: `cycle_number` counts discharge cycles per battery starting at 1 (the raw file interleaves charge/discharge/impedance records).
