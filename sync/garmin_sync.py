#!/usr/bin/env python3
"""Daily Garmin -> Supabase sync for Splits. Runs in GitHub Actions; standard library only.

Environment (set as GitHub repository secrets):
    GARMIN_PERSONAL_API_KEY   your Garmin Personal API key
    SPLITS_SYNC_TOKEN         made on the Splits Connect tab; can only ADD your fitness rows
Optional:
    SYNC_DAYS                 days of activities to pull (default 3; e.g. 2200 for ~6 years of runs)
    SLEEP_DAYS                days of sleep to pull (default: same as SYNC_DAYS, capped at 365; 0 skips sleep)

The Supabase URL and publishable key are read from config.js in this repo. The sync
never holds a key that can read your database: it calls the splits_ingest function,
which checks the token and writes only to the splits_* tables.

This repo is public, so Action logs are public. The script logs only counts and
field NAMES, never your data values or keys.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

sys.path.insert(0, ROOT)
import garmin_pull as gp  # noqa: E402  (token exchange + Garmin endpoints live there)


def env(name, required=True):
    v = os.environ.get(name, "").strip()
    if required and not v:
        sys.exit(f"Missing secret {name}. Add it under the repo's Settings > Secrets and variables > Actions.")
    return v


# ---------- Garmin -> rows ----------

def activity_row(a, user_id):
    at = a.get("activityType") or {}
    type_key = (at.get("typeKey") if isinstance(at, dict) else at) or a.get("activityTypeKey") or "other"
    start = a.get("startTimeGMT") or a.get("startTimeLocal") or a.get("startTime")
    if not start or a.get("activityId") is None:
        return None
    start = str(start).replace(" ", "T")
    if a.get("startTimeGMT") and not start.endswith("Z") and "+" not in start[10:]:
        start += "Z"  # Garmin's GMT field has no zone marker
    return {
        "user_id": user_id,
        "id": str(a["activityId"]),
        "start_time": start,
        "type": str(type_key).lower(),
        "name": a.get("activityName"),
        "meters": a.get("distance"),
        "seconds": a.get("duration") or a.get("movingDuration") or a.get("elapsedDuration"),
        "avg_hr": a.get("averageHR") or a.get("averageHeartRate"),
        "raw": a,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _num(v):
    return int(round(v)) if isinstance(v, (int, float)) else None


def collect_sleep(node, out):
    """Find nightly summaries anywhere in Garmin's sleep responses (shape not yet confirmed)."""
    if isinstance(node, list):
        for n in node:
            collect_sleep(n, out)
        return
    if not isinstance(node, dict):
        return
    cal = node.get("calendarDate")
    sec = next((node[k] for k in ("sleepTimeSeconds", "totalSleepSeconds", "sleepTimeInSeconds")
                if isinstance(node.get(k), (int, float))), None)
    if cal and sec is not None:
        score = None
        ss = node.get("sleepScores")
        if isinstance(ss, dict) and isinstance(ss.get("overall"), dict):
            score = ss["overall"].get("value")
        elif isinstance(node.get("overallSleepScore"), dict):
            score = node["overallSleepScore"].get("value")
        else:
            score = node.get("sleepScore", node.get("overallSleepScore"))
        out.append({"cal": str(cal)[:10], "seconds": _num(sec),
                    "deep": _num(node.get("deepSleepSeconds")), "light": _num(node.get("lightSleepSeconds")),
                    "rem": _num(node.get("remSleepSeconds")), "awake": _num(node.get("awakeSleepSeconds")),
                    "score": _num(score)})
        return
    for v in node.values():
        if isinstance(v, (dict, list)):
            collect_sleep(v, out)


def sleep_rows(responses, user_id):
    found = []
    collect_sleep(responses, found)
    best = {}
    for s in found:
        if s["cal"] not in best or s["seconds"] > best[s["cal"]]["seconds"]:
            best[s["cal"]] = s
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return [{"user_id": user_id, **s, "updated_at": now} for s in best.values()]


