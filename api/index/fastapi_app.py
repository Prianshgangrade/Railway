import os
import json
import csv
import re
import queue
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi import BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from pymongo import MongoClient
from dotenv import load_dotenv
import certifi

# Local scoring utils
try:
    from .scoring_algorithm import ScoringTrain, get_available_platforms, calculate_platform_scores  # type: ignore
except Exception:
    from scoring_algorithm import ScoringTrain, get_available_platforms, calculate_platform_scores  # type: ignore

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise RuntimeError("MONGO_URI not found in environment; create api/.env with your connection string")

# --- Mongo setup ---
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client.get_database('railwayDB')
trains_collection = db['trains']
platforms_collection = db['platforms']
state_collection = db['station_state']
logs_collection = db['operations_log']
reports_collection = db['daily_reports']

API_DIR = os.path.dirname(__file__)
BLOCKAGE_MATRIX_FILE = os.path.join(API_DIR, 'Track Connections.xlsx - Tracks.csv')
BLOCKAGE_MATRIX = {}
INCOMING_LINES = []

# --- SSE infra ---
sse_broadcaster: queue.Queue[str] = queue.Queue()
active_timers: dict[str, threading.Timer] = {}
timers_lock = threading.Lock()

# Coalesced CSV write scheduling (avoid churn while keeping eventual consistency)
csv_timers: dict[str, threading.Timer] = {}
csv_timers_lock = threading.Lock()

# --- FastAPI app ---
app = FastAPI(title="Kharagpur Station Control API", version="2.0")

# CORS: permissive by default; tighten later if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ---------- Helpers ----------

def parse_blockage_cell(cell_string):
    s = str(cell_string or '')
    s = s.replace('\r\n', '\n').replace('\r', '\n').strip()
    up = s.upper().replace(' ', '')
    if not s or up == '--NA--' or (('NA' in up) and ('(' not in s)):
        return []
    routes = []
    for part in s.split('\n'):
        part = part.strip()
        if not part:
            continue
        route_data = {'full': [], 'partial': []}
        matches = re.findall(r'(\d+)\s*\((.*?)\)', part)
        if len(matches) >= 1:
            nums_str = matches[0][1].strip()
            if nums_str:
                route_data['full'] = [f"P{s.strip()}" for s in nums_str.split(',')]
        if len(matches) >= 2:
            nums_str = matches[1][1].strip()
            if nums_str:
                route_data['partial'] = [f"P{s.strip()}" for s in nums_str.split(',')]
        routes.append(route_data)
    return routes


def load_blockage_matrix():
    matrix, lines = {}, []
    with open(BLOCKAGE_MATRIX_FILE, mode='r', encoding='utf-8-sig', newline='') as infile:
        reader = csv.reader(infile)
        headers = next(reader, None)
        if not headers:
            return {}, []
        headers = [h.strip() for h in headers]
        for row in reader:
            if not row:
                continue
            incoming_line = (row[0] or '').strip()
            if not incoming_line:
                continue
            lines.append(incoming_line)
            matrix[incoming_line] = {}
            max_cols = min(len(row), len(headers))
            for col_idx in range(1, max_cols):
                cell = row[col_idx]
                if not cell or not str(cell).strip():
                    continue
                platform_header = headers[col_idx] if col_idx < len(headers) else f"Col{col_idx}"
                platform_header = platform_header.strip() or f"Col{col_idx}"
                matrix[incoming_line][platform_header] = parse_blockage_cell(cell)
    return matrix, lines


def _today_str():
    return datetime.now().strftime('%Y-%m-%d')


def time_difference_seconds(time_str1, time_str2):
    try:
        t1 = datetime.strptime(time_str1, '%H:%M')
        t2 = datetime.strptime(time_str2, '%H:%M')
        if t2 < t1:
            t2 += timedelta(days=1)
        return (t2 - t1).total_seconds()
    except (ValueError, TypeError):
        return 0


def log_action(action_string: str):
    logs_collection.insert_one({"timestamp": datetime.now(), "action": action_string})


