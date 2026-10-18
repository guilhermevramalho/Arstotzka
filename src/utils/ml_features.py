import math
import numpy as np
import pandas as pd

MIN, HOUR, DAY = (60, 3600, 86400)
PAYER_WINDOW = 90 * DAY
BASELINE_GAP = DAY
DEST_WINDOW = 7 * DAY
DEVICE_WINDOW = 7 * DAY
IP_WINDOW = DAY
LOCAL_TZ = "America/Sao_Paulo"
STR_COLS = [
    "pix_id",
    "source_branch",
    "source_account_number",
    "source_document",
    "dest_participant",
    "dest_branch",
    "dest_account_number",
    "dest_document",
    "device_id",
    "channel",
    "ip",
]
NUM_FEATURES = [
    "amount_brl",
    "local_hour",
    "day_of_week",
    "is_night",
    "source_is_pj",
    "dest_is_pj",
    "source_account_age_days",
    "dest_account_age_days",
    "payer_tx_count_1h",
    "payer_tx_count_24h",
    "payer_amount_sum_24h",
    "payer_tx_count_90d",
    "payer_median_amount_90d",
    "ratio_to_median",
    "is_new_dest_for_payer",
    "dest_distinct_payers_24h",
    "dest_distinct_payers_7d",
    "is_new_device_for_payer",
    "device_distinct_accounts_7d",
    "ip_distinct_accounts_24h",
    "km_from_usual_location",
    "geo_missing",
]
CAT_FEATURES = ["channel"]
FEATURE_COLS = NUM_FEATURES + CAT_FEATURES


def _epoch(series) -> np.ndarray:
    dt = pd.to_datetime(series, utc=True, format="ISO8601")
    return ((dt - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(np.int64)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    p = df.copy()
    for c in STR_COLS:
        if c in p:
            p[c] = p[c].astype(str)
    p["source_key"] = p["source_branch"] + ":" + p["source_account_number"]
    p["dest_key"] = p["dest_participant"] + ":" + p["dest_branch"] + ":" + p["dest_account_number"]
    p["ts"] = _epoch(p["transaction_date"])
    p["latitude"] = pd.to_numeric(p["latitude"], errors="coerce")
    p["longitude"] = pd.to_numeric(p["longitude"], errors="coerce")
    local = pd.to_datetime(p["transaction_date"], utc=True, format="ISO8601").dt.tz_convert(LOCAL_TZ)
    p["amount_brl"] = pd.to_numeric(p["amount"]) / 100
    p["local_hour"] = pd.to_numeric(p["local_hour"]).astype(int)
    p["day_of_week"] = local.dt.dayofweek
    p["is_night"] = ((p["local_hour"] >= 22) | (p["local_hour"] < 6)).astype(int)
    p["source_is_pj"] = (p["source_document"].str.len() == 14).astype(int)
    p["dest_is_pj"] = (p["dest_document"].str.len() == 14).astype(int)
    p["source_account_age_days"] = (p["ts"] - _epoch(p["source_opening_date"])) // DAY
    p["dest_account_age_days"] = (p["ts"] - _epoch(p["dest_opening_date"])) // DAY
    p["geo_missing"] = p["latitude"].isna().astype(int)
    return p


def haversine_km(lat1, lon1, lat2, lon2):
    rlat1, rlat2 = (math.radians(lat1), math.radians(lat2))
    a = (
        math.sin((rlat2 - rlat1) / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _location_distance(lat, lon, prev_lats, prev_lons):
    if math.isnan(lat) or not prev_lats:
        return np.nan
    return haversine_km(lat, lon, float(np.median(prev_lats)), float(np.median(prev_lons)))


def compute_features_online(pix: dict, history: pd.DataFrame) -> pd.DataFrame:
    cur = prepare(pd.DataFrame([pix])).iloc[0]
    t, src, dst, dev, ip = (cur["ts"], cur["source_key"], cur["dest_key"], cur["device_id"], cur["ip"])
    if history is None or len(history) == 0:
        h = prepare(pd.DataFrame([pix])).iloc[0:0]
    else:
        h = prepare(history)
    h = h[h["ts"] < t]
    payer = h[(h["source_key"] == src) & (h["ts"] > t - PAYER_WINDOW)]
    dest = h[(h["dest_key"] == dst) & (h["ts"] > t - DEST_WINDOW)]
    device = h[(h["device_id"] == dev) & (h["ts"] > t - DEVICE_WINDOW)]
    ipq = h[(h["ip"] == ip) & (h["ts"] > t - IP_WINDOW)]
    last_24h = payer[payer["ts"] > t - BASELINE_GAP]
    base = payer[payer["ts"] <= t - BASELINE_GAP]
    median = float(base["amount_brl"].median()) if len(base) else np.nan
    geo = base.dropna(subset=["latitude"])
    lat = float(cur["latitude"]) if not pd.isna(cur["latitude"]) else np.nan
    row = {
        "payer_tx_count_1h": int((payer["ts"] > t - HOUR).sum()),
        "payer_tx_count_24h": len(last_24h),
        "payer_amount_sum_24h": float(last_24h["amount_brl"].sum()),
        "payer_tx_count_90d": len(base),
        "payer_median_amount_90d": median,
        "ratio_to_median": cur["amount_brl"] / median if median > 0 else np.nan,
        "is_new_dest_for_payer": int(not (base["dest_key"] == dst).any()),
        "dest_distinct_payers_24h": dest.loc[dest["ts"] > t - DAY, "source_key"].nunique(),
        "dest_distinct_payers_7d": dest["source_key"].nunique(),
        "is_new_device_for_payer": int(not (base["device_id"] == dev).any()),
        "device_distinct_accounts_7d": device.loc[device["source_key"] != src, "source_key"].nunique(),
        "ip_distinct_accounts_24h": ipq.loc[ipq["source_key"] != src, "source_key"].nunique(),
        "km_from_usual_location": _location_distance(
            lat,
            float(cur["longitude"]) if not math.isnan(lat) else np.nan,
            geo["latitude"].tolist(),
            geo["longitude"].tolist(),
        ),
    }
    for c in [
        "amount_brl",
        "local_hour",
        "day_of_week",
        "is_night",
        "source_is_pj",
        "dest_is_pj",
        "source_account_age_days",
        "dest_account_age_days",
        "geo_missing",
        "channel",
    ]:
        row[c] = cur[c]
    return pd.DataFrame([row])[FEATURE_COLS]


def row_from_pix(pix) -> dict:
    return {
        "pix_id": pix.pix_id,
        "amount": pix.amount,
        "transaction_date": pix.transaction_date.isoformat(),
        "local_hour": pix.local_hour,
        "source_branch": pix.source_branch,
        "source_account_number": pix.source_account_number,
        "source_document": pix.source_document,
        "source_opening_date": pix.source_opening_date.isoformat(),
        "dest_participant": pix.dest_participant,
        "dest_branch": pix.dest_branch,
        "dest_account_number": pix.dest_account_number,
        "dest_document": pix.dest_document,
        "dest_opening_date": pix.dest_opening_date.isoformat(),
        "device_id": pix.device_id,
        "channel": pix.channel,
        "ip": pix.ip,
        "latitude": pix.latitude,
        "longitude": pix.longitude,
    }
