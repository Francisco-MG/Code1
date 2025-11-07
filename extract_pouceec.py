import requests
import pandas as pd
from datetime import datetime, timezone
import time
import os

# =========================
# Paramètres généraux
# =========================
USER = "pouceec"
PASSWORD = "Pouceec2023"

BASE_URL = "https://pouceecapiserver.irit.fr/trax/api/fecac2d5-a450-4ae7-b1e1-9d7a99c4a908/xapi/std/statements"
HEADERS = {"X-Experience-API-Version": "1.0.0"}

LIMIT = 5000
SINCE = "2024-09-01T00:00:00.000Z"
UNTIL = "2025-09-01T00:00:00.000Z"

# Sélection par liste blanche
APPLY_SELECTION = True
SELECTED_IDS_CSV = "/projects/pouceec/fmarting/2024_25_ID_pre-post.csv"  # doit contenir la colonne actor.account.name

# =========================
# Récupération paginée
# =========================
def fetch_all_data():
    session = requests.Session()
    session.auth = (USER, PASSWORD)

    all_statements = []
    params = {"limit": LIMIT, "since": SINCE, "until": UNTIL, "ascending": "true"}

    max_retries = 3
    retry_delay = 5

    # Requête initiale
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

    # Pagination via more
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

# =========================
# Exécution principale
# =========================
print("=== Début extraction xAPI ===")
print(f"Période: {SINCE} → {UNTIL} — Limit: {LIMIT}")

start_time = datetime.now(timezone.utc)
statements = fetch_all_data()
end_fetch_time = datetime.now(timezone.utc)
print(f"Récupération terminée en {end_fetch_time - start_time}")