def persist_state(state_doc: dict):
    """Persist the station state to Mongo.
    Separated into a function so we can schedule it as a background task to avoid
    blocking the request/response cycle on slow network I/O.
    """
    try:
        state_collection.replace_one({"_id": "current_station_state"}, state_doc, upsert=True)
    except Exception:
        # Intentionally swallow errors in background to avoid surfacing to users
        # (operational logs in Mongo/Render console will still show failures)
        pass


def schedule_csv_write(date_str: str):
    """Debounce CSV generation for a date; runs ~1s after last schedule."""
    def _run():
        try:
            write_csv_for_date(date_str)
        finally:
            with csv_timers_lock:
                csv_timers.pop(date_str, None)

    with csv_timers_lock:
        if date_str in csv_timers:
            try:
                csv_timers[date_str].cancel()
            except Exception:
                pass
        t = threading.Timer(1.0, _run)
        csv_timers[date_str] = t
        t.start()


def persist_report_update(train_no: str, update_fields: dict):
    """Upsert daily report and schedule CSV generation for today's date in the background."""
    try:
        upsert_daily_report(train_no, update_fields)
        schedule_csv_write(_today_str())
    except Exception:
        pass


def upsert_daily_report(train_no, update_fields, date_str=None):
    if not train_no:
        return
    date_key = date_str or _today_str()
    reports_collection.update_one(
        {"date": date_key, "trainNo": str(train_no)},
        {"$set": {**update_fields, "date": date_key, "trainNo": str(train_no)}},
        upsert=True,
    )


def write_csv_for_date(date_str):
    try:
        rows = list(reports_collection.find({"date": date_str}, {"_id": 0}).sort("trainNo", 1))
        csv_path = os.path.join(API_DIR, 'reports', f"{date_str}.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        headers = [
            'date', 'trainNo', 'trainName', 'scheduled_arrival', 'scheduled_departure',
            'actual_arrival', 'actual_departure', 'top3_suggestions', 'actual_platform',
            'incoming_line', 'outgoing_line'
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            import csv as _csv
            writer = _csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    'date': r.get('date', ''),
                    'trainNo': r.get('trainNo', ''),
                    'trainName': r.get('trainName', ''),
                    'scheduled_arrival': r.get('scheduled_arrival', ''),
                    'scheduled_departure': r.get('scheduled_departure', ''),
                    'actual_arrival': r.get('actual_arrival', ''),
                    'actual_departure': r.get('actual_departure', ''),
                    'top3_suggestions': ', '.join(r.get('top3_suggestions', []) or []),
                    'actual_platform': r.get('actual_platform', ''),
                    'incoming_line': r.get('incoming_line', ''),
                    'outgoing_line': r.get('outgoing_line', ''),
                })
    except Exception:
        pass


# ---------- FastAPI lifecycle ----------

