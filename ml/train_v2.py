import json
import warnings
from pathlib import Path
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from decision_v2 import FraudScorer
from features_v2 import CAT_FEATURES, FEATURE_COLS, NUM_FEATURES, compute_features_batch, read_pix_table

warnings.filterwarnings("ignore", message=".*'eval_set' is deprecated.*")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models" / "v2"
SEED = 42
TRAIN_START = pd.Timestamp("2023-01-01", tz="America/Sao_Paulo")
TEMPORAL_CUTOFF = pd.Timestamp("2024-07-01", tz="America/Sao_Paulo")
REJECT_MIN_PRECISION = 0.9
TWO_FACTOR_MIN_RECALL = 0.95
table = read_pix_table(DATA_DIR / "pix_transaction_v2.csv")
labels = pd.read_csv(DATA_DIR / "labels_v2.csv")
table = table.merge(labels, on="pix_id", how="left", validate="one_to_one")
print(f"Pix na tabela: {len(table):,}. Calculando features de histórico...")
features = compute_features_batch(table)
when = pd.to_datetime(table["transaction_date"], utc=True, format="ISO8601").dt.tz_convert("America/Sao_Paulo")
keep = (when >= TRAIN_START).to_numpy()
X = features[keep].reset_index(drop=True)
y = table.loc[keep, "is_fraud"].astype(int).reset_index(drop=True)
fraud_type = table.loc[keep, "fraud_type"].reset_index(drop=True)
when = when[keep].reset_index(drop=True)
print(f"Pix usados no modelo (2023+): {len(X):,} | fraude: {y.mean():.2%}\n")
idx_train, idx_test = train_test_split(np.arange(len(X)), test_size=0.2, stratify=y, random_state=SEED)
idx_fit, idx_val = train_test_split(idx_train, test_size=0.2, stratify=y[idx_train], random_state=SEED)
preprocessor = ColumnTransformer(
    transformers=[
        ("num", SimpleImputer(strategy="median", add_indicator=True), NUM_FEATURES),
        (
            "cat",
            Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                ]
            ),
            CAT_FEATURES,
        ),
    ],
    verbose_feature_names_out=False,
)
preprocessor.set_output(transform="pandas")
Xt_fit = preprocessor.fit_transform(X.iloc[idx_fit])
Xt_val = preprocessor.transform(X.iloc[idx_val])
Xt_test = preprocessor.transform(X.iloc[idx_test])
scale_pos_weight = (y[idx_fit] == 0).sum() / (y[idx_fit] == 1).sum()
MONOTONE = {
    "dest_account_age_days": -1,
    "source_account_age_days": -1,
    "payer_tx_count_90d": -1,
    "payer_tx_count_1h": 1,
    "payer_tx_count_24h": 1,
    "payer_amount_sum_24h": 1,
    "ratio_to_median": 1,
    "is_new_dest_for_payer": 1,
    "is_new_device_for_payer": 1,
    "dest_distinct_payers_24h": 1,
    "dest_distinct_payers_7d": 1,
    "device_distinct_accounts_7d": 1,
    "ip_distinct_accounts_24h": 1,
    "km_from_usual_location": 1,
    "is_night": 1,
}
monotone_constraints = [MONOTONE.get(c, 0) for c in Xt_fit.columns]
model = lgb.LGBMClassifier(
    n_estimators=2000,
    learning_rate=0.03,
    num_leaves=31,
    min_child_samples=50,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    scale_pos_weight=scale_pos_weight,
    monotone_constraints=monotone_constraints,
    metric="average_precision",
    random_state=SEED,
    verbose=-1,
)
model.fit(
    Xt_fit,
    y[idx_fit],
    eval_set=[(Xt_val, y[idx_val])],
    callbacks=[lgb.early_stopping(100, first_metric_only=True, verbose=False)],
)
print(f"Árvores (early stopping): {model.best_iteration_} | scale_pos_weight: {scale_pos_weight:.1f}")
val_score = model.predict_proba(Xt_val)[:, 1]
prec, rec, thr = precision_recall_curve(y[idx_val], val_score)
prec, rec = (prec[:-1], rec[:-1])
ok_reject, ok_2fa = (prec >= REJECT_MIN_PRECISION, rec >= TWO_FACTOR_MIN_RECALL)
t_reject = float(thr[ok_reject].min()) if ok_reject.any() else 0.99
t_2fa = min(float(thr[ok_2fa].max()) if ok_2fa.any() else float(thr.min()), t_reject)
thresholds = {"two_factor": round(t_2fa, 6), "reject": round(t_reject, 6)}
print(f"Limiares: 2FA >= {t_2fa:.4f} | reprovar >= {t_reject:.4f}\n")
y_test = y[idx_test]
test_score = model.predict_proba(Xt_test)[:, 1]
pr_auc, roc_auc = (average_precision_score(y_test, test_score), roc_auc_score(y_test, test_score))
print("=" * 70)
print("TESTE (20% estratificado)")
print("=" * 70)
print(f"PR-AUC : {pr_auc:.4f}   (modelo aleatório: {y_test.mean():.4f})")
print(f"ROC-AUC: {roc_auc:.4f}\n")
flagged = (test_score >= t_2fa).astype(int)
print("Classification report (sinalizado = 2FA ou reprovado):")
print(classification_report(y_test, flagged, target_names=["legítimo", "fraude"], digits=3))
print("Matriz de confusão (linhas = real, colunas = previsto):")
print(
    pd.DataFrame(
        confusion_matrix(y_test, flagged),
        index=["real: legítimo", "real: fraude"],
        columns=["prev: aprovado", "prev: sinalizado"],
    ).to_string(),
    "\n",
)


