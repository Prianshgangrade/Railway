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
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
import certifi

# Local scoring utils
try:
    from .scoring_algorithm import ScoringTrain, get_available_platforms, calculate_platform_scores  # type: ignore
except Exception:
    from scoring_algorithm import ScoringTrain, get_available_platforms, calculate_platform_scores  # type: ignore

# Ensure we load the .env that lives in the parent 'api' folder even when
# this file is executed from elsewhere (e.g., project root with uvicorn)
_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
if os.path.exists(_ENV_PATH):
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    # Fallback to default lookup in current working directory
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
counters_collection = db['daily_counters']
suggestions_cache_collection = db['suggestions_cache']

API_DIR = os.path.dirname(__file__)
BLOCKAGE_MATRIX_FILE = os.path.join(API_DIR, 'Track Connections.xlsx - Tracks.csv')
BLOCKAGE_MATRIX = {}
INCOMING_LINES = []

# Incoming lines dropdown topology order (as provided by ops).
# The UI will display lines in the order returned by `/api/incoming-lines`.
TOPOLOGY_INCOMING_LINES = [
    'MDN DN Joint',
    'MDN UP Joint',
    'TATA DN',
    'East Coast DOWN Joint',
    'ADRA Joint',
    'TATA UP',
    'East Coast UP Joint',
    'HIJ Freight',
    'HWH DN',
    'HWH MID',
    'HWH UP',
]


def order_lines_by_topology(lines: list[str]) -> list[str]:
    """Return `lines` ordered by TOPOLOGY_INCOMING_LINES, appending unknowns.

    Matching is case-insensitive and trims whitespace. Known topology labels are
    returned in their canonical spelling from TOPOLOGY_INCOMING_LINES.
    """
    if not lines:
        return []

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", str(s or '').strip()).lower()

    available_norm = {}
    for raw in lines:
        n = _norm(raw)
        if not n:
            continue
        # keep first occurrence (preserve original list stability)
        available_norm.setdefault(n, str(raw).strip())

    ordered: list[str] = []
    used = set()
    for topo in TOPOLOGY_INCOMING_LINES:
        n = _norm(topo)
        if n in available_norm and n not in used:
            ordered.append(topo)
            used.add(n)

    # Append anything not in topology list (in the order it appeared).
    for raw in lines:
        n = _norm(raw)
        if not n or n in used:
            continue
        ordered.append(str(raw).strip())
        used.add(n)

    return ordered


def resolve_incoming_line_for_blockage_matrix(incoming_line: str | None) -> str:
    """Resolve UI incoming-line label to an existing BLOCKAGE_MATRIX key.

    The scoring algorithm does an exact dict lookup: `blockage_matrix.get(incoming_line)`.
    If the UI label differs from the matrix key (e.g., 'HWH MID' vs 'HWH MD',
    'DOWN' vs 'DN'), no routes are found and suggestions come back empty.

    This resolver keeps UI labels unchanged, but maps them to a best-match
    matrix key for scoring.
    """
    raw = str(incoming_line or '').strip()
    if not raw:
        return ''
    if raw in BLOCKAGE_MATRIX:
        return raw

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", str(s or '').strip()).lower()

    # Build a normalized lookup table of matrix keys.
    norm_to_key: dict[str, str] = {}
    try:
        for k in (BLOCKAGE_MATRIX or {}).keys():
            ks = str(k or '').strip()
            if not ks:
                continue
            norm_to_key.setdefault(_norm(ks), ks)
    except Exception:
        norm_to_key = {}

    n = _norm(raw)

    _alias_map = {
        'mdn dn joint': 'MDN MD 1',
        'mdn up joint': 'MDN MD 2',
        'east coast down joint': 'HIJ MD 1 (DN)',
        'east coast up joint': 'HIJ MD 2 (UP)',
        'adra joint': 'TATA MD',
    }
    aliased = _alias_map.get(n)
    if aliased:
        if aliased in BLOCKAGE_MATRIX:
            return aliased
        an = _norm(aliased)
        if an in norm_to_key:
            return norm_to_key[an]

    if n in norm_to_key:
        return norm_to_key[n]

    def _swap_word(s: str, src: str, dst: str) -> str:
        return re.sub(rf"\b{re.escape(src)}\b", dst, s, flags=re.IGNORECASE)

    # Try a small set of safe token aliases used in ops naming.
    candidates = {
        raw,
        _swap_word(raw, 'MID', 'MD'),
        _swap_word(raw, 'MD', 'MID'),
        _swap_word(raw, 'DOWN', 'DN'),
        _swap_word(raw, 'DN', 'DOWN'),
    }
    for cand in list(candidates):
        candidates.add(re.sub(r"\s+", " ", str(cand).strip()))

    for cand in candidates:
        if cand in BLOCKAGE_MATRIX:
            return cand
        cn = _norm(cand)
        if cn in norm_to_key:
            return norm_to_key[cn]

    return raw


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for v in values:
        s = str(v).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _prefer_lines_matching_matrix(values: list[str]) -> list[str]:
    """If blockage matrix is loaded, prefer lines that exist in it."""
    cleaned = _dedupe_preserve_order([str(v).strip() for v in (values or [])])
    if not cleaned or not BLOCKAGE_MATRIX:
        return cleaned
    allowed = set(BLOCKAGE_MATRIX.keys())
    filtered = [v for v in cleaned if v in allowed]
    return filtered if filtered else cleaned


def _find_track_connections_collection_name() -> str | None:
    """Locate the Mongo collection that stores the blockage matrix rows.

    In your DB this is typically named similar to:
    'Track Connections.xlsx - Tracks.csv' or 'Track Connections.xlsx - Tracks'.
    """
    try:
        names = db.list_collection_names()
    except Exception:
        return None

    preferred = [
        'Track Connections.xlsx - Tracks.csv',
        'Track Connections.xlsx - Tracks',
        'Track Connections',
        'track_connections',
        'trackConnections',
    ]
    for name in preferred:
        if name in names:
            return name

    # Best-effort fuzzy match
    for name in names:
        if 'Track Connections' in name and 'Track' in name:
            return name
    return None


