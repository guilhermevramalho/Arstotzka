import json
import sys
from datetime import datetime
from pathlib import Path
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from features_v2 import CAT_FEATURES, NUM_FEATURES, compute_features_batch, read_pix_table

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models" / "v2"
OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "src" / "utils" / "ml_artifacts"
OUT_DIR.mkdir(parents=True, exist_ok=True)
preprocessor = joblib.load(MODELS_DIR / "preprocessor.joblib")
model = joblib.load(MODELS_DIR / "fraud_model.joblib")
meta = json.load(open(MODELS_DIR / "fraud_model_meta.json", encoding="utf-8"))
num_imputer = preprocessor.named_transformers_["num"]
onehot = preprocessor.named_transformers_["cat"].named_steps["onehot"]
indicator_idx = num_imputer.indicator_.features_.tolist()
spec = {
    "model_version": "v2-" + datetime.now().strftime("%Y%m%d"),
    "num_features": NUM_FEATURES,
    "num_medians": {f: float(v) for f, v in zip(NUM_FEATURES, num_imputer.statistics_)},
    "missing_indicator_features": [NUM_FEATURES[i] for i in indicator_idx],
    "cat_features": CAT_FEATURES,
    "cat_categories": {f: [str(c) for c in cats] for f, cats in zip(CAT_FEATURES, onehot.categories_)},
    "output_columns": list(preprocessor.get_feature_names_out()),
    "thresholds": meta["thresholds"],
    "metrics_test": meta["metrics_test"],
}
with open(OUT_DIR / "preprocess.json", "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False, indent=2)
model.booster_.save_model(str(OUT_DIR / "model.txt"), num_iteration=model.best_iteration_)


def transform(features: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for f in spec["num_features"]:
        out[f] = pd.to_numeric(features[f], errors="coerce").astype(float).fillna(spec["num_medians"][f])
    for f in spec["missing_indicator_features"]:
        out["missingindicator_" + f] = features[f].isna().astype(float)
    for f in spec["cat_features"]:
        values = features[f].astype(object).where(features[f].notna(), "unknown").astype(str)
        for c in spec["cat_categories"][f]:
            out[f"{f}_{c}"] = (values == c).astype(float)
    return pd.DataFrame(out)[spec["output_columns"]]


table = read_pix_table(ROOT / "data" / "pix_transaction_v2.csv")
feats = compute_features_batch(table).sample(5000, random_state=0)
expected = model.predict_proba(preprocessor.transform(feats))[:, 1]
booster = lgb.Booster(model_file=str(OUT_DIR / "model.txt"))
got = booster.predict(transform(feats).to_numpy())
max_diff = float(np.abs(expected - got).max())
print(f"Diferença máxima de score (pipeline original x exportado) em 5.000 Pix: {max_diff:.2e}")
assert max_diff < 1e-09, "export divergiu do modelo original"
print(f"Exportado em {OUT_DIR}: model.txt, preprocess.json")
