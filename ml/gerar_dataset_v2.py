import hashlib
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
R = random.Random(SEED)
NP = np.random.default_rng(SEED)
Faker.seed(SEED)
fake = Faker("pt_BR")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
TZ = timezone(timedelta(hours=-3))
MIN, HOUR, DAY = (60, 3600, 86400)


def to_sec(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp())


HISTORY_START = to_sec("2022-07-01T00:00:00")
TRAIN_START = to_sec("2023-01-01T00:00:00")
END = to_sec("2024-12-31T23:59:59")
N_TOTAL = 93750
FRAUD_RATE = 0.03
N_FRAUD = round(N_TOTAL * FRAUD_RATE)
N_LEGIT = N_TOTAL - N_FRAUD
FRAUD_MIX = {"ato": 0.35, "engenharia_social": 0.3, "golpe_em_massa": 0.15, "conta_laranja_origem": 0.2}
N_PF, N_PJ = (1000, 80)
N_MERCHANTS = 500
CITIES = [
    ("São Paulo", -23.55, -46.63, 22),
    ("Rio de Janeiro", -22.91, -43.17, 12),
    ("Belo Horizonte", -19.92, -43.94, 6),
    ("Brasília", -15.79, -47.88, 6),
    ("Salvador", -12.97, -38.5, 5),
    ("Fortaleza", -3.73, -38.52, 5),
    ("Recife", -8.05, -34.88, 5),
    ("Curitiba", -25.43, -49.27, 5),
    ("Porto Alegre", -30.03, -51.23, 5),
    ("Manaus", -3.12, -60.02, 4),
    ("Belém", -1.46, -48.5, 4),
    ("Goiânia", -16.68, -49.25, 4),
    ("Campinas", -22.91, -47.06, 4),
    ("Florianópolis", -27.6, -48.55, 3),
    ("Vitória", -20.32, -40.34, 3),
]
CITY_CW = list(np.cumsum([c[3] for c in CITIES]))
ISPBS = [
    "00000000",
    "60701190",
    "60746948",
    "00360305",
    "90400888",
    "18236120",
    "00416968",
    "31872495",
    "10573521",
    "22896431",
]
ISPB_W_LEGIT = [14, 13, 12, 11, 8, 16, 8, 7, 6, 5]
ISPB_W_MULE = [3, 3, 3, 3, 3, 25, 18, 16, 14, 12]
OUR_BRANCHES = ["0001", "0002", "0003", "0004"]
RES_OCTETS = [177, 179, 186, 187, 189, 191, 200, 201]
HOUR_PF = [
    0.6,
    0.3,
    0.2,
    0.15,
    0.15,
    0.3,
    1.0,
    2.5,
    4.5,
    5.5,
    6.0,
    6.5,
    7.0,
    6.5,
    6.0,
    6.0,
    6.0,
    6.0,
    6.5,
    6.0,
    5.0,
    4.0,
    2.8,
    1.5,
]
HOUR_PJ = [0.1, 0.05, 0.05, 0.05, 0.05, 0.1, 0.5, 2, 6, 8, 8, 8, 6, 7, 8, 8, 8, 7, 4, 2, 1, 0.5, 0.3, 0.2]
HOUR_NIGHT_FRAUD = [
    3.5,
    3.5,
    3.0,
    2.5,
    2.0,
    1.5,
    1.5,
    2.0,
    3.0,
    3.5,
    4.0,
    4.0,
    4.0,
    4.0,
    4.0,
    4.0,
    4.0,
    4.0,
    4.0,
    4.5,
    5.0,
    5.5,
    5.0,
    4.5,
]


def cum(weights):
    return list(np.cumsum(weights))


HOUR_PF_CW, HOUR_PJ_CW, HOUR_FRAUD_CW = (cum(HOUR_PF), cum(HOUR_PJ), cum(HOUR_NIGHT_FRAUD))
ISPB_LEGIT_CW, ISPB_MULE_CW = (cum(ISPB_W_LEGIT), cum(ISPB_W_MULE))


def pick(population, cum_weights):
    return R.choices(population, cum_weights=cum_weights, k=1)[0]