@app.on_event("startup")
async def startup_event():
    global BLOCKAGE_MATRIX, INCOMING_LINES
    BLOCKAGE_MATRIX, INCOMING_LINES = load_blockage_matrix()
    # Ensure helpful indexes exist (idempotent)
    try:
        reports_collection.create_index([('date', 1), ('trainNo', 1)], unique=True)
    except Exception:
        pass
    try:
        logs_collection.create_index('timestamp')
    except Exception:
        pass
    try:
        trains_collection.create_index('TRAIN NO', unique=True)
    except Exception:
        pass
    # Initialize station state if absent
    if state_collection.count_documents({}) == 0:
        try:
            platforms_master_raw = list(platforms_collection.find({}, {'_id': 0}))
            if len(platforms_master_raw) == 1 and 'tracks' in platforms_master_raw[0]:
                platforms_master = platforms_master_raw[0]['tracks']
            else:
                platforms_master = platforms_master_raw
            trains_master = list(trains_collection.find({}, {'_id': 0}))
            initial_platforms = []
            for track_data in platforms_master:
                is_platform = track_data.get('is_platform', False)
                item_id = track_data['id'].replace('P', '').replace('T', '')
                initial_platforms.append({
                    'id': f"Platform {item_id}" if is_platform else f"Track {item_id}",
                    'isOccupied': False,
                    'trainDetails': None,
                    'isUnderMaintenance': False,
                    'actualArrival': None
                })
            initial_schedule = []
            for row in trains_master:
                initial_schedule.append({
                    'trainNo': str(row['TRAIN NO']),
                    'name': row['TRAIN NAME'],
                    'scheduled_arrival': row.get('ARRIVAL AT KGP'),
                    'scheduled_departure': row.get('DEPARTURE FROM KGP')
                })
            initial_state = {
                '_id': 'current_station_state',
                'platforms': initial_platforms,
                'arrivingTrains': sorted(initial_schedule, key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99'),
                'waitingList': []
            }
            state_collection.insert_one(initial_state)
            log_action("System initialized: Station state created from master data.")
        except Exception:
            pass


# ---------- Routes ----------

@app.get("/")
async def home():
    return Response(content="Kharagpur Station Control API is running.")

@app.get("/api/health")
async def health():
    try:
        _ = db.list_collection_names()
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "db": db_ok}


@app.get("/api/stream")
async def stream():
    def event_generator():
        yield ": connected\n\n"
        while True:
            try:
                msg = sse_broadcaster.get(timeout=15)
                yield msg
            except queue.Empty:
                yield "event: ping\ndata: {}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@app.get("/api/station-data")