def load_incoming_lines_from_mongo() -> list[str]:
    """Load the incoming line labels from Mongo.

    Supported shapes:
    A) Track-connections/blockage collection with one doc per line and a field 'INCOMING'.
    B) Fallback collection 'incoming_lines' (older shape) with either a config doc or one-doc-per-line.
    """
    # Shape A: track connections collection
    try:
        coll_name = _find_track_connections_collection_name()
        if coll_name:
            coll = db.get_collection(coll_name)
            for field in ('INCOMING', 'incoming', 'Incoming'):
                vals = coll.distinct(field)
                if vals:
                    return _prefer_lines_matching_matrix([str(v) for v in vals])
    except Exception:
        pass

    # Shape B: older dedicated collection
    try:
        coll = db.get_collection('incoming_lines')

        doc = coll.find_one({'_id': 'incoming_lines'}, {'_id': 0}) or {}
        for key in ('lines', 'incomingLines', 'incoming_lines', 'values'):
            val = doc.get(key)
            if isinstance(val, list) and val:
                return _prefer_lines_matching_matrix([str(v) for v in val])

        for field in ('name', 'line'):
            vals = coll.distinct(field)
            if vals:
                return _prefer_lines_matching_matrix([str(v) for v in vals])
    except Exception:
        pass

    return []


def load_blockage_matrix_from_mongo() -> tuple[dict, list[str]]:
    """Load blockage matrix and incoming line list from Mongo track-connections collection."""
    coll_name = _find_track_connections_collection_name()
    if not coll_name:
        return {}, []

    try:
        coll = db.get_collection(coll_name)
        docs = list(coll.find({}, {'_id': 0}))
    except Exception:
        return {}, []

    matrix: dict = {}
    lines: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        incoming = doc.get('INCOMING') or doc.get('incoming') or doc.get('Incoming') or doc.get('incoming_line') or doc.get('incomingLine')
        if not incoming:
            continue
        incoming_line = str(incoming).strip()
        if not incoming_line:
            continue
        lines.append(incoming_line)
        row = {}
        for key, val in doc.items():
            header = str(key or '').strip()
            if not header:
                continue
            if header.upper() in {'INCOMING', 'INCOMING_LINE', 'INCOMINGLINE'}:
                continue
            cell = str(val or '').strip()
            if not cell:
                continue
            row[header] = parse_blockage_cell(cell)
        matrix[incoming_line] = row

    lines = _dedupe_preserve_order(lines)
    return matrix, lines

TRACK_LABELS = {
    'Track 1': 'Cuttack 2',
    'Track 2': 'Cuttack 5',
    'Track 3': 'Cuttack 6',
    'Track 4': 'Midnapore 9',
    'Track 5': 'Midnapore 10',
    'Track 6': 'Midnapore 11',
}
ALLOWED_TRACK_IDS = set(TRACK_LABELS.keys())

# Business rule helpers (keep scoring_algorithm unchanged)
SHORT_SINGLE_PLATFORM_IDS = {
    'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8',
    'P1A', 'P2A', 'P3A', 'P4A',
}

# Long trains can be suggested on these as single platforms.
LONG_SINGLE_PLATFORM_IDS = {'P5', 'P6', 'P7', 'P8'}

# --- Train metadata cache (cuts round trips to Mongo for every suggestion/assignment) ---
TRAIN_CACHE: dict[str, dict] = {}
train_cache_lock = threading.Lock()


def refresh_train_cache():
    """Warm the in-memory cache with all train docs. Called at startup and after bulk updates."""
    try:
        docs = list(trains_collection.find({}, {'_id': 0}))
    except Exception as exc:
        log_action(f"TRAIN_CACHE: initial load failed {exc}")
        docs = []
    with train_cache_lock:
        TRAIN_CACHE.clear()
        for doc in docs:
            train_no = str(doc.get('TRAIN NO') or doc.get('trainNo') or '')
            if train_no:
                TRAIN_CACHE[train_no] = doc


def cache_train_doc(train_doc: dict):
    if not train_doc:
        return
    train_no = str(train_doc.get('TRAIN NO') or train_doc.get('trainNo') or '')
    if not train_no:
        return
    with train_cache_lock:
        TRAIN_CACHE[train_no] = train_doc


def remove_from_train_cache(train_no: str | None):
    if not train_no:
        return
    with train_cache_lock:
        TRAIN_CACHE.pop(str(train_no), None)


def get_train_record(train_no: str | None, force_db: bool = False) -> dict:
    if not train_no:
        return {}
    train_no = str(train_no)
    if not force_db:
        with train_cache_lock:
            cached = TRAIN_CACHE.get(train_no)
        if cached:
            return cached
    doc = trains_collection.find_one({"TRAIN NO": train_no}) or {}
    if doc:
        cache_train_doc(doc)
    return doc

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


PLATFORM_NUMBER_REGEX = re.compile(r'(\d+[A-Za-z]*)')


def normalize_platform_label(label: str | None) -> str:
    """Extract the numeric/alpha suffix from labels like 'Platform 1A' or 'Track 5'."""
    if not label:
        return ''
    match = PLATFORM_NUMBER_REGEX.search(str(label))
    if match:
        return match.group(1).strip()
    return str(label).strip()


def normalize_platform_labels(labels: list[str] | None) -> list[str]:
    if not labels:
        return []
    return [normalize_platform_label(lbl) for lbl in labels if lbl]


def find_partner_platform_id(platform_name: str | None) -> str | None:
    """Resolve the paired platform for long-train assignments (e.g., Platform 1 ↔ Platform 3)."""
    if not platform_name:
        return None
    m = re.match(r"^(Platform)\s*(\d+)([A-Za-z]*)$", platform_name.strip())
    if not m:
        return None
    base, num_str, suffix = m.group(1), m.group(2), m.group(3) or ''
    try:
        num = int(num_str)
    except ValueError:
        return None
    partner_map = {1: 3, 2: 4, 3: 1, 4: 2}
    partner_num = partner_map.get(num)
    if partner_num is None:
        return None
    return f"{base} {partner_num}{suffix}".strip()


def coerce_label_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [part.strip() for part in value.split(',') if part.strip()]
    return [str(value)]