# 1) res = all_statements (brut) + export FULL normalisé
if statements:
    # res (brut) complet
    res = statements

    # Export complet normalisé (désactivé)
    # df_full = pd.json_normalize(res)
    # df_full.to_csv("all_statements_full.csv", index=False)
    # print(f"✅ Export complet: all_statements_full.csv ({df_full.shape[0]} lignes)")

    # 2) Filtrage par liste blanche (en conservant la structure brute)
    # Exclusions de base (si besoin)
    excluded_users = {
        "79e581b4-32ec-4611-807e-3b630386e6e7",
        "d78414f-7442-47a4-bc2b-b293454c44ed",
        "455c6260-a74f-4ddc-b9bd-7e796434e6a7",
        "4d0169ed-b3c1-431e-9303-6fe5bc2ddf01",
    }

    def _actor_name(s):
        return s.get("actor", {}).get("account", {}).get("name")

    # liste blanche
    whitelist_set = None
    if APPLY_SELECTION:
        sel = pd.read_csv(SELECTED_IDS_CSV)
        if "actor.account.name" not in sel.columns:
            raise KeyError("Le CSV de sélection doit contenir une colonne actor.account.name.")
        whitelist_set = set(sel["actor.account.name"].astype(str).str.strip().dropna().unique())

    # filtrage sur la liste blanche + exclusions
    if whitelist_set is not None:
        res_filtered = [
            s for s in res
            if (_actor_name(s) not in excluded_users) and (_actor_name(s) in whitelist_set)
        ]
    else:
        res_filtered = [
            s for s in res
            if (_actor_name(s) not in excluded_users)
        ]

    print(f"Filtrage liste blanche: {len(res_filtered)} / {len(res)} statements conservés")


    # Calculate times in page and in finish a session
    from collections import OrderedDict, defaultdict
    from datetime import datetime, timedelta, timezone
    import json
    import asyncio

    # --- FIX: robust parsing des timestamps ISO 8601 avec 'Z' ---
    def get_timestamp(data):
        ts = data.get("timestamp")
        if ts is None:
            raise KeyError("timestamp manquant dans le statement")
        # supporte ...Z et ...+00:00
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
            # object.id: start , complete
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
            except Exception as e:
                error = "Error creating SID with: " + action["id"] + action["verb"]["id"] + '\n'
                # writeLog(error)
        return sid

    def add_sid_and_ms(data):
        for i, action in enumerate(data):
            timestamp = get_timestamp(action)
            # si aware, .timestamp() suffit; on garde UTC
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
                    # --- FIX: s'assurer que context/extensions existent ---
                    data[i].setdefault("context", {}).setdefault("extensions", {})
                    data[i]["context"]["extensions"][
                        "https://pouceecapiserver.irit.fr/contextActivities"
                    ] = {}
                    data[i]["context"]["extensions"][
                        "https://pouceecapiserver.irit.fr/contextActivities"
                    ]["grouping"] = students[action["actor"]["account"]["name"]]
                else:
                    print(action['id'], 'No start found: ', action['verb']['display']['en-us'])
        print('Done: add_sessions_in_all_traces ')
        return data

    def add_view_page_duration(data):
        sequences = defaultdict(list)
        for i, action in enumerate(data):
            # --- FIX: accès sûr à actor.name ---
            if action.get("actor", {}).get("name", "").startswith("Student"):
                if (action["verb"]["display"]["en-us"] == "viewed") | (
                    action["verb"]["display"]["en-us"] == "completed"
                ):
                    sid = action['sid']
                    # If some page was view
                    if sequences[sid]:
                        # Time spend in last page
                        Time = get_timestamp(action) - get_timestamp(
                            sequences[sid]["actualPage"]
                        )
                        data[sequences[sid]["actualPageId"]]["result"] = {}
                        data[sequences[sid]["actualPageId"]]["result"]["duration"] = Time.total_seconds()
                    # Update Actual Page
                    sequences[sid] = {}
                    sequences[sid]["actualPage"] = action
                    sequences[sid]["actualPageId"] = i
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
                # --- FIX: opérateur logique ---
                if (i > 0) and (action['sid'] != "Z"):
                    # If in the sequence there is a forward-page just after the respective view-page (same object.id)
                    if (
                        (
                            (action["verb"]["display"]["en-us"] == "forward")
                            | (action["verb"]["display"]["en-us"] == "back")
                        )
                        & (action['sid'] == data[i - 1]['sid'])
                        & (data[i - 1]["verb"]["display"]["en-us"] == "viewed")
                        & (action["object"]["id"] == data[i - 1]["object"]["id"])
                    ):
                        delta_time = action['ms'] - data[i - 1]['ms']
                        if delta_time < umbral:
                            dff_aceptF.append(delta_time)
                            data[i]["ms"] = data[i - 1]['ms'] - 1
                            forward_modify.append(action["id"])
                        else:
                            diff_rejact[action["id"]] = delta_time

                    # If in the sequence (same SID) there is a started-session right after the view-page of the same session
                    if (
                        (action["verb"]["display"]["en-us"] == "started")
                        & (action['sid'] == data[i - 1]['sid'])
                        & (data[i - 1]["verb"]["display"]["en-us"] == "viewed")
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

    # Video preprocessing
    from datetime import datetime, date

    def add_result_time(data):
        """Copy videoTime to Result"""
        for i, statement in enumerate(data):
            if statement["verb"]["display"]["en-us"] in ["play", "paused", "stoped", "interacted"]:
                try:
                    if "https://pouceecapiserver.irit.fr/videoTime" in statement["context"]["extensions"]:
                        data[i]["result"] = {}
                        data[i]["result"]["extensions"] = {}
                        data[i]["result"]["extensions"][
                            "https://w3id.org/xapi/video/extensions/time"
                        ] = statement["context"]["extensions"][
                            "https://pouceecapiserver.irit.fr/videoTime"
                        ]

                    if "time" in statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/data"]:
                        data[i]["result"] = {}
                        data[i]["result"]["extensions"] = {}
                        data[i]["result"]["extensions"][
                            "https://w3id.org/xapi/video/extensions/time"
                        ] = statement["context"]["extensions"][
                            "https://pouceecapiserver.irit.fr/data"
                        ]["time"]

                except Exception as Argument:
                    now = date.today().strftime("%Y-%m-%d %H:%M:%S")
                    error = "Error occurred at {} while addResultTime running to {}, index: {} \n".format(
                        now, statement["id"], "ids[i]"
                    )
                    # writeLog(error)

        print("Result-time added")
        return data

    def add_session_extension(data):
        """To the video action is a specific extension"""
        miss = 0
        for i, action in enumerate(data):
            if action["object"]["definition"]["type"] in [
                "https://pouceecapiserver.irit.fr/video",
                "https://pouceecapiserver.irit.fr/yt-video",
            ]:
                try:
                    data[i]["context"]["extensions"][
                        "https://w3id.org/xapi/video/extensions/session-id"
                    ] = data[i]["context"]["extensions"][
                        "https://pouceecapiserver.irit.fr/contextActivities"
                    ]["grouping"]
                except:
                    # --- FIX: accès sûr à actor.name pour le comptage ---
                    if action.get("actor", {}).get("name", "").startswith("Student"):
                        miss += 1
                    print('No session found: ', action['id'], miss)

        print("https://w3id.org/xapi/video/extensions/session-id  added in videos ")
        return data

    def add_result_seek_times(data):
        """Copy videoTime to Result"""
        for i, statement in enumerate(data):
            if statement["verb"]["display"]["en-us"] == "seek":
                try:
                    if statement["context"]["extensions"]["https://pouceecapiserver.irit.fr/videoTime"] >= 0:
                        data[i]["result"] = {}
                        data[i]["result"]["extensions"] = {}
                        data[i]["result"]["extensions"][
                            "https://w3id.org/xapi/video/extensions/time-to"
                        ] = statement["context"]["extensions"][
                            "https://pouceecapiserver.irit.fr/videoTime"
                        ]
                except Exception as Argument:
                    now = date.today().strftime("%Y-%m-%d %H:%M:%S")
                    error = "Error occurred at {} while addResultTime running to {} \n".format(
                        now, statement["id"]
                    )
                    # writeLog(error)

        print("Time-to added")
        return data

    # To do: try new version: September 3
    def add_result_duration(data):
        actors = defaultdict(list)
        errors = 0
        for i, action in enumerate(data):
            # Interaction avec une vidéo
            if action["verb"]["display"]["en-us"] in ["play", "paused", "stoped", "seek"]:
                # Dict pour l'acteur
                if actors[action["actor"]["account"]["name"]]:
                    # Dict pour la vidéo dans le dict de l'acteur
                    if actors[action["actor"]["account"]["name"]][action["object"]["id"]]:
                        last_action = actors[action["actor"]["account"]["name"]][action["object"]["id"]]
                        # fin de segment
                        if action["verb"]["display"]["en-us"] in ["paused", "stoped", "seek"]:
                            try:
                                duration = action["ms"] - last_action["ms"]
                                if data[i]["result"]["extensions"]:
                                    data[i]["result"]["extensions"]["duration"] = duration
                                else:
                                    data[i]["result"]["extensions"] = {}
                                    data[i]["result"]["extensions"]["duration"] = duration

                                # play
                                if last_action["verb"]["display"]["en-us"] == "play":
                                    start = last_action["result"]["extensions"][
                                        "https://w3id.org/xapi/video/extensions/time"
                                    ]
                                # seek
                                else:
                                    # --- FIX: manquait le niveau 'extensions' ---
                                    start = last_action["result"]["extensions"][
                                        "https://w3id.org/xapi/video/extensions/time-to"
                                    ]

                                if action["verb"]["display"]["en-us"] == "seek":
                                    end = action["result"]["extensions"][
                                        "https://w3id.org/xapi/video/extensions/time-to"
                                    ]
                                else:
                                    end = action["result"]["extensions"][
                                        "https://w3id.org/xapi/video/extensions/time"
                                    ]
                                played_segments = "{}[,]{}".format(start, end)
                                data[i]["result"]["extensions"][
                                    "https://w3id.org/xapi/video/extensions/played-segments"
                                ] = played_segments
                            except Exception as Argument:
                                errors += 1
                                now = date.today().strftime("%Y-%m-%d %H:%M:%S")
                                error = "Error occurred at {} while add duration-Time running to {}, n° {} \n".format(
                                    now, action["id"], errors
                                )
                                # writeLog(error)
                    else:
                        # First play in the video
                        actors[action["actor"]["account"]["name"]][action["object"]["id"]] = action
                else:
                    actors[action["actor"]["account"]["name"]] = defaultdict(list)
                    actors[action["actor"]["account"]["name"]][action["object"]["id"]] = action
            # else: NO video interaction
        return data

    def add_length_extension():
        """Data pending on platform"""
        pass

    def main_videos(data):
        data = add_result_time(data)
        data = add_result_seek_times(data)
        data = add_session_extension(data)
        data = add_result_duration(data)
        return data

    # --- IMPORTANT : exécuter ces traitements UNIQUEMENT si des statements existent ---
    data = main_students(res_filtered)
    data = main_videos(data)

   
    # Export CLEAN normalisé
    df_clean = pd.json_normalize(data)
    df_clean.to_csv("statements_1577.csv", index=False)
    print(f"✅ Export filtré: statements_1577.csv ({df_clean.shape[0]} lignes)")

    # res = liste filtrée (forme origine)
    # res = res_filtered
else:
    print("Aucune donnée récupérée")
    res = []

# Pas d export JSON / Parquet / NDJSON (allégé)
print("=== Fin ===")