async def get_station_data():
    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    if state and '_id' in state:
        state['_id'] = str(state['_id'])
    # Sync arriving trains from master
    try:
        master = list(trains_collection.find({}, {'_id': 0}))
        arr = state.get('arrivingTrains', []) or []
        by_no = {str(t.get('trainNo')): t for t in arr}
        changed = False
        for row in master:
            train_no = str(row.get('TRAIN NO'))
            if not train_no:
                continue
            entry = {
                'trainNo': train_no,
                'name': row.get('TRAIN NAME'),
                'scheduled_arrival': row.get('ARRIVAL AT KGP'),
                'scheduled_departure': row.get('DEPARTURE FROM KGP'),
            }
            if train_no in by_no:
                cur = by_no[train_no]
                if cur.get('name') != entry['name'] or cur.get('scheduled_arrival') != entry['scheduled_arrival'] or cur.get('scheduled_departure') != entry['scheduled_departure']:
                    cur.update(entry)
                    changed = True
            else:
                arr.append(entry)
                by_no[train_no] = entry
                changed = True
        if changed:
            arr.sort(key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99')
            state['arrivingTrains'] = arr
            state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    except Exception:
        pass
    return JSONResponse(state)


@app.get("/api/logs")
async def get_logs():
    log_entries = list(logs_collection.find().sort("timestamp", -1).limit(100))
    logs_json = [{"timestamp": log['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), "action": log['action']} for log in log_entries]
    return logs_json


class SuggestRequest(BaseModel):
    trainNo: str
    incomingLine: str
    platforms: list
    freightNeedsPlatform: bool | None = None


@app.post("/api/platform-suggestions")
async def platform_suggestions(body: SuggestRequest, background_tasks: BackgroundTasks):
    train_no = body.trainNo
    incoming_line = body.incomingLine
    frontend_platforms = body.platforms
    freight_needs_platform = body.freightNeedsPlatform

    if not all([train_no, incoming_line, frontend_platforms]):
        raise HTTPException(status_code=400, detail="Missing required parameters: trainNo, incomingLine, and platforms are all required.")

    train_data = trains_collection.find_one({"TRAIN NO": str(train_no)})
    if not train_data:
        raise HTTPException(status_code=404, detail=f"Train {train_no} not found in master schedule.")

    is_freight = 'Goods' in train_data.get('TRAIN NAME', '') or 'Freight' in train_data.get('TRAIN NAME', '')

    incoming_train = ScoringTrain(
        train_id=train_data.get('TRAIN NO'),
        train_name=train_data.get('TRAIN NAME'),
        train_type='Freight' if is_freight else 'Passenger',
        is_terminating=train_data.get('ISTERMINATING', False),
        length=str(train_data.get('LENGTH', 'Long')).strip().lower(),
        needs_platform=freight_needs_platform if is_freight else True,
        direction=train_data.get('DIRECTION'),
        historical_platform=str(train_data.get('PLATFORM NO', '')).split(',')[0].strip(),
        zone=train_data.get('ZONE', 'SER')
    )

    available_platforms = get_available_platforms(frontend_platforms)
    ranked = calculate_platform_scores(incoming_train, available_platforms, incoming_line, BLOCKAGE_MATRIX)

    final = []
    for suggestion in ranked:
        pf_id = suggestion['platformId']
        display_id = f"Platform {pf_id.replace('P','')}" if pf_id.startswith('P') else f"Track {pf_id.replace('T','')}"
        final.append({
            'platformId': display_id,
            'score': suggestion['score'],
            'platformIds': [display_id],
            'blockages': suggestion.get('blockages', {})
        })

    top3 = [s['platformId'] for s in final[:3]]
    background_tasks.add_task(
        persist_report_update,
        train_no,
        {
            'trainName': train_data.get('TRAIN NAME', ''),
            'scheduled_arrival': train_data.get('ARRIVAL AT KGP', ''),
            'scheduled_departure': train_data.get('DEPARTURE FROM KGP', ''),
            'incoming_line': incoming_line,
            'top3_suggestions': top3,
        },
    )

    return {"suggestions": final}


@app.get("/api/incoming-lines")
async def get_incoming_lines():
    return INCOMING_LINES


# Note: Pydantic v2 removed __root__ on BaseModel; for free-form bodies we just use `dict` directly


@app.post("/api/add-train")
async def add_train(body: dict, background_tasks: BackgroundTasks):
    if trains_collection.find_one({"TRAIN NO": str(body.get('TRAIN NO'))}):
        raise HTTPException(status_code=409, detail=f"Train number {body.get('TRAIN NO')} already exists.")
    trains_collection.insert_one(body)
    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    arr = state.setdefault('arrivingTrains', [])
    arr.append({
        'trainNo': str(body['TRAIN NO']),
        'name': body['TRAIN NAME'],
        'scheduled_arrival': body.get('ARRIVAL AT KGP'),
        'scheduled_departure': body.get('DEPARTURE FROM KGP')
    })
    arr.sort(key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99')
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    background_tasks.add_task(log_action, f"TRAIN ADDED: New train {body['TRAIN NO']} added to the master schedule.")
    return {"message": f"Train {body['TRAIN NO']} added successfully."}


@app.post("/api/delete-train")
async def delete_train(body: dict, background_tasks: BackgroundTasks):
    train_no_to_delete = str(body.get('trainNo'))
    result = trains_collection.delete_one({"TRAIN NO": train_no_to_delete})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Train {train_no_to_delete} not found in master list.")
    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    state['arrivingTrains'] = [t for t in state.get('arrivingTrains', []) if str(t['trainNo']) != train_no_to_delete]
    state['waitingList'] = [t for t in state.get('waitingList', []) if str(t['trainNo']) != train_no_to_delete]
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    background_tasks.add_task(log_action, f"TRAIN DELETED: Train {train_no_to_delete} removed from the master schedule.")
    return {"message": f"Train {train_no_to_delete} deleted successfully."}


@app.post("/api/add-to-waiting-list")
async def add_to_waiting_list(body: dict, background_tasks: BackgroundTasks):
    train_no = body.get('trainNo')
    if not train_no:
        raise HTTPException(status_code=400, detail="Train number is required.")
    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    wl = state.setdefault('waitingList', [])
    if any(t['trainNo'] == train_no for t in wl):
        return {"message": f"Train {train_no} is already in the waiting list."}
    train_to_wait = next((t for t in state.get('arrivingTrains', []) if t['trainNo'] == train_no), None)
    if not train_to_wait:
        raise HTTPException(status_code=404, detail=f"Train {train_no} not found in arriving trains.")
    wl.append(train_to_wait)
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    background_tasks.add_task(log_action, f"WAITING: Train {train_no} added to the waiting list.")
    return {"message": f"Train {train_no} added to the waiting list."}


@app.post("/api/remove-from-waiting-list")
async def remove_from_waiting_list(body: dict, background_tasks: BackgroundTasks):
    train_no = body.get('trainNo')
    if not train_no:
        raise HTTPException(status_code=400, detail="Train number is required.")
    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    wl = state.get('waitingList', [])
    train_to_remove = next((t for t in wl if t['trainNo'] == train_no), None)
    if not train_to_remove:
        raise HTTPException(status_code=404, detail=f"Train {train_no} not found in the waiting list.")
    state['waitingList'] = [t for t in wl if t['trainNo'] != train_no]
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    background_tasks.add_task(log_action, f"WAITING LIST: Train {train_no} removed from waiting list.")
    return {"message": f"Train {train_no} removed from the waiting list."}


@app.post("/api/assign-platform")
async def assign_platform(body: dict, background_tasks: BackgroundTasks):
    train_no = body.get('trainNo')
    platform_ids_raw = body.get('platformIds')
    actual_arrival = body.get('actualArrival')
    platform_ids = [platform_ids_raw] if isinstance(platform_ids_raw, str) else platform_ids_raw

    state = state_collection.find_one({"_id": "current_station_state"}) or {}

    # Prefer waiting list
    wl_match = next((t for t in state.get('waitingList', []) if t.get('trainNo') == train_no), None)
    if wl_match:
        train_to_assign = wl_match
        from_wait = True
    else:
        train_to_assign = next((t for t in state.get('arrivingTrains', []) if t.get('trainNo') == train_no), None)
        from_wait = False
    if not train_to_assign:
        raise HTTPException(status_code=404, detail="Train not found in arriving or waiting lists.")

    train_data = trains_collection.find_one({"TRAIN NO": str(train_no)}) or {}
    stoppage_seconds = time_difference_seconds(train_data.get('ARRIVAL AT KGP'), train_data.get('DEPARTURE FROM KGP'))

    def find_partner(platform_name: str):
        m = re.match(r"^(Platform)\s*(\d+)([A-Za-z]*)$", platform_name)
        if not m:
            return None
        base, num_str, suffix = m.group(1), m.group(2), m.group(3) or ''
        try:
            num = int(num_str)
        except ValueError:
            return None
        partner_map = {1: 3, 2: 4, 3: 1, 4: 2}
        if num not in partner_map:
            return None
        partner_num = partner_map[num]
        return f"{base} {partner_num}{suffix}"

    is_long = str(train_data.get('LENGTH', '')).strip().lower() == 'long'
    if is_long and len(platform_ids) == 1:
        requested = platform_ids[0]
        partner = find_partner(requested)
        if partner:
            partner_obj = next((p for p in state.get('platforms', []) if p.get('id') == partner), None)
            if partner_obj and not partner_obj.get('isOccupied') and not partner_obj.get('isUnderMaintenance'):
                platform_ids = [requested, partner]
            else:
                raise HTTPException(status_code=400, detail=f"Partner platform {partner} is not available for long train assignment.")

    is_linked = len(platform_ids) > 1
    linked_map = {platform_ids[0]: platform_ids[1], platform_ids[1]: platform_ids[0]} if is_linked else {}

    for platform_id in platform_ids:
        for i, p in enumerate(state['platforms']):
            if p['id'] == platform_id:
                train_details = {"trainNo": train_to_assign['trainNo'], "name": train_to_assign['name']}
                if is_linked:
                    train_details['linkedPlatformId'] = linked_map[platform_id]
                state['platforms'][i]['isOccupied'] = True
                state['platforms'][i]['trainDetails'] = train_details
                state['platforms'][i]['actualArrival'] = actual_arrival
                if stoppage_seconds > 0:
                    timer = threading.Timer(stoppage_seconds, lambda: sse_broadcaster.put(
                        f"event: departure_alert\ndata: {json.dumps({'train_number': train_no, 'train_name': train_data.get('TRAIN NAME'), 'platform_id': platform_id})}\n\n"
                    ))
                    with timers_lock:
                        active_timers[platform_id] = timer
                    timer.start()
                break

    if from_wait:
        state['waitingList'] = [t for t in state.get('waitingList', []) if t['trainNo'] != train_no]

    background_tasks.add_task(
        log_action,
        f"ARRIVED & ASSIGNED: Train {train_no} arrived at {actual_arrival} and assigned to {', '.join(platform_ids)}."
    )
    background_tasks.add_task(
        persist_report_update,
        train_no,
        {
            'trainName': (train_data or {}).get('TRAIN NAME', ''),
            'scheduled_arrival': (train_data or {}).get('ARRIVAL AT KGP', ''),
            'scheduled_departure': (train_data or {}).get('DEPARTURE FROM KGP', ''),
            'actual_arrival': actual_arrival,
            'actual_platform': ', '.join(platform_ids),
        },
    )
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    return {"message": f"Train {train_no} assigned to {', '.join(platform_ids)}."}


@app.post("/api/unassign-platform")
async def unassign_platform(body: dict, background_tasks: BackgroundTasks):
    platform_id = body.get('platformId')
    state = state_collection.find_one({"_id": "current_station_state"}) or {}

    def _clear_platform(state, pid):
        platform_to_clear = next((p for p in state['platforms'] if p['id'] == pid), None)
        if not platform_to_clear or not platform_to_clear['isOccupied']:
            return None, None
        with timers_lock:
            if pid in active_timers:
                active_timers[pid].cancel()
                del active_timers[pid]
        train_details = platform_to_clear['trainDetails']
        linked_platform_id = train_details.get('linkedPlatformId') if train_details else None
        platform_to_clear['isOccupied'] = False
        platform_to_clear['trainDetails'] = None
        platform_to_clear['actualArrival'] = None
        return train_details, linked_platform_id

    train_details, linked_platform_id = _clear_platform(state, platform_id)
    if not train_details:
        raise HTTPException(status_code=404, detail="Platform not found or is not occupied.")
    cleared_platforms = [platform_id]
    if linked_platform_id:
        _clear_platform(state, linked_platform_id)
        cleared_platforms.append(linked_platform_id)

    # Persist state synchronously for immediate reflection; log in background
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    background_tasks.add_task(log_action, f"UNASSIGNED: Train {train_details['trainNo']} unassigned from {', '.join(cleared_platforms)} and returned to arrival list.")
    return {"message": f"Train {train_details['trainNo']} unassigned from {', '.join(cleared_platforms)}."}


@app.post("/api/depart-train")
async def depart_train(body: dict, background_tasks: BackgroundTasks):
    platform_id = body.get('platformId')
    state = state_collection.find_one({"_id": "current_station_state"}) or {}

    def _clear_platform(state, pid):
        platform_to_clear = next((p for p in state['platforms'] if p['id'] == pid), None)
        if not platform_to_clear or not platform_to_clear['isOccupied']:
            return None, None
        with timers_lock:
            if pid in active_timers:
                active_timers[pid].cancel()
                del active_timers[pid]
        train_details = platform_to_clear['trainDetails']
        linked_platform_id = train_details.get('linkedPlatformId') if train_details else None
        platform_to_clear['isOccupied'] = False
        platform_to_clear['trainDetails'] = None
        platform_to_clear['actualArrival'] = None
        return train_details, linked_platform_id

    train_details, linked_platform_id = _clear_platform(state, platform_id)
    if not train_details:
        raise HTTPException(status_code=404, detail="Platform not found or is not occupied.")
    cleared_platforms = [platform_id]
    if linked_platform_id:
        _clear_platform(state, linked_platform_id)
        cleared_platforms.append(linked_platform_id)

    departure_time = datetime.now().strftime('%H:%M')
    background_tasks.add_task(
        log_action,
        f"DEPARTED: Train {train_details['trainNo']} departed from {', '.join(cleared_platforms)} at {departure_time}."
    )
    background_tasks.add_task(persist_report_update, train_details['trainNo'], {'actual_departure': departure_time})
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    return {"message": f"Train {train_details['trainNo']} departed from {', '.join(cleared_platforms)}."}


@app.post("/api/log-depart-line")
async def log_depart_line(body: dict, background_tasks: BackgroundTasks):
    platform_id = body.get('platformId')
    line = body.get('line')
    if not platform_id or not line:
        raise HTTPException(status_code=400, detail="platformId and line required.")
    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    train_no = None
    try:
        for p in state.get('platforms', []):
            if p.get('id') == platform_id and p.get('isOccupied') and p.get('trainDetails'):
                train_no = str(p['trainDetails']['trainNo'])
                break
    except Exception:
        pass
    background_tasks.add_task(log_action, f"DEPART LINE: Train {train_no or ''} departing from {platform_id} via {line}.")
    if train_no:
        background_tasks.add_task(persist_report_update, train_no, {'outgoing_line': line})
    return {"message": "Departure line logged."}


@app.post("/api/toggle-maintenance")
async def toggle_maintenance(body: dict):
    platform_id = body.get('platformId')
    state = state_collection.find_one({"_id": "current_station_state"}) or {}

    status = None
    for i, p in enumerate(state.get('platforms', [])):
        if p.get('id') == platform_id:
            if state['platforms'][i]['isOccupied']:
                raise HTTPException(status_code=400, detail="Cannot change maintenance on an occupied platform.")
            state['platforms'][i]['isUnderMaintenance'] = not state['platforms'][i]['isUnderMaintenance']
            status = "ON" if state['platforms'][i]['isUnderMaintenance'] else "OFF"
            break

    log_action(f"MAINTENANCE: Maintenance for {platform_id} set to {status}.")
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    return {"message": f"Maintenance status toggled for {platform_id}."}


@app.get("/api/report/download")
async def download_report(date: str | None = None):
    date_str = date or _today_str()
    try:
        rows = list(reports_collection.find({"date": date_str}, {"_id": 0}).sort("trainNo", 1))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read reports: {e}")

    headers_list = [
        'date', 'trainNo', 'trainName', 'scheduled_arrival', 'scheduled_departure',
        'actual_arrival', 'actual_departure', 'top3_suggestions', 'actual_platform',
        'incoming_line', 'outgoing_line'
    ]

    def generate():
        yield ','.join(headers_list) + '\n'
        for r in rows:
            top3 = ', '.join(r.get('top3_suggestions', []) or [])
            values = [
                r.get('date', ''),
                str(r.get('trainNo', '')),
                (r.get('trainName', '') or '').replace(',', ' '),
                r.get('scheduled_arrival', '') or '',
                r.get('scheduled_departure', '') or '',
                r.get('actual_arrival', '') or '',
                r.get('actual_departure', '') or '',
                top3.replace(',', ';'),
                r.get('actual_platform', '') or '',
                r.get('incoming_line', '') or '',
                r.get('outgoing_line', '') or '',
            ]
            safe = []
            for v in values:
                s = str(v)
                if any(ch in s for ch in [',', '"', '\n']):
                    s = '"' + s.replace('"', '""') + '"'
                safe.append(s)
            yield ','.join(safe) + '\n'

    headers = {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{date_str}.csv"'
    }
    return StreamingResponse(generate(), headers=headers)


@app.get("/api/debug/push-alert")
async def debug_push_alert():
    try:
        sse_broadcaster.put(f"event: departure_alert\ndata: {json.dumps({'train_number': 'TEST-001', 'train_name': 'Debug Train', 'platform_id': 'Platform 1'})}\n\n")
        return {"message": "Debug departure_alert sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