def decide(s):
    return "rejected" if s >= t_reject else "two_factor_required" if s >= t_2fa else "approved"


decisions = pd.Series([decide(s) for s in test_score])
types_test = fraud_type.iloc[idx_test].reset_index(drop=True)
table_dec = (
    pd.crosstab(decisions, types_test).reindex(["approved", "two_factor_required", "rejected"]).fillna(0).astype(int)
)
print("Decisões no teste, por tipo:")
print(table_dec.to_string(), "\n")
per_type = pd.DataFrame(
    {
        "fraudes": table_dec.sum(),
        "barradas (2FA ou reprovado)": 1 - table_dec.loc["approved"] / table_dec.sum(),
        "reprovadas": table_dec.loc["rejected"] / table_dec.sum(),
    }
).drop(index="legitimo")
print("Recall por tipo de fraude:")
print(per_type.to_string(formatters={c: "{:.1%}".format for c in per_type.columns[1:]}), "\n")
legit_n = (y_test == 0).sum()
legit_friction = 1 - table_dec.loc["approved", "legitimo"] / legit_n
legit_blocked = table_dec.loc["rejected", "legitimo"] / legit_n
fraud_passed = (table_dec.loc["approved"].sum() - table_dec.loc["approved", "legitimo"]) / (y_test == 1).sum()
print(f"Legítimos com alguma fricção: {legit_friction:.2%} | legítimos bloqueados: {legit_blocked:.2%}")
print(f"Fraudes aprovadas sem fricção: {fraud_passed:.2%}\n")
importance = pd.Series(model.booster_.feature_importance("gain"), index=Xt_fit.columns)
print("Top 10 features (ganho):")
print((importance / importance.sum()).sort_values(ascending=False).head(10).round(3).to_string(), "\n")
past, future = ((when < TEMPORAL_CUTOFF).to_numpy(), (when >= TEMPORAL_CUTOFF).to_numpy())
pre_t = clone(preprocessor)
model_t = clone(model).set_params(n_estimators=model.best_iteration_)
model_t.fit(pre_t.fit_transform(X[past]), y[past])
pr_auc_t = average_precision_score(y[future], model_t.predict_proba(pre_t.transform(X[future]))[:, 1])
print(f"PR-AUC temporal (treino < jul/24, teste >= jul/24): {pr_auc_t:.4f}\n")
MODELS_DIR.mkdir(parents=True, exist_ok=True)
joblib.dump(preprocessor, MODELS_DIR / "preprocessor.joblib")
joblib.dump(model, MODELS_DIR / "fraud_model.joblib")
meta = {
    "thresholds": thresholds,
    "decision_policy": {"reject_min_precision": REJECT_MIN_PRECISION, "two_factor_min_recall": TWO_FACTOR_MIN_RECALL},
    "feature_cols": FEATURE_COLS,
    "metrics_test": {
        "pr_auc": round(pr_auc, 4),
        "roc_auc": round(roc_auc, 4),
        "pr_auc_temporal": round(pr_auc_t, 4),
        "legit_friction_rate": round(float(legit_friction), 4),
        "legit_blocked_rate": round(float(legit_blocked), 4),
        "fraud_approved_rate": round(float(fraud_passed), 4),
        "recall_by_type": {k: round(float(v), 4) for k, v in per_type["barradas (2FA ou reprovado)"].items()},
    },
    "best_iteration": int(model.best_iteration_),
    "versions": {"lightgbm": lgb.__version__, "scikit-learn": sklearn.__version__, "pandas": pd.__version__},
}
with open(MODELS_DIR / "fraud_model_meta.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"Salvos em {MODELS_DIR}")
scorer = FraudScorer(MODELS_DIR)
print("\nExemplos de decisão com motivos:")
X_test = X.iloc[idx_test].reset_index(drop=True)
for t in ["ato", "engenharia_social", "golpe_em_massa", "conta_laranja_origem"]:
    hits = np.flatnonzero((types_test == t).to_numpy() & (decisions != "approved").to_numpy())
    if len(hits):
        r = scorer.score(X_test.iloc[[hits[0]]])[0]
        print(f"  [{t}] {r['status']} (score {r['score']}): " + "; ".join(r["reasons"]))
