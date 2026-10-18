from pathlib import Path
import numpy as np
import pandas as pd
from features_v2 import (
    FEATURE_COLS,
    NUM_FEATURES,
    compute_features_batch,
    compute_features_online,
    history_from_table,
    prepare,
    read_pix_table,
)

ROOT = Path(__file__).resolve().parent
N_SAMPLES = 400
table = read_pix_table(ROOT / "data" / "pix_transaction_v2.csv")
print(f"Calculando features em lote para {len(table):,} Pix...")
batch = compute_features_batch(table)
prepared = prepare(table)
rng = np.random.default_rng(0)
labels = pd.read_csv(ROOT / "data" / "labels_v2.csv")
fraud_idx = np.flatnonzero(table["pix_id"].isin(labels.loc[labels["is_fraud"] == 1, "pix_id"]))
sample_idx = np.concatenate(
    [rng.choice(len(table), N_SAMPLES - 100, replace=False), rng.choice(fraud_idx, 100, replace=False)]
)
mismatches = []
for i in sample_idx:
    pix = table.iloc[i].to_dict()
    online = compute_features_online(pix, history_from_table(prepared, pix)).iloc[0]
    expected = batch.iloc[i]
    for col in NUM_FEATURES:
        a, b = (float(online[col]), float(expected[col]))
        if not (np.isclose(a, b, rtol=1e-09, atol=1e-06) or (np.isnan(a) and np.isnan(b))):
            mismatches.append((table.iloc[i]["pix_id"], col, b, a))
    if online["channel"] != expected["channel"]:
        mismatches.append((table.iloc[i]["pix_id"], "channel", expected["channel"], online["channel"]))
print(f"Pix conferidos: {N_SAMPLES} | features por Pix: {len(FEATURE_COLS)}")
if mismatches:
    print(f"FALHOU: {len(mismatches)} divergências. Primeiras:")
    print(pd.DataFrame(mismatches[:20], columns=["pix_id", "feature", "lote", "online"]).to_string())
    raise SystemExit(1)
print("OK: lote e online idênticos.")
