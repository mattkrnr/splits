#!/usr/bin/env python3
"""Pull your Garmin activities and sleep into garmin.json for the Splits app.

Usage:
    python3 garmin_pull.py --save-key         # once: paste your API key, it's saved privately
    python3 garmin_pull.py --days 90          # writes ./garmin.json

Your API key is read from ~/.config/garmin/connect-personal-api-key (the same
place Garmin's own client uses), or from --key-file, or from the
GARMIN_PERSONAL_API_KEY environment variable. Standard library only, Python 3.8+.

Endpoints (from Garmin's official client, github.com/garmin/connect-personal-api-python):
    POST /personalapitoken-service/personal-api/personal-api-key/token   (Authorization: ApiKey <key>)
    GET  /activitylist-service/activities/search/activities?start=&limit=&startDate=&endDate=
    GET  /sleep-service/sleep/dailySleepSummariesByDate?startDate=&endDate=
    GET  /sleep-service/sleep/dailySleep?date=            (fallback, one day at a time)
Not yet confirmed against a live account: the token response field name and the
"Bearer" header on data calls. The script prints what it got so we can check.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = "https://personal.connectapi.garmin.com"
DEFAULT_KEY_FILE = "~/.config/garmin/connect-personal-api-key"


class ApiError(Exception):
    pass


def http(method, path, headers, params=None):
    url = HOST + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ApiError(f"{method} {path} -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise ApiError(f"{method} {path} -> {e.reason}")
    return json.loads(body) if body.strip() else None


def _read_key_file(path):
    # utf-8-sig drops the byte-order mark some Windows editors add
    with open(os.path.expanduser(path), encoding="utf-8-sig") as f:
        return f.read().strip()


def read_key(key_file):
    if key_file:
        return _read_key_file(key_file)
    env = os.environ.get("GARMIN_PERSONAL_API_KEY", "").strip()
    if env:
        return env
    path = os.path.expanduser(DEFAULT_KEY_FILE)
    if os.path.exists(path):
        return _read_key_file(path)
    sys.exit(f"No API key found. Save it to {DEFAULT_KEY_FILE} (see the steps in the Connect tab).")


def save_key():
    try:
        import getpass
        key = getpass.getpass("Paste your Garmin API key (it won't show), then press Return: ")
    except Exception:
        key = input("Paste your Garmin API key, then press Return: ")
    key = key.strip().strip("'\"")
    if not key:
        sys.exit("No key entered; nothing saved.")
    path = os.path.expanduser(DEFAULT_KEY_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"Saved. The key ends in ...{key[-4:]}. Now run: python3 garmin_pull.py --days 90")


def get_token(api_key):
    # Matches Garmin's official client: Accept */*, and the token comes back as plain text (a JWT).
    path = "/personalapitoken-service/personal-api/personal-api-key/token"
    req = urllib.request.Request(HOST + path, method="POST",
                                 headers={"Accept": "*/*", "Authorization": f"ApiKey {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        hint = " (the key may be wrong, deleted or expired)" if e.code in (401, 403) else ""
        raise ApiError(f"POST {path} -> HTTP {e.code}{hint}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise ApiError(f"POST {path} -> {e.reason}")
    if body.startswith("{"):  # tolerate a JSON wrapper, just in case
        try:
            data = json.loads(body)
            body = next((data[k] for k in ("access_token", "accessToken", "token") if data.get(k)), "")
        except ValueError:
            body = ""
    if not body:
        sys.exit("Garmin's token response was empty or in an unexpected format.")
    return body


def pull_activities(auth, start, end, page=100):
    out, offset = [], 0
    while True:
        batch = http("GET", "/activitylist-service/activities/search/activities", auth, {
            "start": offset, "limit": page, "startDate": start.isoformat(), "endDate": end.isoformat()})
        if isinstance(batch, dict):
            batch = batch.get("activityList") or batch.get("activities") or []
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


def pull_sleep(auth, start, end, chunk_days=28):
    """Try the range endpoint in chunks; fall back to one call per day if a chunk fails."""
    out, warnings = [], []
    cur = start
    while cur <= end:
        stop = min(cur + dt.timedelta(days=chunk_days - 1), end)
        try:
            out.append(http("GET", "/sleep-service/sleep/dailySleepSummariesByDate", auth,
                            {"startDate": cur.isoformat(), "endDate": stop.isoformat()}))
        except ApiError as e:
            warnings.append(f"range {cur}..{stop} failed ({e}); trying day by day")
            d = cur
            while d <= stop:
                try:
                    out.append(http("GET", "/sleep-service/sleep/dailySleep", auth, {"date": d.isoformat()}))
                except ApiError as e2:
                    warnings.append(f"sleep {d} failed: {e2}")
                d += dt.timedelta(days=1)
        cur = stop + dt.timedelta(days=1)
    return out, warnings


def first_dict(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, list):
        for i in x:
            d = first_dict(i)
            if d:
                return d
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90, help="how many days back to pull (default 90)")
    ap.add_argument("-o", "--out", default="garmin.json")
    ap.add_argument("--key-file", help=f"API key file (default {DEFAULT_KEY_FILE})")
    ap.add_argument("--no-sleep", action="store_true", help="skip sleep")
    ap.add_argument("--save-key", action="store_true",
                    help=f"paste your API key once and save it to {DEFAULT_KEY_FILE}, then exit")
    args = ap.parse_args()

    if args.save_key:
        save_key()
        return

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)
    auth = {"Authorization": f"Bearer {get_token(read_key(args.key_file))}"}

    try:
        acts = pull_activities(auth, start, end)
    except ApiError as e:
        sys.exit(f"Activity pull failed: {e}")
    sleep, warnings = ([], []) if args.no_sleep else pull_sleep(auth, start, end)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"pulledAt": dt.datetime.now().isoformat(timespec="seconds"),
                   "range": [start.isoformat(), end.isoformat()],
                   "activities": acts, "sleep": sleep}, f, indent=1)

    types = {}
    for a in acts:
        t = (a.get("activityType") or {}).get("typeKey", "unknown")
        types[t] = types.get(t, 0) + 1
    print(f"\nWrote {os.path.abspath(args.out)}")
    print(f"  {len(acts)} activities, {start} to {end}: " + (", ".join(f"{k} {v}" for k, v in sorted(types.items())) or "none"))
    print(f"  {len(sleep)} sleep responses")
    for w in warnings[:5]:
        print("  warning:", w)
    print("\nCopy everything below this line and paste it to Claude:")
    print("activity fields:", ", ".join(sorted(acts[0].keys())) if acts else "(none)")
    s = first_dict(sleep)
    print("sleep top-level fields:", ", ".join(sorted(s.keys())) if s else "(none)")
    if s:
        for k, v in s.items():
            inner = first_dict(v)
            if inner and isinstance(v, (dict, list)):
                print(f"  sleep.{k} fields:", ", ".join(sorted(inner.keys()))[:400])


if __name__ == "__main__":
    main()