def sample_time(lo, hi, hour_cw):
    local_lo, local_hi = ((lo - 3 * HOUR) // DAY, (hi - 3 * HOUR) // DAY)
    day = R.randint(local_lo, local_hi)
    hour = pick(range(24), hour_cw)
    t = day * DAY + hour * HOUR + R.randrange(HOUR) + 3 * HOUR
    return min(max(t, lo), hi)


def jitter(lat, lon, sd_deg):
    return (lat + R.gauss(0, sd_deg), lon + R.gauss(0, sd_deg))


def new_device():
    return "dvc-%08x" % R.getrandbits(32)


def rand_ip(octets=RES_OCTETS):
    return f"{R.choice(octets)}.{R.randint(0, 255)}.{R.randint(0, 255)}.{R.randint(1, 254)}"


_used_docs = set()


def new_document(kind):
    while True:
        fmt = fake.cpf() if kind == "PF" else fake.cnpj()
        if fmt not in _used_docs:
            _used_docs.add(fmt)
            return fmt


def digits(s):
    return re.sub("\\D", "", s)


def iso(sec, ms=None):
    dt = datetime.fromtimestamp(sec if ms is None else sec + ms / 1000, TZ)
    return dt.isoformat(timespec="seconds" if ms is None else "milliseconds")


CARRIER_IPS = [rand_ip([170, 152, 168]) for _ in range(400)]
FRAUD_IPS = [rand_ip([45, 103, 185]) for _ in range(80)]
MULE_ORIGIN_IPS = [rand_ip([45, 103, 185]) for _ in range(8)]
DEVICE_FARM = [new_device() for _ in range(12)]
dests = []


def new_dest(kind, open_ts, ispb_cw=ISPB_LEGIT_CW):
    dests.append(
        {
            "participant": pick(ISPBS, ispb_cw),
            "branch": str(R.randint(1, 9999)).zfill(4),
            "account_number": str(R.randint(10000, 99999999)),
            "doc_fmt": new_document(kind),
            "open_ts": open_ts,
            "kind": kind,
        }
    )
    return len(dests) - 1


def old_open_ts():
    return R.randint(to_sec("2008-01-01T00:00:00"), HISTORY_START - 30 * DAY)


merchants = [new_dest("PJ", old_open_ts()) for _ in range(N_MERCHANTS)]
merchant_w = 1 / np.arange(1, N_MERCHANTS + 1) ** 0.9
MERCHANT_CW = cum(merchant_w)
_account_numbers = iter(R.sample(range(10000, 999999), N_PF + N_PJ + 5000))
customers = []


def new_customer(kind, open_ts, is_mule=False):
    city = pick(range(len(CITIES)), CITY_CW)
    home = jitter(CITIES[city][1], CITIES[city][2], 0.05)
    c = {
        "kind": kind,
        "is_mule": is_mule,
        "branch": R.choice(OUR_BRANCHES),
        "account_number": str(next(_account_numbers)),
        "doc_fmt": new_document(kind),
        "open_ts": open_ts,
        "city": city,
        "home": home,
        "devices": [new_device()] + ([new_device()] if R.random() < 0.2 else []),
        "device_change_ts": None,
        "new_devices": None,
        "home_ip": rand_ip(),
        "server_ip": rand_ip(),
    }
    if kind == "PF":
        c["channels"], c["channel_cw"] = (["app", "internet_banking"], cum([88, 12]))
        c["base"] = min(max(R.lognormvariate(np.log(150), 0.9), 5), 20000)
        c["activity"] = R.lognormvariate(0, 0.7)
    else:
        c["channels"], c["channel_cw"] = (["internet_banking", "api", "app"], cum([50, 30, 20]))
        c["base"] = min(max(R.lognormvariate(np.log(2500), 1.0), 50), 300000)
        c["activity"] = R.lognormvariate(0, 0.7) * 4
    if R.random() < 0.3:
        c["device_change_ts"] = R.randint(max(open_ts, HISTORY_START), END)
        c["new_devices"] = [new_device()]
    customers.append(c)
    return c


for i in range(N_PF + N_PJ):
    kind = "PF" if i < N_PF else "PJ"
    opened = old_open_ts() if R.random() < 0.8 else R.randint(HISTORY_START, to_sec("2024-11-30T00:00:00"))
    new_customer(kind, opened)
for c in customers:
    n_personal = R.randint(2, 9) if c["kind"] == "PF" else R.randint(5, 20)
    payees = []
    for _ in range(n_personal):
        kind = "PF" if c["kind"] == "PF" and R.random() < 0.85 else "PJ"
        opened = old_open_ts() if R.random() < 0.8 else R.randint(HISTORY_START, END - 30 * DAY)
        payees.append(new_dest(kind, opened))
    payees += [pick(merchants, MERCHANT_CW) for _ in range(R.randint(1, 4))]
    c["payees"] = payees
    c["payee_cw"] = cum(NP.dirichlet(np.ones(len(payees)) * 0.8))


def devices_at(c, t):
    if c["device_change_ts"] is not None and t >= c["device_change_ts"]:
        return c["new_devices"]
    return c["devices"]


def legit_context(c, t, channel=None):
    channel = channel or pick(c["channels"], c["channel_cw"])
    devs = devices_at(c, t)
    device = devs[0] if len(devs) == 1 or R.random() < 0.8 else devs[1]
    if channel == "api":
        ip, has_geo = (c["server_ip"], False)
    elif channel == "internet_banking":
        ip = c["home_ip"] if R.random() < 0.9 else R.choice(CARRIER_IPS)
        has_geo = R.random() < 0.25
    else:
        ip = c["home_ip"] if R.random() < 0.55 else R.choice(CARRIER_IPS)
        has_geo = R.random() < 0.85
    lat = lon = None
    if has_geo:
        if R.random() < 0.02:
            city = R.randrange(len(CITIES))
            lat, lon = jitter(CITIES[city][1], CITIES[city][2], 0.05)
        else:
            lat, lon = jitter(*c["home"], 0.02)
    return {"device": device, "channel": channel, "ip": ip, "lat": lat, "lon": lon}


txns = []


def add_txn(c, t, dest_idx, amount, ctx, is_fraud, fraud_type):
    txns.append(
        {
            "cust": c,
            "ts": int(t),
            "dest": dest_idx,
            "amount": round(amount, 2),
            "is_fraud": is_fraud,
            "fraud_type": fraud_type,
            **ctx,
        }
    )


for c in list(customers):
    if c["open_ts"] >= HISTORY_START and R.random() < 0.7:
        t = c["open_ts"] + R.randint(HOUR, 10 * DAY)
        for _ in range(R.randint(1, 4)):
            t = min(t + int(R.expovariate(1 / (6 * HOUR))), END)
            if R.random() < 0.6:
                d = pick(c["payees"], c["payee_cw"])
                if dests[d]["open_ts"] >= t:
                    d = pick(merchants, MERCHANT_CW)
            else:
                d = new_dest("PF", old_open_ts())
            amount = c["base"] * R.lognormvariate(np.log(3), 0.6)
            add_txn(c, t, d, amount, legit_context(c, t), 0, "legitimo")
legit_w = [c["activity"] * max(END - max(c["open_ts"], HISTORY_START), 0) for c in customers]
LEGIT_CW = cum(legit_w)
while len(txns) < N_LEGIT:
    c = pick(customers, LEGIT_CW)
    t = sample_time(max(c["open_ts"], HISTORY_START), END, HOUR_PJ_CW if c["kind"] == "PJ" else HOUR_PF_CW)
    session = 1 if R.random() < 0.85 else R.randint(2, 4)
    ctx = legit_context(c, t)
    for k in range(session):
        if k:
            t = min(t + int(R.expovariate(1 / (12 * MIN))), END)
            ctx = legit_context(c, t, ctx["channel"])
        u = R.random()
        known = False
        if u < 0.85:
            d = pick(c["payees"], c["payee_cw"])
            known = dests[d]["open_ts"] < t
            if not known:
                d = pick(merchants, MERCHANT_CW)
        elif u < 0.93:
            d = pick(merchants, MERCHANT_CW)
        else:
            kind = "PF" if R.random() < 0.7 else "PJ"
            opened = (
                old_open_ts()
                if R.random() < 0.65
                else t - int(min(max(R.expovariate(1 / (20 * DAY)), HOUR), 120 * DAY))
            )
            d = new_dest(kind, opened)
            c["payees"].append(d)
            c["payee_cw"] = cum(np.diff([0] + c["payee_cw"]).tolist() + [1 / len(c["payees"])])
        amount = c["base"] * R.lognormvariate(0, 0.6)
        if known and R.random() < 0.03:
            amount *= R.uniform(4, 15)
        add_txn(c, t, d, max(amount, 1.0), ctx, 0, "legitimo")
        if len(txns) >= N_LEGIT:
            break
active_mules = []


def get_mule(t, reuse_p):
    alive = [m for m in active_mules if m[1] <= t <= m[2]]
    if alive and R.random() < reuse_p:
        return R.choice(alive)[0]
    if R.random() < 0.7:
        opened = t - int(min(max(R.expovariate(1 / (3 * DAY)), HOUR), 20 * DAY))
    else:
        opened = t - R.randint(200, 1000) * DAY
    d = new_dest("PF" if R.random() < 0.85 else "PJ", opened, ISPB_MULE_CW)
    active_mules.append((d, t, t + R.randint(1, 7) * DAY))
    return d


def eligible_victim():
    while True:
        c = R.choice(customers)
        if not c["is_mule"] and c["open_ts"] < END - 60 * DAY:
            return c


targets = {k: round(N_FRAUD * v) for k, v in FRAUD_MIX.items()}
targets["ato"] += N_FRAUD - sum(targets.values())
count = {k: 0 for k in targets}


def room(kind):
    return targets[kind] - count[kind]


def fraud(c, t, d, amount, ctx, kind):
    add_txn(c, min(t, END), d, amount, ctx, 1, kind)
    count[kind] += 1


while room("ato") > 0:
    c = eligible_victim()
    t = sample_time(max(c["open_ts"] + 30 * DAY, HISTORY_START), END - DAY, HOUR_FRAUD_CW)
    size = min(1 + int(NP.poisson(1.5)), 6, room("ato"))
    device = new_device() if R.random() < 0.8 else devices_at(c, t)[0]
    ip = R.choice(FRAUD_IPS) if R.random() < 0.5 else rand_ip()
    far_city = R.choice([i for i in range(len(CITIES)) if i != c["city"]])
    has_geo = R.random() < 0.5
    d = get_mule(t, reuse_p=0.5)
    with_test = size >= 2 and R.random() < 0.25
    for k in range(size):
        if k:
            t += int(R.expovariate(1 / (8 * MIN)))
            if R.random() < 0.3:
                d = get_mule(t, reuse_p=0.5)
        lat, lon = jitter(CITIES[far_city][1], CITIES[far_city][2], 0.05) if has_geo else (None, None)
        ctx = {"device": device, "channel": "app", "ip": ip, "lat": lat, "lon": lon}
        if with_test and k == 0:
            amount = R.uniform(1, 30)
        else:
            amount = min(max(c["base"] * R.lognormvariate(np.log(8), 0.6), 200), 50000)
        fraud(c, t, d, amount, ctx, "ato")
while room("engenharia_social") > 0:
    c = eligible_victim()
    t = sample_time(max(c["open_ts"] + 30 * DAY, HISTORY_START), END - DAY, HOUR_PF_CW)
    size = min(1 + (R.random() < 0.35) + (R.random() < 0.15), room("engenharia_social"))
    d = get_mule(t, reuse_p=0.3)
    ctx = legit_context(c, t, "app")
    for k in range(size):
        if k:
            t += int(R.expovariate(1 / (10 * MIN)))
            ctx = legit_context(c, t, "app")
        amount = min(max(c["base"] * R.lognormvariate(np.log(6), 0.7), 300), 30000)
        fraud(c, t, d, amount, ctx, "engenharia_social")
while room("golpe_em_massa") > 0:
    t0 = sample_time(HISTORY_START, END - 3 * DAY, HOUR_PF_CW)
    duration = R.randint(6 * HOUR, 48 * HOUR)
    d = get_mule(t0, reuse_p=0.0)
    price = R.lognormvariate(np.log(250), 0.6)
    for _ in range(min(R.randint(3, 15), room("golpe_em_massa"))):
        c = eligible_victim()
        t = t0 + R.randint(0, duration)
        if c["open_ts"] >= t:
            continue
        amount = min(max(price * R.uniform(0.9, 1.1), 30), 2000)
        fraud(c, t, d, amount, legit_context(c, t, "app"), "golpe_em_massa")
ring = []
while room("conta_laranja_origem") > 0:
    if not ring:
        ring_t = R.randint(HISTORY_START, END - 20 * DAY)
        ring_devices = R.sample(DEVICE_FARM, R.randint(2, 3))
        ring_ip = R.choice(MULE_ORIGIN_IPS)
        ring = list(range(R.randint(2, 6)))
    ring.pop()
    opened = ring_t + R.randint(0, 3 * DAY)
    c = new_customer("PF", opened, is_mule=True)
    device = R.choice(ring_devices)
    ip = ring_ip if R.random() < 0.7 else R.choice(CARRIER_IPS)
    channel = "app" if R.random() < 0.7 else "internet_banking"
    city = R.randrange(len(CITIES))
    has_geo = R.random() < 0.4
    delay = int(min(R.expovariate(1 / (2 * DAY)), 10 * DAY))
    t = (opened + delay - 3 * HOUR) // DAY * DAY + pick(range(24), HOUR_FRAUD_CW) * HOUR + 3 * HOUR
    t = max(t, opened + 5 * MIN)
    size = min(2 + int(NP.poisson(2.5)), 10, room("conta_laranja_origem"))
    for k in range(size):
        if k:
            t += int(R.expovariate(1 / (20 * MIN)))
        d = get_mule(t, reuse_p=0.6) if R.random() < 0.6 else new_dest("PF", old_open_ts())
        lat, lon = jitter(CITIES[city][1], CITIES[city][2], 0.05) if has_geo else (None, None)
        ctx = {"device": device, "channel": channel, "ip": ip, "lat": lat, "lon": lon}
        amount = min(max(R.lognormvariate(np.log(1500), 0.7), 100), 30000)
        fraud(c, t, d, amount, ctx, "conta_laranja_origem")
txns.sort(key=lambda x: x["ts"])
_used_ids = set()
rows, labels = ([], [])
for x in txns:
    while True:
        pix_id = "pix-%012x" % R.getrandbits(48)
        if pix_id not in _used_ids:
            _used_ids.add(pix_id)
            break
    c, d = (x["cust"], dests[x["dest"]])
    amount_cents = max(int(round(x["amount"] * 100)), 1)
    source = {"device_id": x["device"], "channel": x["channel"], "ip": x["ip"]}
    if x["lat"] is not None:
        source["geolocation"] = {"latitude": round(x["lat"], 6), "longitude": round(x["lon"], 6)}
    payload = {
        "id": pix_id,
        "amount": amount_cents,
        "transaction_date": iso(x["ts"]),
        "source_account": {
            "branch": c["branch"],
            "account_number": c["account_number"],
            "opening_date": iso(c["open_ts"]),
            "owner": {"document_number": c["doc_fmt"]},
        },
        "destination_account": {
            "participant": d["participant"],
            "branch": d["branch"],
            "account_number": d["account_number"],
            "opening_date": iso(d["open_ts"]),
            "owner": {"document_number": d["doc_fmt"]},
        },
        "source": source,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    rows.append(
        {
            "pix_id": pix_id,
            "payload_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "raw_payload": raw,
            "amount": amount_cents,
            "transaction_date": iso(x["ts"]),
            "local_hour": datetime.fromtimestamp(x["ts"], TZ).hour,
            "received_at": iso(x["ts"], ms=R.randint(40, 900)),
            "source_branch": c["branch"],
            "source_account_number": c["account_number"],
            "source_document": digits(c["doc_fmt"]),
            "source_opening_date": iso(c["open_ts"]),
            "dest_participant": d["participant"],
            "dest_branch": d["branch"],
            "dest_account_number": d["account_number"],
            "dest_document": digits(d["doc_fmt"]),
            "dest_opening_date": iso(d["open_ts"]),
            "device_id": x["device"],
            "channel": x["channel"],
            "ip": x["ip"],
            "latitude": None if x["lat"] is None else round(x["lat"], 6),
            "longitude": None if x["lon"] is None else round(x["lon"], 6),
        }
    )
    labels.append({"pix_id": pix_id, "is_fraud": x["is_fraud"], "fraud_type": x["fraud_type"]})
table = pd.DataFrame(rows)
labels = pd.DataFrame(labels)
DATA_DIR.mkdir(exist_ok=True)
table.to_csv(DATA_DIR / "pix_transaction_v2.csv", index=False, encoding="utf-8")
labels.to_csv(DATA_DIR / "labels_v2.csv", index=False, encoding="utf-8")
in_window = pd.to_datetime(table["transaction_date"], utc=True) >= pd.Timestamp(TRAIN_START, unit="s", tz="UTC")
print(f"Linhas totais: {len(table):,} (a partir de 2023: {in_window.sum():,})")
print(f"Taxa de fraude: {labels['is_fraud'].mean():.2%}")
print(labels["fraud_type"].value_counts().to_string())
print(f"Sem geolocalização: {table['latitude'].isna().mean():.1%}")
print(f"Salvo em {DATA_DIR}: pix_transaction_v2.csv, labels_v2.csv")
