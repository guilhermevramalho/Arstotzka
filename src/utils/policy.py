ENGINE_VERSION = "1.0.0"
POLICY_VERSION = "2026-10-18.1"
TWO_FACTOR_FROM_SCORE = 40
REJECT_FROM_SCORE = 80
NIGHT_START_HOUR = 20
NIGHT_END_HOUR = 6
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
LIM_01 = {
    "PF": {"attention_above": 500000, "points": 45, "reject_above": 1500000},
    "PJ": {"attention_above": 2500000, "points": 45, "reject_above": 10000000},
}
LIM_02 = {
    "PF": {"attention_above": 100000, "points": 40, "reject_above": 300000},
    "PJ": {"attention_above": 500000, "points": 35, "reject_above": 1500000},
}
PJ_COUNT_MULTIPLIER = 5
VEL_01 = {
    "attention_window": 2 * MINUTE,
    "attention_count": 3,
    "points": 45,
    "reject_window": 5 * MINUTE,
    "reject_count": 5,
}
VEL_02 = {
    "attention_window": 120,
    "attention_count": 2,
    "points": 45,
    "reject_window": 10 * MINUTE,
    "reject_count": 3,
    "fatal_on_duplicate": True,
}
VEL_03 = {"window": 10 * MINUTE, "attention_count": 3, "points": 40, "reject_count": 5}
PJ_AMOUNT_MULTIPLIER = 5
MON_01 = {
    "min_count": 2,
    "hour_window": HOUR,
    "hour_above": 400000,
    "hour_points": 40,
    "day_window": DAY,
    "day_above": 1000000,
    "day_points": 45,
    "day_reject_above": 2000000,
}
PROFILE_WINDOW = 30 * DAY
PRF_01 = {
    "min_history": 3,
    "min_amount": 100000,
    "attention_multiplier": 3,
    "attention_points": 30,
    "high_multiplier": 8,
    "high_points": 50,
}
PRF_02 = {"amount_above": 20000, "points": 30, "day_window": DAY, "day_amount_above": 100000, "day_points": 45}
PRF_03 = {"window": 7 * DAY, "attention_documents": 2, "attention_points": 30, "high_documents": 3, "high_points": 45}
PRF_04 = {
    "min_distance_km": 100,
    "attention_speed_kmh": 300,
    "attention_points": 45,
    "high_speed_kmh": 800,
    "high_points": 60,
}
PRF_05 = {
    "recent_age": 3 * DAY,
    "recent_min_amount": 100000,
    "recent_points": 30,
    "brand_new_age": DAY,
    "brand_new_amount_above": 300000,
    "brand_new_points": 50,
}
PRF_06 = {"max_tz_divergence_hours": 2}
PRF_07 = {"high_points": 45, "medium_points": 30, "cold_start_min_account_age_days": 30}
CTP_01 = [
    {"max_age": DAY, "inclusive": False, "min_amount": 500000, "points": 60},
    {"max_age": 2 * DAY, "inclusive": True, "min_amount": 200000, "points": 45},
    {"max_age": 7 * DAY, "inclusive": True, "min_amount": 50000, "points": 25},
]
CTP_02 = {
    "window": HOUR,
    "attention_payers": 5,
    "attention_points": 40,
    "high_payers": 10,
    "high_max_dest_age": 30 * DAY,
    "high_points": 60,
}
CTP_03 = {"min_relationship_age": DAY, "min_approved": 1, "points": -25}