# ---------- Supabase (token-gated, write-only) ----------

def read_config():
    text = open(os.path.join(ROOT, "config.js"), encoding="utf-8").read()
    url = re.search(r'url:\s*"([^"]+)"', text)
    key = re.search(r'key:\s*"([^"]+)"', text)
    if not url or not key:
        sys.exit("config.js is missing the Supabase url or key.")
    return url.group(1).rstrip("/"), key.group(1)


class Ingest:
    def __init__(self, url, key, token):
        self.endpoint = url + "/rest/v1/rpc/splits_ingest"
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        if not key.startswith("sb_"):  # legacy anon keys are JWTs and also go in Authorization
            self.headers["Authorization"] = f"Bearer {key}"
        self.token = token

    def call(self, activities=(), sleep=(), ok=None, message=None):
        body = json.dumps({"p_token": self.token, "p_activities": list(activities), "p_sleep": list(sleep),
                           "p_ok": ok, "p_message": message}).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, method="POST", headers=self.headers)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if "Invalid sync token" in detail:
                raise RuntimeError("Supabase rejected the sync token. Make a new one on the Splits Connect tab "
                                   "and update the SPLITS_SYNC_TOKEN secret.")
            raise RuntimeError(f"Supabase write failed: HTTP {e.code} {detail[:200]}")


def strip(row):
    return {k: v for k, v in row.items() if k not in ("user_id", "updated_at")}


def main():
    url, key = read_config()
    db = Ingest(url, key, env("SPLITS_SYNC_TOKEN"))
    days = int(env("SYNC_DAYS", required=False) or 3)
    sleep_env = env("SLEEP_DAYS", required=False)
    sleep_days = int(sleep_env) if sleep_env else min(days, 365)
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    sleep_start = end - dt.timedelta(days=sleep_days)

    def fail(msg):
        try:
            db.call(ok=False, message=msg)
        except RuntimeError as e:
            print("Couldn't record sync status:", str(e).split(":")[0])
        sys.exit(msg)

    try:
        token = gp.get_token(env("GARMIN_PERSONAL_API_KEY"))
    except SystemExit as e:  # garmin_pull exits with a readable message
        fail(f"Garmin sign-in failed: {str(e)[:200]}")
    except gp.ApiError as e:
        fail(f"Garmin sign-in failed: {str(e).split(':')[0]}")
    auth = {"Authorization": f"Bearer {token}"}

    try:
        acts = gp.pull_activities(auth, start, end)
    except gp.ApiError as e:
        fail(f"Activity pull failed: {str(e).split(':')[0]}")
    sleep_raw, warnings = gp.pull_sleep(auth, sleep_start, end) if sleep_days > 0 else ([], [])

    arows = [strip(r) for r in (activity_row(a, None) for a in acts) if r]
    srows = [strip(r) for r in sleep_rows(sleep_raw, None)]
    try:
        for i in range(0, len(arows), 100):
            db.call(activities=arows[i:i + 100])
        msg = f"{start} to {end}: {len(arows)} activities; {len(srows)} sleep nights" + \
              (f" since {sleep_start}" if sleep_days > 0 else " (sleep skipped)")
        if sleep_raw and not srows:
            msg += " (sleep came back but no nights matched the expected fields)"
        db.call(sleep=srows, ok=True, message=msg)
    except RuntimeError as e:
        sys.exit(str(e))
    print("OK:", msg)
    for w in warnings[:5]:
        print("warning:", w.split(":")[0])  # no response bodies in public logs

    # Field names only, to confirm the mapping on the first runs.
    if acts:
        print("activity fields:", ", ".join(sorted(acts[0].keys())))
    s = gp.first_dict(sleep_raw)
    if s:
        print("sleep fields:", ", ".join(sorted(s.keys())))
        for k, v in s.items():
            inner = gp.first_dict(v) if isinstance(v, (dict, list)) else None
            if inner:
                print(f"  sleep.{k} fields:", ", ".join(sorted(inner.keys()))[:400])


if __name__ == "__main__":
    main()
