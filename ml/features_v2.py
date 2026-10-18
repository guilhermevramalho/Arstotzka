import math
from collections import defaultdict, deque
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
HISTORY_SQL = "\nSELECT pix_id, amount, transaction_date, local_hour,\n       source_branch, source_account_number, source_document, source_opening_date,\n       dest_participant, dest_branch, dest_account_number, dest_document, dest_opening_date,\n       device_id, channel, host(ip) AS ip, latitude, longitude\nFROM pix_transaction\nWHERE transaction_date < :t\n  AND (   (source_account_key = :src AND transaction_date > :t - interval '90 days')\n       OR (dest_account_key   = :dst AND transaction_date > :t - interval '7 days')\n       OR (device_id          = :dev AND transaction_date > :t - interval '7 days')\n       OR (ip                 = CAST(:ip AS inet) AND transaction_date > :t - interval '24 hours'))\n"


def read_pix_table(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={c: str for c in STR_COLS})


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


def compute_features_batch(table: pd.DataFrame) -> pd.DataFrame:
    p = prepare(table)
    n = len(p)
    TS = p["ts"].to_numpy()
    SRC, DST = (p["source_key"].to_numpy(), p["dest_key"].to_numpy())
    DEV, IP = (p["device_id"].to_numpy(), p["ip"].to_numpy())
    AMT = p["amount_brl"].to_numpy(float)
    LAT, LON = (p["latitude"].to_numpy(float), p["longitude"].to_numpy(float))
    dyn_cols = [
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
    ]
    out = np.full((n, len(dyn_cols)), np.nan)
    payer_q = defaultdict(deque)
    dest_q = defaultdict(deque)
    dev_q = defaultdict(deque)
    ip_q = defaultdict(deque)

    def evict(q, cutoff):
        while q and q[0][0] <= cutoff:
            q.popleft()

    order = np.lexsort((np.arange(n), TS))
    pending, cur_ts = ([], None)
    for i in order:
        t = TS[i]
        if t != cur_ts:
            for j in pending:
                payer_q[SRC[j]].append((TS[j], AMT[j], DST[j], DEV[j], LAT[j], LON[j]))
                dest_q[DST[j]].append((TS[j], SRC[j]))
                dev_q[DEV[j]].append((TS[j], SRC[j]))
                ip_q[IP[j]].append((TS[j], SRC[j]))
            pending, cur_ts = ([], t)
        pq = payer_q[SRC[i]]
        evict(pq, t - PAYER_WINDOW)
        base = [e for e in pq if e[0] <= t - BASELINE_GAP]
        recent = [e for e in pq if e[0] > t - BASELINE_GAP]
        amounts = [e[1] for e in base]
        median = float(np.median(amounts)) if amounts else np.nan
        prev_lats = [e[4] for e in base if not math.isnan(e[4])]
        prev_lons = [e[5] for e in base if not math.isnan(e[4])]
        dq = dest_q[DST[i]]
        evict(dq, t - DEST_WINDOW)
        vq = dev_q[DEV[i]]
        evict(vq, t - DEVICE_WINDOW)
        iq = ip_q[IP[i]]
        evict(iq, t - IP_WINDOW)
        out[i] = [
            sum((1 for e in recent if e[0] > t - HOUR)),
            len(recent),
            sum((e[1] for e in recent)),
            len(base),
            median,
            AMT[i] / median if median > 0 else np.nan,
            0 if any((e[2] == DST[i] for e in base)) else 1,
            len({e[1] for e in dq if e[0] > t - DAY}),
            len({e[1] for e in dq}),
            0 if any((e[3] == DEV[i] for e in base)) else 1,
            len({e[1] for e in vq if e[1] != SRC[i]}),
            len({e[1] for e in iq if e[1] != SRC[i]}),
            _location_distance(LAT[i], LON[i], prev_lats, prev_lons),
        ]
        pending.append(i)
    feats = pd.DataFrame(out, columns=dyn_cols, index=p.index)
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
        feats[c] = p[c]
    return feats[FEATURE_COLS]


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


def history_from_table(prepared_table: pd.DataFrame, pix: dict) -> pd.DataFrame:
    cur = prepare(pd.DataFrame([pix])).iloc[0]
    t = cur["ts"]
    h = prepared_table[prepared_table["ts"] < t]
    mask = (
        (h["source_key"] == cur["source_key"]) & (h["ts"] > t - PAYER_WINDOW)
        | (h["dest_key"] == cur["dest_key"]) & (h["ts"] > t - DEST_WINDOW)
        | (h["device_id"] == cur["device_id"]) & (h["ts"] > t - DEVICE_WINDOW)
        | (h["ip"] == cur["ip"]) & (h["ts"] > t - IP_WINDOW)
    )
    return h[mask]


def _digits(s: str) -> str:
    return "".join((ch for ch in str(s) if ch.isdigit()))


def payload_to_row(payload: dict) -> dict:
    src, dst, ctx = (payload["source_account"], payload["destination_account"], payload["source"])
    geo = ctx.get("geolocation") or {}
    return {
        "pix_id": payload["id"],
        "amount": int(payload["amount"]),
        "transaction_date": payload["transaction_date"],
        "local_hour": pd.Timestamp(payload["transaction_date"]).hour,
        "source_branch": str(src["branch"]),
        "source_account_number": str(src["account_number"]),
        "source_document": _digits(src["owner"]["document_number"]),
        "source_opening_date": src["opening_date"],
        "dest_participant": str(dst["participant"]),
        "dest_branch": str(dst["branch"]),
        "dest_account_number": str(dst["account_number"]),
        "dest_document": _digits(dst["owner"]["document_number"]),
        "dest_opening_date": dst["opening_date"],
        "device_id": ctx["device_id"],
        "channel": ctx["channel"],
        "ip": ctx["ip"],
        "latitude": geo.get("latitude"),
        "longitude": geo.get("longitude"),
    }