def log_action(action_string: str):
    # Persist to Mongo
    entry = {"timestamp": datetime.now(), "action": action_string}
    try:
        logs_collection.insert_one(entry)
    except Exception:
        pass
    # Also append to text operations log for quick inspection
    try:
        log_path = os.path.join(API_DIR, '..', 'operations_log.txt')
        # operations_log.txt historically is at api/operations_log.txt; ensure path
        if not os.path.isabs(log_path):
            log_path = os.path.join(API_DIR, 'operations_log.txt')
        with open(log_path, 'a', encoding='utf-8') as lf:
            lf.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {action_string}\n")
    except Exception:
        pass


refresh_train_cache()


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
    """Update the latest daily report entry and schedule CSV generation.

    Notes:
    - We keep *multiple* entries per train per day (each assignment creates a new entry).
    - This helper updates the most recent entry for the train/day (used for depart/outgoing-line/unassign).
    """
    try:
        upsert_daily_report(train_no, update_fields)
        schedule_csv_write(_today_str())
    except Exception:
        pass


def persist_report_entry(train_no: str, entry_fields: dict):
    """Append a new daily report entry and schedule CSV generation.

    Used for ASSIGN / REASSIGN events where a new CSV row is required.
    """
    try:
        append_daily_report_entry(train_no, entry_fields)
        schedule_csv_write(_today_str())
    except Exception:
        pass


def persist_report_update_if_exists(train_no: str, update_fields: dict):
    """Update the latest report entry only if one already exists.

    This is used for non-state-changing actions like computing suggestions, where
    we do not want to create a standalone report row.
    """
    try:
        updated = update_latest_daily_report_if_exists(train_no, update_fields)
        if updated:
            schedule_csv_write(_today_str())
    except Exception:
        pass


