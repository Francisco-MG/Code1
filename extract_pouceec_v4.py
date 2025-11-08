#!/usr/bin/env python3
# extract_pouceec_env.py
import os, time, json
import pandas as pd
import requests
from datetime import datetime, timezone

# --------- Config depuis l'environnement ----------
def getenv_required(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise SystemExit(f"[CONFIG] Variable d'env manquante: {key}")
    return v

USER        = getenv_required("POUCEEC_USER")
PASSWORD    = getenv_required("POUCEEC_PASSWORD")
BASE_URL    = getenv_required("POUCEEC_BASE_URL")  # endpoint /xapi/std/statements
SINCE       = os.environ.get("POUCEEC_SINCE", "2024-09-01T00:00:00.000Z")
UNTIL       = os.environ.get("POUCEEC_UNTIL", "2025-09-01T00:00:00.000Z")
LIMIT       = int(os.environ.get("POUCEEC_LIMIT", "5000"))
APPLY_SEL   = os.environ.get("POUCEEC_APPLY_SELECTION", "1").lower() in ("1","true","yes","y","on")
WL_CSV      = os.environ.get("POUCEEC_SELECTED_IDS_CSV", "/projects/pouceec/fmarting/2024_25_ID_pre-post.csv")
OUT_CSV     = os.environ.get("POUCEEC_OUT_CSV", "statements_1577.csv")

HEADERS = {"X-Experience-API-Version": "1.0.0"}

# --------- Récup paginée ----------
def fetch_all_data():
    session = requests.Session()
    session.auth = (USER, PASSWORD)

    all_statements = []
    params = {"limit": LIMIT, "since": SINCE, "until": UNTIL, "ascending": "true"}
    max_retries = 3
    retry_delay = 5

    more_url = None

    for attempt in range(max_retries):
        try:
            print(f"Tentative initiale {attempt+1}/{max_retries}...")
            r = session.get(BASE_URL, headers=HEADERS, params=params, timeout=180)
            if r.status_code == 200:
                data = r.json()
                all_statements.extend(data.get("statements", []))
                more_url = data.get("more")
                print(f"Premier bloc: {len(all_statements)} enregistrements")
                break
            else:
                print(f"Erreur {r.status_code}: {r.text}")
        except Exception as e:
            print(f"Exception: {e}")
        if attempt < max_retries - 1:
            wt = retry_delay * (2 ** attempt)
            print(f"Nouvelle tentative dans {wt}s...")
            time.sleep(wt)
        else:
            return []

    page = 1
    while more_url:
        page += 1
        r = session.get(more_url, headers=HEADERS, timeout=180)
        if r.status_code != 200:
            print(f"Erreur {r.status_code}: {r.text}")
            break
        batch = r.json().get("statements", [])
        print(f"Bloc {page}: {len(batch)} enregistrements")
        all_statements.extend(batch)
        more_url = r.json().get("more")
        time.sleep(0.4)

    print(f"Total: {len(all_statements)} enregistrements récupérés")
    return all_statements

# --------- Post-traitements ----------
from collections import defaultdict

def get_timestamp(data):
    ts = data.get("timestamp")
    if ts is None:
        raise KeyError("timestamp manquant dans le statement")
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def sorter_function(trace):
    return trace['sid'], trace['ms']

def create_sid(action):
    sid = "Z"
    if action["verb"]["id"] in [
        "https://pouceecapiserver.irit.fr/started",
        "https://pouceecapiserver.irit.fr/completed",
    ]:
        sid = "{} {} {}".format(
            action["actor"]["account"]["name"], "-", action["object"]["id"]
        )
    else:
        try:
            sid = "{} {} {}".format(
                action["actor"]["account"]["name"],
                "-",
                action["context"]["extensions"][
                    "https://pouceecapiserver.irit.fr/contextActivities"
                ]["grouping"],
            )
        except Exception:
            pass
    return sid

def add_sid_and_ms(data):
    for i, action in enumerate(data):
        timestamp = get_timestamp(action)
        data[i]['ms'] = timestamp.timestamp()
        sid = create_sid(action)
        data[i]['sid'] = sid
    return data

def add_sessions_in_all_traces(data):
    students = defaultdict(list)
    for i, action in enumerate(data):
        if action["verb"]["id"] == "https://pouceecapiserver.irit.fr/started":
            students[action["actor"]["account"]["name"]] = action["object"]["id"]
        if action["verb"]["id"] in [
            "https://pouceecapiserver.irit.fr/verbs/change",
            "http://activitystrea.ms/schema/1.0/play",
            "http://id.tincanapi.com/verb/paused",
            "https://pouceecapiserver.irit.fr/verbs/write",
            "http://pouceecapiserver.irit.fr/verbs/seek",
            "http://pouceecapiserver.irit.fr/verbs/stop",
            "http://activitystrea.ms/schema/1.0/cancel",
        ]:
            if students[action["actor"]["account"]["name"]]:
                data[i].setdefault("context", {}).setdefault("extensions", {})
                data[i]["context"]["extensions"][
                    "https://pouceecapiserver.irit.fr/contextActivities"
                ] = {}
                data[i]["context"]["extensions"][
                    "https://pouceecapiserver.irit.fr/contextActivities"
                ]["grouping"] = students[action["actor"]["account"]["name"]]
    print('Done: add_sessions_in_all_traces ')
    return data

def add_view_page_duration(data):
    sequences = defaultdict(list)
    for i, action in enumerate(data):
        if action.get("actor", {}).get("name", "").startswith("Student"):
            if (action["verb"]["display"]["en-us"] == "viewed") or (
                action["verb"]["display"]["en-us"] == "completed"
            ):
                sid = action['sid']
                if sequences[sid]:
                    Time = get_timestamp(action) - get_timestamp(
                        sequences[sid]["actualPage"]
                    )
                    data[sequences[sid]["actualPageId"]].setdefault("result", {})
                    data[sequences[sid]["actualPageId"]]["result"]["duration"] = Time.total_seconds()
                sequences[sid] = {"actualPage": action, "actualPageId": i}
    print('Done: add_view_page_duration')
    return data

def view_order_correction(data, umbral):
    data = add_sid_and_ms(data)
    data = sorted(data, key=sorter_function)
    diff_rejact = {}
    dff_aceptF = []
    dff_aceptS = []
    forward_modify = []
    started_modify = []
    for i, action in enumerate(data):
        if action["verb"]["display"]["en-us"] in ["forward", "back", "viewed", "started"]:
            if (i > 0) and (action['sid'] != "Z"):
                if (
                    ((action["verb"]["display"]["en-us"] == "forward") or (action["verb"]["display"]["en-us"] == "back"))
                    and (action['sid'] == data[i - 1]['sid'])
                    and (data[i - 1]["verb"]["display"]["en-us"] == "viewed")
                    and (action["object"]["id"] == data[i - 1]["object"]["id"])
                ):
                    delta_time = action['ms'] - data[i - 1]['ms']
                    if delta_time < umbral:
                        dff_aceptF.append(delta_time)
                        data[i]["ms"] = data[i - 1]['ms'] - 1
                        forward_modify.append(action["id"])
                    else:
                        diff_rejact[action["id"]] = delta_time

                if (
                    (action["verb"]["display"]["en-us"] == "started")
                    and (action['sid'] == data[i - 1]['sid'])
                    and (data[i - 1]["verb"]["display"]["en-us"] == "viewed")
                ):
                    delta_time = action['ms'] - data[i - 1]['ms']
                    if delta_time < umbral:
                        dff_aceptS.append(delta_time)
                        data[i]["ms"] = data[i - 1]['ms'] - 1
                        started_modify.append(action["id"])
                    else:
                        diff_rejact[action["id"]] = delta_time
    print('Done: view_order_correction')
    return data

def main_students(data):
    data = add_sessions_in_all_traces(data)
    data = view_order_correction(data, 5000)
    data = add_view_page_duration(data)
    data = add_view_page_duration(data)
    return data

from datetime import date

def add_result_time(data):
    for i, statement in enumerate(data):
        if statement["verb"]["display"]["en-us"] in ["play", "paused", "stoped", "interacted"]:
            try:
                if "https://pouceecapiserver.irit.fr/videoTime" in statement["context"]["extensions"]:
                    data[i].setdefault("result", {}).setdefault("extensions", {})
                    data[i]["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time"] = \
                        statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/videoTime"]
                if "time" in statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/data"]:
                    data[i].setdefault("result", {}).setdefault("extensions", {})
                    data[i]["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time"] = \
                        statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/data"]["time"]
            except Exception:
                pass
    print("Result-time added")
    return data

def add_session_extension(data):
    miss = 0
    for i, action in enumerate(data):
        if action["object"]["definition"]["type"] in [
            "https://pouceecapiserver.irit.fr/video",
            "https://pouceecapiserver.irit.fr/yt-video",
        ]:
            try:
                data[i]["context"]["extensions"]["https://w3id.org/xapi/video/extensions/session-id"] = \
                    data[i]["context"]["extensions"]["https://pouceecapiserver.irit.fr/contextActivities"]["grouping"]
            except Exception:
                if action.get("actor", {}).get("name", "").startswith("Student"):
                    miss += 1
    print("session-id added in videos")
    return data

def add_result_seek_times(data):
    for i, statement in enumerate(data):
        if statement["verb"]["display"]["en-us"] == "seek":
            try:
                if statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/videoTime"] >= 0:
                    data[i].setdefault("result", {}).setdefault("extensions", {})
                    data[i]["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time-to"] = \
                        statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/videoTime"]
            except Exception:
                pass
    print("Time-to added")
    return data

def add_result_duration(data):
    actors = defaultdict(list)
    errors = 0
    for i, action in enumerate(data):
        if action["verb"]["display"]["en-us"] in ["play", "paused", "stoped", "seek"]:
            name = action["actor"]["account"]["name"]
            vid  = action["object"]["id"]
            if actors[name]:
                if actors[name][vid]:
                    last_action = actors[name][vid]
                    if action["verb"]["display"]["en-us"] in ["paused", "stoped", "seek"]:
                        try:
                            duration = action["ms"] - last_action["ms"]
                            ex = data[i].setdefault("result", {}).setdefault("extensions", {})
                            ex["duration"] = duration
                            if last_action["verb"]["display"]["en-us"] == "play":
                                start = last_action["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time"]
                            else:
                                start = last_action["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time-to"]

                            if action["verb"]["display"]["en-us"] == "seek":
                                end = action["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time-to"]
                            else:
                                end = action["result"]["extensions"]["https://w3id.org/xapi/video/extensions/time"]
                            ex["https://w3id.org/xapi/video/extensions/played-segments"] = f"{start}[,]{end}"
                        except Exception:
                            errors += 1
                else:
                    actors[name][vid] = action
            else:
                actors[name] = defaultdict(list)
                actors[name][vid] = action
    return data

def main_videos(data):
    data = add_result_time(data)
    data = add_result_seek_times(data)
    data = add_session_extension(data)
    data = add_result_duration(data)
    return data

# --------- Main ---------
def main():
    print("=== Début extraction xAPI ===")
    print(f"Période: {SINCE} → {UNTIL} — Limit: {LIMIT}")
    print(f"Endpoint: {BASE_URL}")
   
    start_time = datetime.now(timezone.utc)
    statements = fetch_all_data()
    end_fetch_time = datetime.now(timezone.utc)
    print(f"Récupération terminée en {end_fetch_time - start_time}")

    if not statements:
        print("Aucune donnée récupérée")
        print("=== Fin ===")
        return

    res = statements

    # Exclusions
    excluded_users = {
        "79e581b4-32ec-4611-807e-3b630386e6e7",
        "d78414f-7442-47a4-bc2b-b293454c44ed",
        "455c6260-a74f-4ddc-b9bd-7e796434e6a7",
        "4d0169ed-b3c1-431e-9303-6fe5bc2ddf01",
    }
    def _actor_name(s):
        return s.get("actor", {}).get("account", {}).get("name")

    # Whitelist optionnelle
    whitelist_set = None
    if APPLY_SEL:
        sel = pd.read_csv(WL_CSV)
        if "actor.account.name" not in sel.columns:
            raise KeyError("Le CSV de sélection doit contenir une colonne actor.account.name.")
        whitelist_set = set(sel["actor.account.name"].astype(str).str.strip().dropna().unique())

    if whitelist_set is not None:
        res_filtered = [s for s in res if (_actor_name(s) not in excluded_users) and (_actor_name(s) in whitelist_set)]
    else:
        res_filtered = [s for s in res if (_actor_name(s) not in excluded_users)]

    print(f"Filtrage liste blanche: {len(res_filtered)} / {len(res)} statements conservés")

    # Post-traitements
    data = main_students(res_filtered)
    data = main_videos(data)

    # Export final
    df_clean = pd.json_normalize(data)
    df_clean.to_csv(OUT_CSV, index=False)
    print(f"✅ Export filtré: {OUT_CSV} ({df_clean.shape[0]} lignes)")
    print("=== Fin ===")

if __name__ == "__main__":
    main()