def get_next_freight_tag(date_str: str | None = None) -> str:
    """Atomically generate the next freight identifier for the given day (F1, F2, ...)."""
    date_key = date_str or _today_str()
    doc = counters_collection.find_one_and_update(
        {"date": date_key},
        {"$inc": {"freight_counter": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    counter_val = int(doc.get('freight_counter', 1))
    return f"F{counter_val}"


def upsert_daily_report(train_no, update_fields, date_str=None):
    if not train_no:
        return
    date_key = date_str or _today_str()

    # Update only the most recent entry for this train/day.
    # If none exists yet (older data / edge cases), create a baseline entry.
    query = {"date": date_key, "trainNo": str(train_no)}
    latest = None
    try:
        latest = reports_collection.find_one(query, sort=[('event_time', -1), ('_id', -1)])
    except Exception:
        latest = reports_collection.find_one(query)

    if latest and latest.get('_id') is not None:
        reports_collection.update_one(
            {"_id": latest['_id']},
            {"$set": {**update_fields, "date": date_key, "trainNo": str(train_no)}},
            upsert=False,
        )
        return

    # No existing entry; create one so updates aren't lost.
    doc = {**update_fields, "date": date_key, "trainNo": str(train_no)}
    doc.setdefault('event_time', datetime.utcnow().isoformat())
    reports_collection.insert_one(doc)


def update_latest_daily_report_if_exists(train_no, update_fields, date_str=None):
    """Update the latest entry for the train/day; no insert if missing."""
    if not train_no:
        return False
    date_key = date_str or _today_str()
    query = {"date": date_key, "trainNo": str(train_no)}
    latest = None
    try:
        latest = reports_collection.find_one(query, sort=[('event_time', -1), ('_id', -1)])
    except Exception:
        latest = reports_collection.find_one(query)
    if not latest or latest.get('_id') is None:
        return False
    reports_collection.update_one(
        {"_id": latest['_id']},
        {"$set": {**(update_fields or {}), "date": date_key, "trainNo": str(train_no)}},
        upsert=False,
    )
    return True


def persist_suggestions_snapshot(train_no: str, suggestion_fields: dict):
    """Persist suggestions for a train without creating a standalone report row.

    - If a report entry already exists, update the latest entry.
    - Also cache it for the next assignment/reassignment entry.
    """
    if not train_no:
        return
    date_key = _today_str()
    fields = suggestion_fields or {}
    try:
        updated = update_latest_daily_report_if_exists(train_no, fields, date_key)
    except Exception:
        updated = False

    # Always upsert the cache so the next assignment row can merge suggestions,
    # even when a report entry already exists (e.g., train moved to waiting list and reassigned).
    try:
        suggestions_cache_collection.update_one(
            {"date": date_key, "trainNo": str(train_no)},
            {
                "$set": {
                    **fields,
                    "date": date_key,
                    "trainNo": str(train_no),
                    "updated_at": datetime.utcnow().isoformat(),
                }
            },
            upsert=True,
        )
    except Exception:
        pass

    # If we updated the latest report entry too, schedule CSV generation.
    if updated:
        try:
            schedule_csv_write(date_key)
        except Exception:
            pass


def persist_assignment_report_entry(train_no: str, entry_fields: dict):
    """Insert a new assignment/reassignment report entry.

    If suggestions were computed before assignment, merge cached suggestions into
    this entry so the CSV row includes them.
    """
    if not train_no:
        return
    date_key = _today_str()
    merged = dict(entry_fields or {})
    try:
        cached = suggestions_cache_collection.find_one({"date": date_key, "trainNo": str(train_no)}, {"_id": 0})
    except Exception:
        cached = None
    if cached:
        # Only set if not already provided by caller
        if 'suggestions' not in merged and cached.get('suggestions'):
            merged['suggestions'] = cached.get('suggestions')
        if 'incoming_line' not in merged and cached.get('incoming_line'):
            merged['incoming_line'] = cached.get('incoming_line')

    append_daily_report_entry(train_no, merged, date_key)

    # Clear cache after successful insert so next assignment starts fresh
    try:
        suggestions_cache_collection.delete_one({"date": date_key, "trainNo": str(train_no)})
    except Exception:
        pass

    try:
        schedule_csv_write(date_key)
    except Exception:
        pass


def get_latest_report_entry_for_today(train_no: str) -> dict | None:
    """Fetch the latest report entry for a train for today (if any)."""
    if not train_no:
        return None
    date_key = _today_str()
    query = {"date": date_key, "trainNo": str(train_no)}
    try:
        return reports_collection.find_one(query, {"_id": 0}, sort=[('event_time', -1), ('_id', -1)])
    except Exception:
        try:
            doc = reports_collection.find_one(query, sort=[('event_time', -1), ('_id', -1)])
            if doc and '_id' in doc:
                doc.pop('_id', None)
            return doc
        except Exception:
            return None


def append_daily_report_entry(train_no, entry_fields, date_str=None):
    """Insert a new report entry (new CSV row) for this train/day."""
    if not train_no:
        return
    date_key = date_str or _today_str()
    doc = {**(entry_fields or {}), "date": date_key, "trainNo": str(train_no)}
    doc.setdefault('event_time', datetime.utcnow().isoformat())
    # For assignment entries we keep Remarks empty unless explicitly provided.
    if 'Remarks' not in doc:
        doc['Remarks'] = ''
    reports_collection.insert_one(doc)


def write_csv_for_date(date_str):
    try:
        rows = list(
            reports_collection
            .find({"date": date_str}, {"_id": 0})
            .sort([("trainNo", 1), ("event_time", 1)])
        )
        csv_path = os.path.join(API_DIR, 'reports', f"{date_str}.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        headers = [
            'date', 'trainNo', 'trainName', 'scheduled_arrival', 'scheduled_departure',
            'actual_arrival', 'actual_departure', 'actual_platform_arrival', 'suggestions', 'actual_platform',
            'incoming_line', 'outgoing_line', 'Remarks' 
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            import csv as _csv
            writer = _csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for r in rows:
                suggestions_field = r.get('suggestions')
                if not suggestions_field:
                    suggestions_field = r.get('top3_suggestions', [])
                normalized_suggestions = normalize_platform_labels(coerce_label_list(suggestions_field))
                actual_platform_field = r.get('actual_platform', '')
                normalized_actual_platform = ', '.join(normalize_platform_labels(coerce_label_list(actual_platform_field))) if actual_platform_field else ''
                writer.writerow({
                    'date': r.get('date', ''),
                    'trainNo': r.get('trainNo', ''),
                    'trainName': r.get('trainName', ''),
                    'scheduled_arrival': r.get('scheduled_arrival', ''),
                    'scheduled_departure': r.get('scheduled_departure', ''),
                    'actual_arrival': r.get('actual_arrival', ''),
                    'actual_departure': r.get('actual_departure', ''),
                    'actual_platform_arrival': r.get('actual_platform_arrival', ''),
                    'suggestions': ', '.join(normalized_suggestions),
                    'actual_platform': normalized_actual_platform,
                    'incoming_line': r.get('incoming_line', ''),
                    'outgoing_line': r.get('outgoing_line', ''),
                    'Remarks': r.get('Remarks', ''),
                })
    except Exception:
        pass


def enforce_track_layout(state: dict) -> dict:
    """Ensure only allowed tracks exist and attach friendly display names."""
    if not state:
        return state
    platforms = state.get('platforms', []) or []
    waiting = state.setdefault('waitingList', []) or []
    waiting_nos = {str(item.get('trainNo')) for item in waiting if item.get('trainNo')}
    normalized = []
    changed = False
    for entry in platforms:
        pid = entry.get('id') if isinstance(entry, dict) else None
        if pid and pid.startswith('Track'):
            if pid not in ALLOWED_TRACK_IDS:
                train_details = entry.get('trainDetails') if isinstance(entry, dict) else None
                train_no = str(train_details.get('trainNo')) if train_details and train_details.get('trainNo') else None
                if train_no and train_no not in waiting_nos:
                    waiting.append({
                        'trainNo': train_no,
                        'name': train_details.get('name'),
                        'enqueued_at': datetime.now().astimezone().isoformat(),
                        'actualArrival': entry.get('actualArrival'),
                        'incoming_line': train_details.get('incomingLine') or train_details.get('incoming_line') or ''
                    })
                    waiting_nos.add(train_no)
                changed = True
                continue
            friendly = TRACK_LABELS.get(pid)
            if friendly and entry.get('displayName') != friendly:
                entry = dict(entry)
                entry['displayName'] = friendly
                changed = True
        normalized.append(entry)
    if changed:
        state['platforms'] = normalized
        # Keep waiting list FCFS ordered by enqueued_at
        try:
            def _wl_key(item: dict):
                enq = item.get('enqueued_at') or ''
                try:
                    dt = datetime.fromisoformat(enq)
                    return (dt.timestamp(), str(item.get('trainNo') or ''))
                except Exception:
                    return (enq, str(item.get('trainNo') or ''))
            waiting.sort(key=_wl_key)
        except Exception:
            pass
        state['waitingList'] = waiting
        try:
            state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
        except Exception:
            pass
    return state


def _default_platforms() -> list[dict]:
    """Fallback platform list if Mongo "platforms" master is missing."""
    platform_ids = [
        'Platform 1', 'Platform 2', 'Platform 3', 'Platform 4',
        'Platform 1A', 'Platform 2A', 'Platform 3A', 'Platform 4A',
        'Platform 5', 'Platform 6', 'Platform 7', 'Platform 8',
    ]
    track_ids = sorted(list(ALLOWED_TRACK_IDS))
    ids = platform_ids + track_ids
    return [
        {
            'id': pid,
            'isOccupied': False,
            'trainDetails': None,
            'isUnderMaintenance': False,
            'actualArrival': None,
        }
        for pid in ids
    ]


def _build_initial_platforms_from_master() -> list[dict]:
    """Build initial platforms list from Mongo platforms master; fall back to defaults."""
    try:
        platforms_master_raw = list(platforms_collection.find({}, {'_id': 0}))
        if len(platforms_master_raw) == 1 and isinstance(platforms_master_raw[0], dict) and 'tracks' in platforms_master_raw[0]:
            platforms_master = platforms_master_raw[0].get('tracks') or []
        else:
            platforms_master = platforms_master_raw

        initial_platforms: list[dict] = []
        for track_data in platforms_master:
            if not isinstance(track_data, dict):
                continue
            is_platform = bool(track_data.get('is_platform', False))
            raw_id = str(track_data.get('id', '') or '')
            if not raw_id:
                continue
            item_id = raw_id.replace('P', '').replace('T', '')
            initial_platforms.append({
                'id': f"Platform {item_id}" if is_platform else f"Track {item_id}",
                'isOccupied': False,
                'trainDetails': None,
                'isUnderMaintenance': False,
                'actualArrival': None
            })

        # Keep only tracks we actually support in UI (Track 1–6)
        if initial_platforms:
            initial_platforms = [
                p for p in initial_platforms
                if not str(p.get('id', '')).startswith('Track') or p.get('id') in ALLOWED_TRACK_IDS
            ]
        return initial_platforms or _default_platforms()
    except Exception:
        return _default_platforms()


def _ensure_state_platforms_present(state: dict | None = None) -> dict:
    """Ensure station_state has a non-empty platforms list (repairs accidental empty array)."""
    if state is None:
        state = state_collection.find_one({"_id": "current_station_state"}) or {}
    if state.get('platforms'):
        return state

    platforms_list = _build_initial_platforms_from_master()
    state['platforms'] = platforms_list
    try:
        state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    except Exception:
        pass
    return state


# ---------- FastAPI lifecycle ----------

@app.on_event("startup")
async def startup_event():
    global BLOCKAGE_MATRIX, INCOMING_LINES
    # Prefer MongoDB for blockage matrix + incoming lines when available.
    mongo_matrix, mongo_lines = load_blockage_matrix_from_mongo()
    if mongo_matrix and mongo_lines:
        BLOCKAGE_MATRIX, INCOMING_LINES = mongo_matrix, mongo_lines
    else:
        BLOCKAGE_MATRIX, INCOMING_LINES = load_blockage_matrix()
        # If only the line list exists in Mongo, use it for dropdowns.
        try:
            mongo_only_lines = load_incoming_lines_from_mongo()
            if mongo_only_lines:
                INCOMING_LINES = mongo_only_lines
        except Exception:
            pass
    # Ensure helpful indexes exist (idempotent)
    # NOTE: Reports now allow multiple entries per train per day (reassign creates a new row),
    # so we must NOT keep the old unique (date, trainNo) index.
    try:
        info = reports_collection.index_information() or {}
        for idx_name, spec in info.items():
            try:
                if not spec.get('unique'):
                    continue
                keys = spec.get('key') or []
                if keys == [('date', 1), ('trainNo', 1)]:
                    reports_collection.drop_index(idx_name)
            except Exception:
                pass
        reports_collection.create_index([('date', 1), ('trainNo', 1), ('event_time', 1)])
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

    # Repair if state exists but platforms list is empty
    try:
        _ensure_state_platforms_present()
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
    state = _ensure_state_platforms_present()
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
    state = enforce_track_layout(state)
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

    train_data = get_train_record(str(train_no))
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
    frontend_platforms = frontend_platforms or []
    is_long = str(train_data.get('LENGTH', '')).strip().lower() == 'long'

    # Enforce business rules (keep scoring_algorithm unchanged):
    # - Short trains: can use any single platform (1–8 + 1A–4A).
    # - Long trains: paired options (1+3 or 2+4) OR single platforms 5–8.
    if is_long:
        long_candidates = {pid for pid in available_platforms if pid in LONG_SINGLE_PLATFORM_IDS}
        if 'P1' in available_platforms and 'P3' in available_platforms:
            long_candidates.add('P1')
        if 'P2' in available_platforms and 'P4' in available_platforms:
            long_candidates.add('P2')
        available_platforms = long_candidates
    else:
        available_platforms = {pid for pid in available_platforms if pid in SHORT_SINGLE_PLATFORM_IDS}

    # HIJ Freight is a special incoming line that should not depend on blockage matrix.
    # If the matrix lacks a row for it, we still want to suggest available platforms.
    incoming_norm = re.sub(r"\s+", " ", str(incoming_line or '').strip()).lower()
    if incoming_norm == 'hij freight':
        def _sort_pf(pid: str):
            s = str(pid or '')
            m = re.match(r'^([PT])(\d+)([A-Za-z]*)$', s)
            if not m:
                return (9, 9999, s)
            kind = 0 if m.group(1) == 'P' else 1
            num = int(m.group(2))
            suf = m.group(3) or ''
            return (kind, num, suf)

        ranked = [{'platformId': pid, 'score': 0.0} for pid in sorted(available_platforms, key=_sort_pf)]
    else:
        scoring_incoming_line = resolve_incoming_line_for_blockage_matrix(incoming_line)
        ranked = calculate_platform_scores(incoming_train, available_platforms, scoring_incoming_line, BLOCKAGE_MATRIX)

    final = []
    for suggestion in ranked:
        pf_id = suggestion['platformId']
        display_id = f"Platform {pf_id.replace('P','')}" if pf_id.startswith('P') else f"Track {pf_id.replace('T','')}"
        combined_ids = [display_id]
        if is_long and display_id.startswith('Platform'):
            partner_id = find_partner_platform_id(display_id)
            if partner_id:
                partner_entry = next((p for p in frontend_platforms if p.get('id') == partner_id), None)
                if partner_entry and not partner_entry.get('isOccupied') and not partner_entry.get('isUnderMaintenance'):
                    if partner_id not in combined_ids:
                        combined_ids.append(partner_id)
        # Preserve historical-match metadata from scorer (if present)
        final.append({
            'platformId': display_id,
            'score': suggestion['score'],
            'platformIds': combined_ids,
            'blockages': None if not is_long else suggestion.get('blockages', {}),
            'historicalMatch': suggestion.get('historicalMatch', False),
            'historicalPlatform': suggestion.get('historicalPlatform')
        })

    all_suggestions = [s['platformId'] for s in final]
    normalized_suggestions = normalize_platform_labels(all_suggestions)
    # IMPORTANT: generating suggestions should not create its own report row.
    # If an assignment entry exists, update it; otherwise cache for the next assignment.
    background_tasks.add_task(
        persist_suggestions_snapshot,
        train_no,
        {
            'incoming_line': incoming_line,
            'suggestions': normalized_suggestions,
        },
    )

    return {"suggestions": final}


@app.get("/api/incoming-lines")
async def get_incoming_lines():
    # IMPORTANT: The UI dropdown should use the hardcoded topology list only.
    # We intentionally ignore Mongo/CSV here to keep the order deterministic.
    return list(TOPOLOGY_INCOMING_LINES)


# Note: Pydantic v2 removed __root__ on BaseModel; for free-form bodies we just use `dict` directly


@app.post("/api/add-train")
async def add_train(body: dict, background_tasks: BackgroundTasks):
    if trains_collection.find_one({"TRAIN NO": str(body.get('TRAIN NO'))}):
        raise HTTPException(status_code=409, detail=f"Train number {body.get('TRAIN NO')} already exists.")
    trains_collection.insert_one(body)
    cache_train_doc(body)
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
    remove_from_train_cache(train_no_to_delete)
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
    if any(str(t.get('trainNo')) == str(train_no) for t in wl):
        return {"message": f"Train {train_no} is already in the waiting list."}
    train_to_wait = next((t for t in state.get('arrivingTrains', []) if str(t['trainNo']) == str(train_no)), None)
    if not train_to_wait:
        raise HTTPException(status_code=404, detail=f"Train {train_no} not found in arriving trains.")

    # For richer logging/report updates, try to capture the last known assigned platform from the report.
    latest_report = get_latest_report_entry_for_today(str(train_no))
    previous_platform = ''
    try:
        previous_platform = (latest_report or {}).get('actual_platform') or ''
    except Exception:
        previous_platform = ''
    # prepare waiting entry with enqueue timestamp and actualArrival if provided
    # Use local timezone time (not UTC) so logs match the operator clock.
    # Keep ISO format (24-hour) and include offset like +05:30.
    enqueued_at = datetime.now().astimezone().isoformat()
    actual_arrival = body.get('actualArrival') or train_to_wait.get('scheduled_arrival') or None
    incoming_line = body.get('incomingLine') or ''
    waiting_entry = {
        'trainNo': str(train_to_wait['trainNo']),
        'name': train_to_wait.get('name'),
        'enqueued_at': enqueued_at,
        'actualArrival': actual_arrival,
        'incoming_line': incoming_line,
    }
    wl.append(waiting_entry)
    # FCFS: whoever entered the waiting list first stays on top
    def _wl_key(item: dict):
        enq = item.get('enqueued_at') or ''
        try:
            dt = datetime.fromisoformat(enq)
            return (dt.timestamp(), str(item.get('trainNo') or ''))
        except Exception:
            return (enq, str(item.get('trainNo') or ''))

    wl.sort(key=_wl_key)
    state['waitingList'] = wl
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)

    # Update the latest existing report row (do NOT create a new row) to mark this move.
    background_tasks.add_task(persist_report_update_if_exists, str(train_no), {'Remarks': 'waiting list'})

    prev_pf_part = f" (previousPlatform: {previous_platform})" if previous_platform else ""
    background_tasks.add_task(
        log_action,
        f"WAITING LIST: Train {train_no} moved to waiting list at {enqueued_at} (actualArrival: {actual_arrival}) (incoming: {incoming_line}).{prev_pf_part}"
    )
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
    # (No auto-suggestion trigger on waiting list removal per updated requirement.)
    return {"message": f"Train {train_no} removed from the waiting list."}


@app.post("/api/assign-platform")
async def assign_platform(body: dict, background_tasks: BackgroundTasks):
    train_no = body.get('trainNo')
    platform_ids_raw = body.get('platformIds')
    actual_arrival = body.get('actualArrival')
    platform_ids = [platform_ids_raw] if isinstance(platform_ids_raw, str) else platform_ids_raw
    provided_incoming_line = body.get('incomingLine') or body.get('incoming_line')
    requested_train_name = body.get('trainName')
    force_freight = body.get('forceCreateFreight') or body.get('isFreight')

    if not platform_ids:
        raise HTTPException(status_code=400, detail="platformIds are required for assignment.")

    state = state_collection.find_one({"_id": "current_station_state"}) or {}

    assignment_time_hhmm = datetime.now().strftime('%H:%M')

    # Prefer waiting list
    wl_match = next((t for t in state.get('waitingList', []) if t.get('trainNo') == train_no), None)
    generated_freight = False
    if wl_match:
        train_to_assign = wl_match
        from_wait = True
    else:
        train_to_assign = next((t for t in state.get('arrivingTrains', []) if t.get('trainNo') == train_no), None)
        from_wait = False
    if not train_to_assign:
        if not train_no or force_freight or requested_train_name:
            train_no = train_no or get_next_freight_tag()
            train_to_assign = {
                'trainNo': str(train_no),
                'name': requested_train_name or f"Freight {train_no}",
                'incoming_line': provided_incoming_line or ''
            }
            generated_freight = True
            from_wait = False
        else:
            raise HTTPException(status_code=404, detail="Train not found in arriving or waiting lists.")

    train_data = get_train_record(str(train_no))
    if not train_data and generated_freight:
        train_data = {
            'TRAIN NAME': train_to_assign.get('name'),
            'ARRIVAL AT KGP': actual_arrival,
            'DEPARTURE FROM KGP': None,
            'LENGTH': body.get('length') or 'medium'
        }

    if provided_incoming_line and not train_to_assign.get('incoming_line'):
        train_to_assign['incoming_line'] = provided_incoming_line

    # If assigning from waiting list, CSV should record a NEW actual arrival time for the new row.
    # Keep UI/state `actualArrival` populated for display, but ensure report uses the new value.
    actual_arrival_for_state = actual_arrival or assignment_time_hhmm
    actual_arrival_for_report = assignment_time_hhmm if from_wait else actual_arrival_for_state

    latest_report = get_latest_report_entry_for_today(str(train_no))
    previous_platform = ''
    try:
        previous_platform = (latest_report or {}).get('actual_platform') or ''
    except Exception:
        previous_platform = ''
    stoppage_seconds = time_difference_seconds(train_data.get('ARRIVAL AT KGP'), train_data.get('DEPARTURE FROM KGP'))

    is_long = str(train_data.get('LENGTH', '')).strip().lower() == 'long'
    if is_long and len(platform_ids) == 1:
        requested = platform_ids[0]
        partner = find_partner_platform_id(requested)
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
                # Include incoming line if available (prefer waiting list's stored value, else provided from frontend)
                incoming_line_val = train_to_assign.get('incoming_line') or provided_incoming_line
                # Mark the first platform in platform_ids as the primary (the one the user requested).
                is_primary = (platform_id == platform_ids[0])
                train_details = {"trainNo": train_to_assign['trainNo'], "name": train_to_assign['name']}
                if incoming_line_val:
                    train_details['incomingLine'] = incoming_line_val
                if is_linked:
                    train_details['linkedPlatformId'] = linked_map[platform_id]
                if is_primary:
                    train_details['isPrimary'] = True
                state['platforms'][i]['isOccupied'] = True
                state['platforms'][i]['trainDetails'] = train_details
                state['platforms'][i]['actualArrival'] = actual_arrival_for_state
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
        background_tasks.add_task(log_action, f"WAITING LIST: Train {train_no} removed from waiting list (assigned to platform).")

    # record actual platform arrival timestamp
    # Record platform berth time in HH:MM for consistency with other timestamps
    actual_platform_arrival = assignment_time_hhmm
    for platform_id in platform_ids:
        for p in state.get('platforms', []):
            if p.get('id') == platform_id and p.get('isOccupied') and p.get('trainDetails') and p['trainDetails'].get('trainNo') == train_no:
                p['trainDetails']['actualPlatformArrival'] = actual_platform_arrival
                p['actualPlatformArrival'] = actual_platform_arrival
                break
    # persist state synchronously, log and persist report in background
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    train_name_for_report = train_to_assign.get('name') or (train_data or {}).get('TRAIN NAME', '')

    if from_wait:
        prev_pf_part = f" (previousPlatform: {previous_platform})" if previous_platform else ""
        background_tasks.add_task(
            log_action,
            f"ASSIGNED FROM WAITING LIST: Train {train_no} assigned to {', '.join(platform_ids)} at {actual_platform_arrival} (newActualArrival: {actual_arrival_for_report}).{prev_pf_part}"
        )
    else:
        background_tasks.add_task(
            log_action,
            f"ARRIVED & ASSIGNED: Train {train_no} arrived at {actual_arrival_for_state} and assigned to {', '.join(platform_ids)}. (platformArrival: {actual_platform_arrival})"
        )
    # ASSIGN/REASSIGN should create a NEW report entry (new CSV row).
    # Merge any cached suggestions from earlier "Get Platform Suggestions".
    background_tasks.add_task(
        persist_assignment_report_entry,
        train_no,
        {
            'trainName': train_name_for_report,
            'scheduled_arrival': (train_data or {}).get('ARRIVAL AT KGP', ''),
            'scheduled_departure': (train_data or {}).get('DEPARTURE FROM KGP', ''),
            'actual_arrival': actual_arrival_for_report,
            'actual_platform': ', '.join(normalize_platform_labels(platform_ids)),
            'actual_platform_arrival': actual_platform_arrival,
            'incoming_line': train_to_assign.get('incoming_line') or provided_incoming_line or '',
            'Remarks': '',
        },
    )
    return {"message": f"Train {train_no} assigned to {', '.join(platform_ids)}."}


@app.post("/api/assign-track")
async def assign_track(body: dict, background_tasks: BackgroundTasks):
    track_id = body.get('trackId')
    if not track_id:
        raise HTTPException(status_code=400, detail="trackId is required for track assignment.")
    if track_id not in ALLOWED_TRACK_IDS:
        raise HTTPException(status_code=400, detail=f"{track_id} is not a valid freight track.")
    incoming_line = body.get('incomingLine') or ''
    actual_arrival = body.get('actualArrival')
    train_name = body.get('trainName') or 'Freight'
    train_no = body.get('trainNo') or get_next_freight_tag()

    state = state_collection.find_one({"_id": "current_station_state"}) or {}
    track_entry = next((p for p in state.get('platforms', []) if p.get('id') == track_id), None)
    if not track_entry:
        raise HTTPException(status_code=404, detail=f"{track_id} not found in station state.")
    if track_entry.get('isOccupied'):
        raise HTTPException(status_code=409, detail=f"{track_id} is already occupied.")
    if track_entry.get('isUnderMaintenance'):
        raise HTTPException(status_code=409, detail=f"{track_id} is under maintenance.")

    arrival_timestamp = actual_arrival or datetime.now().strftime('%H:%M')
    train_details = {
        'trainNo': str(train_no),
        'name': train_name,
    }
    if incoming_line:
        train_details['incomingLine'] = incoming_line
    train_details['isFreightTrack'] = True
    train_details['actualPlatformArrival'] = arrival_timestamp

    for i, p in enumerate(state.get('platforms', [])):
        if p.get('id') == track_id:
            state['platforms'][i]['isOccupied'] = True
            state['platforms'][i]['trainDetails'] = train_details
            state['platforms'][i]['actualArrival'] = arrival_timestamp
            state['platforms'][i]['actualPlatformArrival'] = arrival_timestamp
            break

    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    friendly_name = TRACK_LABELS.get(track_id, track_id)
    background_tasks.add_task(log_action, f"FREIGHT TRACK ASSIGN: Train {train_no} assigned to {friendly_name} ({track_id}) (incoming {incoming_line}).")
    # Track assignment should also create a NEW report entry (new CSV row)
    background_tasks.add_task(
        persist_assignment_report_entry,
        train_no,
        {
            'trainName': train_name,
            'actual_arrival': arrival_timestamp,
            'actual_platform': normalize_platform_label(track_id),
            'actual_platform_arrival': arrival_timestamp,
            'incoming_line': incoming_line,
            'Remarks': '',
        }
    )
    return {"message": f"Freight train {train_no} assigned to {track_id}.", "trainNo": str(train_no)}


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
    else:
        # Fallback partner clear for long trains if link missing
        train_data = get_train_record(str(train_details.get('trainNo')))
        is_long = str(train_data.get('LENGTH', '')).strip().lower() == 'long'
        if is_long:
            partner_guess = find_partner_platform_id(platform_id)
            if partner_guess:
                partner_obj = next((p for p in state.get('platforms', []) if p.get('id') == partner_guess), None)
                if partner_obj and partner_obj.get('isOccupied') and partner_obj.get('trainDetails') and partner_obj['trainDetails'].get('trainNo') == train_details.get('trainNo'):
                    _clear_platform(state, partner_guess)
                    cleared_platforms.append(partner_guess)

    # Persist state synchronously for immediate reflection; log in background
    state_collection.replace_one({"_id": "current_station_state"}, state, upsert=True)
    background_tasks.add_task(log_action, f"UNASSIGNED: Train {train_details['trainNo']} unassigned from {', '.join(cleared_platforms)} and returned to arrival list.")
    # Requirement: when unassigned, write "unassign" into Remarks on the current/latest row.
    try:
        # IMPORTANT: do not create a new baseline row here; only update the latest existing row.
        background_tasks.add_task(persist_report_update_if_exists, train_details['trainNo'], {'Remarks': 'unassigned'})
    except Exception:
        pass

    # If suggestions already exist on the latest report row, carry them forward so the next
    # assignment row can include them even if the operator doesn't recompute suggestions.
    try:
        latest_report = get_latest_report_entry_for_today(str(train_details['trainNo'])) or {}
        suggestions_field = latest_report.get('suggestions')
        if not suggestions_field:
            suggestions_field = latest_report.get('top3_suggestions')
        incoming_line_for_cache = latest_report.get('incoming_line') or ''
        if suggestions_field:
            date_key = _today_str()
            suggestions_cache_collection.update_one(
                {"date": date_key, "trainNo": str(train_details['trainNo'])},
                {
                    "$set": {
                        "date": date_key,
                        "trainNo": str(train_details['trainNo']),
                        "suggestions": suggestions_field,
                        "incoming_line": incoming_line_for_cache,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                },
                upsert=True,
            )
    except Exception:
        pass
    # (No auto-suggestion trigger on unassign per updated requirement.)
    return {"message": f"Train {train_details['trainNo']} unassigned from {', '.join(cleared_platforms)}."}


@app.post("/api/depart-train")
async def depart_train(body: dict, background_tasks: BackgroundTasks):
    platform_id = body.get('platformId')
    line = body.get('line') or body.get('outgoingLine') or body.get('outgoing_line')
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
    # If partner recorded via linkedPlatformId, clear it
    if linked_platform_id:
        _clear_platform(state, linked_platform_id)
        cleared_platforms.append(linked_platform_id)
    else:
        # Fallback: for long trains ensure partner is cleared even if link missing
        # Detect long train from master data
        train_data = get_train_record(str(train_details.get('trainNo')))
        is_long = str(train_data.get('LENGTH', '')).strip().lower() == 'long'
        if is_long:
            def find_partner(pid: str):
                m = re.match(r"^(Platform)\s*(\d+)([A-Za-z]*)$", pid)
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
            partner_guess = find_partner(platform_id)
            if partner_guess:
                partner_obj = next((p for p in state.get('platforms', []) if p.get('id') == partner_guess), None)
                if partner_obj and partner_obj.get('isOccupied') and partner_obj.get('trainDetails') and partner_obj['trainDetails'].get('trainNo') == train_details.get('trainNo'):
                    _clear_platform(state, partner_guess)
                    cleared_platforms.append(partner_guess)

    departure_time = datetime.now().strftime('%H:%M')

    # IMPORTANT: do not create a new baseline row on depart; update the latest assignment row.
    update_fields = {'actual_departure': departure_time}
    if line:
        update_fields['outgoing_line'] = line
    background_tasks.add_task(persist_report_update_if_exists, train_details['trainNo'], update_fields)

    # Single combined departure log (includes departure line if provided)
    if line:
        background_tasks.add_task(
            log_action,
            f"Train {train_details['trainNo']} departed from {platform_id} at {departure_time} via {line}."
        )
    else:
        background_tasks.add_task(
            log_action,
            f"Train {train_details['trainNo']} departed from {platform_id} at {departure_time}."
        )
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
    if train_no:
        # IMPORTANT: do not create a new baseline row here; update the latest existing row.
        background_tasks.add_task(persist_report_update_if_exists, train_no, {'outgoing_line': line})
    # (No suggestion trigger here.)
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
async def download_report(
    date: str | None = None,
    startDate: str | None = None,
    endDate: str | None = None,
):
    """Download a CSV report.

    - Single date: `?date=YYYY-MM-DD` (backward compatible)
    - Date range: `?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD` (inclusive)

    Returns one combined CSV; includes a `date` column.
    """

    def _is_ymd(s: str) -> bool:
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s or ''))

    use_range = bool(startDate or endDate)
    if use_range:
        start = startDate or endDate
        end = endDate or startDate
        if not start or not end:
            raise HTTPException(status_code=400, detail="startDate and endDate are required for range download.")
        if not _is_ymd(start) or not _is_ymd(end):
            raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format.")
        if start > end:
            start, end = end, start
        query = {"date": {"$gte": start, "$lte": end}}
        filename = f"{start}_to_{end}.csv"
    else:
        date_str = date or _today_str()
        if not _is_ymd(date_str):
            raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format.")
        query = {"date": date_str}
        filename = f"{date_str}.csv"

    try:
        rows = list(
            reports_collection
            .find(query, {"_id": 0})
            .sort([("date", 1), ("trainNo", 1), ("event_time", 1)])
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read reports: {e}")

    headers_list = [
        'date', 'trainNo', 'trainName', 'scheduled_arrival', 'scheduled_departure',
        'actual_arrival', 'actual_departure', 'actual_platform_arrival', 'suggestions', 'actual_platform',
        'incoming_line', 'outgoing_line', 'Remarks'
    ]

    def generate():
        yield ','.join(headers_list) + '\n'
        for r in rows:
            suggestions_field = r.get('suggestions') or r.get('top3_suggestions', [])
            normalized_suggestions = ', '.join(normalize_platform_labels(coerce_label_list(suggestions_field)))
            actual_platform_field = r.get('actual_platform', '')
            normalized_actual_platform = ', '.join(normalize_platform_labels(coerce_label_list(actual_platform_field))) if actual_platform_field else ''
            values = [
                r.get('date', ''),
                str(r.get('trainNo', '')),
                (r.get('trainName', '') or '').replace(',', ' '),
                r.get('scheduled_arrival', '') or '',
                r.get('scheduled_departure', '') or '',
                r.get('actual_arrival', '') or '',
                r.get('actual_departure', '') or '',
                r.get('actual_platform_arrival', '') or '',
                normalized_suggestions.replace(',', ';'),
                normalized_actual_platform or '',
                r.get('incoming_line', '') or '',
                r.get('outgoing_line', '') or '',
                r.get('Remarks', '') or '',
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
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    return StreamingResponse(generate(), headers=headers)


@app.get("/api/debug/push-alert")
async def debug_push_alert():
    try:
        sse_broadcaster.put(f"event: departure_alert\ndata: {json.dumps({'train_number': 'TEST-001', 'train_name': 'Debug Train', 'platform_id': 'Platform 1'})}\n\n")
        return {"message": "Debug departure_alert sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
