from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import threading
import time
import queue
import csv
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import certifi


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    print("\n--- FATAL ERROR ---")
    print("MONGO_URI not found in environment variables.")
    print("Please create an '.env' file in the '/api' directory and add your MongoDB connection string.")
    print("-------------------\n")
    exit()

try:
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client.get_database('railwayDB')
    trains_collection = db['trains']
    platforms_collection = db['platforms']
    state_collection = db['station_state']
    logs_collection = db['operations_log']
    reports_collection = db['daily_reports']
    print("DEBUG: MongoDB connection successful.")
except Exception as e:
    print(f"\n--- MONGODB CONNECTION ERROR ---")
    print(f"Could not connect to MongoDB. Error: {e}")
    print("Please check your MONGO_URI in the .env file and your network connection.")
    print("--------------------------------\n")
    exit()

# Robust import of local scoring module for both package and script execution
try:
    # When running under gunicorn as package (index.index)
    from .scoring_algorithm import ScoringTrain, get_available_platforms, calculate_platform_scores  # type: ignore
except Exception:
    try:
        # When running this file directly (python index.py)
        from scoring_algorithm import ScoringTrain, get_available_platforms, calculate_platform_scores  # type: ignore
    except Exception as e:
        print(f"Warning: scoring_algorithm import failed: {e}")
        class ScoringTrain: pass
        def get_available_platforms(p): return []
        def calculate_platform_scores(t, a, i, m): return []


app = Flask(__name__)
CORS(app)

API_DIR = os.path.dirname(__file__)
BLOCKAGE_MATRIX_FILE = os.path.join(API_DIR, 'Track Connections.xlsx - Tracks.csv')
BLOCKAGE_MATRIX = {}
INCOMING_LINES = []

def parse_blockage_cell(cell_string):
    """Parses the complex blockage string from the CSV into a list of route dictionaries."""
    s = str(cell_string or '')
    # Normalize line-endings like the working pandas script does
    # (that replaces \r/\n variations consistently before parsing)
    s = s.replace('\r\n', '\n').replace('\r', '\n').strip()
    # If marked as not applicable/no route, return empty routes so platform is skipped
    up = s.upper().replace(' ', '')
    if not s or up == '--NA--' or (('NA' in up) and ('(' not in s)):
        return []
    routes = []
    parts = s.split('\n')
    for part in parts:
        part = part.strip()
        if not part: continue
        route_data = {'full': [], 'partial': []}
        matches = re.findall(r'(\d+)\s*\((.*?)\)', part)
        if len(matches) >= 1:
            nums_str = matches[0][1].strip()
            if nums_str: route_data['full'] = [f"P{s.strip()}" for s in nums_str.split(',')]
        if len(matches) >= 2:
            nums_str = matches[1][1].strip()
            if nums_str: route_data['partial'] = [f"P{s.strip()}" for s in nums_str.split(',')]
        # Append the route even if both lists are empty (valid route with 0 blockages)
        routes.append(route_data)
    return routes

def load_blockage_matrix():
    """Loads and parses the blockage matrix CSV file into a structured dictionary."""
    matrix, lines = {}, []
    try:
        with open(BLOCKAGE_MATRIX_FILE, mode='r', encoding='utf-8-sig', newline='') as infile:
            reader = csv.reader(infile)
            headers = next(reader, None)
            if not headers:
                print("FATAL: Blockage matrix CSV appears to be empty or has no header row.")
                return {}, []

            headers = [h.strip() for h in headers]

            for row in reader:
                if not row or len(row) == 0:
                    continue
                # Guard against short rows
                first_cell = row[0] if len(row) > 0 else ''
                incoming_line = (first_cell or '').strip()
                if not incoming_line:
                    continue
                lines.append(incoming_line)
                matrix[incoming_line] = {}

                # Iterate only over columns that exist in both header and row
                max_cols = min(len(row), len(headers))
                for col_idx in range(1, max_cols):
                    cell = row[col_idx]
                    if not cell or not str(cell).strip():
                        continue
                    platform_header = headers[col_idx] if col_idx < len(headers) else f"Col{col_idx}"
                    platform_header = platform_header.strip() or f"Col{col_idx}"
                    matrix[incoming_line][platform_header] = parse_blockage_cell(cell)
        print("DEBUG: Blockage matrix loaded and parsed successfully.")
        return matrix, lines
    except FileNotFoundError:
        print(f"FATAL: Blockage matrix file not found. Ensure 'Track Connections.xlsx - Tracks.csv' is in the '{API_DIR}' directory.")
        return {}, []
    except Exception as e:
        print(f"FATAL: An error occurred while parsing the blockage matrix: {e}")
        return {}, []




sse_broadcaster = queue.Queue()
active_timers = {}
timers_lock = threading.Lock()

# --- Utility Functions now use MongoDB ---

def log_action(action_string):
    """Logs an action to the 'operations_log' collection in MongoDB."""
    logs_collection.insert_one({
        "timestamp": datetime.now(),
        "action": action_string
    })

# --- Daily Reports (date-wise CSV) ---
REPORTS_DIR = os.path.join(API_DIR, 'reports')
os.makedirs(REPORTS_DIR, exist_ok=True)

def _today_str():
    return datetime.now().strftime('%Y-%m-%d')

def upsert_daily_report(train_no, update_fields, date_str=None):
    if not train_no:
        return
    date_key = date_str or _today_str()
    reports_collection.update_one(
        {"date": date_key, "trainNo": str(train_no)},
        {"$set": {**update_fields, "date": date_key, "trainNo": str(train_no)}},
        upsert=True
    )

def write_csv_for_date(date_str):
    try:
        rows = list(reports_collection.find({"date": date_str}, {"_id": 0}).sort("trainNo", 1))
        csv_path = os.path.join(REPORTS_DIR, f"{date_str}.csv")
        headers = [
            'date', 'trainNo', 'trainName', 'scheduled_arrival', 'scheduled_departure',
            'actual_arrival', 'actual_departure', 'top3_suggestions', 'actual_platform',
            'incoming_line', 'outgoing_line'
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
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
        print(f"DEBUG: Wrote daily CSV {csv_path}")
    except Exception as e:
        print(f"WARNING: Failed to write CSV for {date_str}: {e}")

def initialize_station_state():
    """Initializes station state in MongoDB if it doesn't exist."""
    if state_collection.count_documents({}) == 0:
        print("State not found in MongoDB. Initializing from master collections...")
        try:
            platforms_master_raw = list(platforms_collection.find({}, {'_id': 0}))
            
            if len(platforms_master_raw) == 1 and 'tracks' in platforms_master_raw[0]:
                print("DEBUG: Detected single-document import for platforms. Using inner 'tracks' array.")
                platforms_master = platforms_master_raw[0]['tracks']
            else:
                platforms_master = platforms_master_raw

            trains_master = list(trains_collection.find({}, {'_id': 0}))

            initial_platforms = []
            for track_data in platforms_master:
                is_platform = track_data.get('is_platform', False)
                item_id = track_data['id'].replace('P', '').replace('T', '')
                
                initial_platforms.append({
                    "id": f"Platform {item_id}" if is_platform else f"Track {item_id}",
                    "isOccupied": False, 
                    "trainDetails": None, 
                    "isUnderMaintenance": False,
                    "actualArrival": None
                })

            initial_schedule = []
            for row in trains_master:
                initial_schedule.append({
                    "trainNo": str(row['TRAIN NO']),
                    "name": row['TRAIN NAME'],
                    "scheduled_arrival": row.get('ARRIVAL AT KGP'),
                    "scheduled_departure": row.get('DEPARTURE FROM KGP')
                })
            
            initial_state = {
                "_id": "current_station_state",
                "platforms": initial_platforms,
                "arrivingTrains": sorted(initial_schedule, key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99'),
                "waitingList": []
            }
            
            state_collection.insert_one(initial_state)
            log_action("System initialized: Station state created from master data.")
            print("State initialized in MongoDB successfully.")

        except Exception as e:
            print(f"FATAL: Could not initialize state in MongoDB. Error: {e}")
            pass

def read_state():
    """Reads the current station state from MongoDB."""
    state = state_collection.find_one({"_id": "current_station_state"})
    if not state:
        initialize_station_state()
        state = state_collection.find_one({"_id": "current_station_state"})
    
    if state and '_id' in state:
        state['_id'] = str(state['_id'])
        
    return state

def write_state(new_state):
    """Writes the new state to MongoDB, replacing the existing state document."""
    if '_id' in new_state:
        del new_state['_id']
    state_collection.replace_one({"_id": "current_station_state"}, new_state, upsert=True)


def sync_arriving_trains_from_master(state):
    """Augment state's arrivingTrains so it includes all trains from the master trains collection.

    - Adds any missing trains from trains_collection to state['arrivingTrains']
    - Updates name/schedule for existing entries if master changed
    - Does NOT remove trains from arrivingTrains to keep it static as per requirement
    Returns True if state was modified, else False.
    """
    try:
        master = list(trains_collection.find({}, {'_id': 0}))
        if master is None:
            return False
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
                # Update fields if different
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
        return changed
    except Exception as e:
        print(f"WARNING: Failed to sync arrivingTrains from master: {e}")
        return False


def time_difference_seconds(time_str1, time_str2):
    try:
        t1 = datetime.strptime(time_str1, '%H:%M')
        t2 = datetime.strptime(time_str2, '%H:%M')
        if t2 < t1: t2 += timedelta(days=1)
        return (t2 - t1).total_seconds()
    except (ValueError, TypeError):
        return 0

def push_departure_alert(train_number, train_name, platform_id):
    event_data = {'train_number': train_number, 'train_name': train_name, 'platform_id': platform_id}
    sse_broadcaster.put(f"event: departure_alert\ndata: {json.dumps(event_data)}\n\n")

@app.route("/")
def home():
    return "Kharagpur Station Control API is running."

@app.route("/stream")
@app.route("/api/stream")
def stream():
    def event_generator():
        while True:
            try:
                msg = sse_broadcaster.get(timeout=20)
                yield msg
            except queue.Empty:
                yield ": heartbeat\n\n"
    return Response(event_generator(), mimetype="text/event-stream")

@app.route("/api/station-data")
def get_station_data():
    state = read_state()
    if sync_arriving_trains_from_master(state):
        write_state(state)
    return jsonify(state)

@app.route("/api/logs")
def get_logs():
    log_entries = list(logs_collection.find().sort("timestamp", -1).limit(100))
    logs_json = [{"timestamp": log['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), "action": log['action']} for log in log_entries]
    return jsonify(logs_json)


@app.route("/api/platform-suggestions", methods=['POST'])
def get_platform_suggestions():
    request_data = request.get_json()
    train_no = request_data.get('trainNo')
    incoming_line = request_data.get('incomingLine') # New required parameter
    frontend_platforms = request_data.get('platforms')
    freight_needs_platform = request_data.get('freightNeedsPlatform')

    if not all([train_no, incoming_line, frontend_platforms]):
        return jsonify({"error": "Missing required parameters: trainNo, incomingLine, and platforms are all required."}), 400
    
    train_data = trains_collection.find_one({"TRAIN NO": str(train_no)})
    if not train_data:
        return jsonify({"error": f"Train {train_no} not found in master schedule."}), 404

    is_freight = 'Goods' in train_data.get('TRAIN NAME', '') or 'Freight' in train_data.get('TRAIN NAME', '')
    
    incoming_train = ScoringTrain(
        train_id=train_data.get('TRAIN NO'),
        train_name=train_data.get('TRAIN NAME'),
        train_type='Freight' if is_freight else 'Passenger',
        is_terminating=train_data.get('ISTERMINATING', False),
        length=train_data.get('LENGTH', 'Long').lower(),
        needs_platform=freight_needs_platform if is_freight else True,
        direction=train_data.get('DIRECTION'),
        historical_platform=str(train_data.get('PLATFORM NO', '')).split(',')[0].strip(),
        zone=train_data.get('ZONE', 'SER')
    )

    available_platforms = get_available_platforms(frontend_platforms)
    
    ranked_suggestions = calculate_platform_scores(incoming_train, available_platforms, incoming_line, BLOCKAGE_MATRIX)
    
    final_suggestions = []
    for suggestion in ranked_suggestions:
        pf_id = suggestion['platformId']
        display_id = f"Platform {pf_id.replace('P','')}" if pf_id.startswith('P') else f"Track {pf_id.replace('T','')}"
        final_suggestions.append({
            "platformId": display_id,
            "score": suggestion['score'],
            "platformIds": [display_id],
            "blockages": suggestion.get('blockages', {}) 
        })
    
    # Persist top3 suggestions and incoming line
    try:
        top3 = [s['platformId'] for s in final_suggestions[:3]]
        upsert_daily_report(train_no, {
            'trainName': train_data.get('TRAIN NAME', ''),
            'scheduled_arrival': train_data.get('ARRIVAL AT KGP', ''),
            'scheduled_departure': train_data.get('DEPARTURE FROM KGP', ''),
            'incoming_line': incoming_line,
            'top3_suggestions': top3
        })
        write_csv_for_date(_today_str())
    except Exception as e:
        print(f"WARNING: Persist suggestions failed for train {train_no}: {e}")
    return jsonify({"suggestions": final_suggestions})

@app.route("/api/incoming-lines")
def get_incoming_lines():
    """Provides the list of incoming lines from the matrix for the frontend dropdown."""
    return jsonify(INCOMING_LINES)

@app.route("/api/add-train", methods=['POST'])
def add_train():
    new_train_data = request.get_json()
    if trains_collection.find_one({"TRAIN NO": str(new_train_data.get('TRAIN NO'))}):
        return jsonify({"error": f"Train number {new_train_data.get('TRAIN NO')} already exists."}), 409
    
    trains_collection.insert_one(new_train_data)
    
    state = read_state()
    state['arrivingTrains'].append({
        "trainNo": str(new_train_data['TRAIN NO']),
        "name": new_train_data['TRAIN NAME'],
        "scheduled_arrival": new_train_data.get('ARRIVAL AT KGP'),
        "scheduled_departure": new_train_data.get('DEPARTURE FROM KGP')
    })
    state['arrivingTrains'].sort(key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99')
    
    log_action(f"TRAIN ADDED: New train {new_train_data['TRAIN NO']} added to the master schedule.")
    write_state(state)
    return jsonify({"message": f"Train {new_train_data['TRAIN NO']} added successfully."})

@app.route("/api/delete-train", methods=['POST'])
def delete_train():
    train_no_to_delete = str(request.json.get('trainNo'))
    
    result = trains_collection.delete_one({"TRAIN NO": train_no_to_delete})
    
    if result.deleted_count == 0:
        return jsonify({"error": f"Train {train_no_to_delete} not found in master list."}), 404

    state = read_state()
    state['arrivingTrains'] = [t for t in state['arrivingTrains'] if str(t['trainNo']) != train_no_to_delete]
    state['waitingList'] = [t for t in state.get('waitingList', []) if str(t['trainNo']) != train_no_to_delete]
    
    log_action(f"TRAIN DELETED: Train {train_no_to_delete} removed from the master schedule.")
    write_state(state)
    return jsonify({"message": f"Train {train_no_to_delete} deleted successfully."})

@app.route("/api/add-to-waiting-list", methods=['POST'])
def add_to_waiting_list():
    data = request.get_json()
    train_no = data.get('trainNo')
    if not train_no:
        return jsonify({"error": "Train number is required."}), 400
    state = read_state()
    if any(t['trainNo'] == train_no for t in state.get('waitingList', [])):
        return jsonify({"message": f"Train {train_no} is already in the waiting list."})
    train_to_wait = next((t for t in state['arrivingTrains'] if t['trainNo'] == train_no), None)
    if not train_to_wait:
        return jsonify({"error": f"Train {train_no} not found in arriving trains."}), 404
    state.setdefault('waitingList', []).append(train_to_wait)
    log_action(f"WAITING: Train {train_no} added to the waiting list.")
    write_state(state)
    return jsonify({"message": f"Train {train_no} added to the waiting list."})

@app.route("/api/remove-from-waiting-list", methods=['POST'])
def remove_from_waiting_list():
    data = request.get_json()
    train_no = data.get('trainNo')
    if not train_no:
        return jsonify({"error": "Train number is required."}), 400
    state = read_state()
    train_to_remove = next((t for t in state.get('waitingList', []) if t['trainNo'] == train_no), None)
    if not train_to_remove:
        return jsonify({"error": f"Train {train_no} not found in the waiting list."}), 404
    state['waitingList'] = [t for t in state['waitingList'] if t['trainNo'] != train_no]
    log_action(f"WAITING LIST: Train {train_no} removed from waiting list.")
    write_state(state)
    return jsonify({"message": f"Train {train_no} removed from the waiting list."})

@app.route("/api/assign-platform", methods=['POST'])
def assign_platform():
    data = request.get_json()
    train_no = data.get('trainNo')
    platform_ids_raw = data.get('platformIds') 
    actual_arrival = data.get('actualArrival')
    platform_ids = [platform_ids_raw] if isinstance(platform_ids_raw, str) else platform_ids_raw
    state = read_state()
    # Prefer waiting list if present so the item is removed from waitingList after assignment
    is_from_waiting_list = False
    wl_match = next((t for t in state.get('waitingList', []) if t.get('trainNo') == train_no), None)
    if wl_match:
        train_to_assign = wl_match
        is_from_waiting_list = True
    else:
        train_to_assign = next((t for t in state.get('arrivingTrains', []) if t.get('trainNo') == train_no), None)
    if not train_to_assign:
        return jsonify({"error": "Train not found in arriving or waiting lists."}), 404
    
    train_data = trains_collection.find_one({"TRAIN NO": str(train_no)})
    
    stoppage_seconds = time_difference_seconds(train_data.get('ARRIVAL AT KGP'), train_data.get('DEPARTURE FROM KGP'))
    # If train is long and single platform selected, auto-include its paired platform
    try:
        is_long = str(train_data.get('LENGTH', '')).strip().lower() == 'long'
    except Exception:
        is_long = False

    def find_partner(platform_name):
        # match 'Platform <num><suffix?>' and map 1<->3, 2<->4
        m = re.match(r"^(Platform)\s*(\d+)([A-Za-z]*)$", platform_name)
        if not m:
            return None
        base, num_str, suffix = m.group(1), m.group(2), m.group(3) or ''
        try:
            num = int(num_str)
        except ValueError:
            return None
        partner_map = {1:3, 2:4, 3:1, 4:2}
        if num not in partner_map:
            return None
        partner_num = partner_map[num]
        return f"{base} {partner_num}{suffix}"

    if is_long and len(platform_ids) == 1:
        requested = platform_ids[0]
        partner = find_partner(requested)
        if partner:
            # check partner availability in current state
            partner_obj = next((p for p in state.get('platforms', []) if p.get('id') == partner), None)
            if partner_obj and not partner_obj.get('isOccupied') and not partner_obj.get('isUnderMaintenance'):
                platform_ids = [requested, partner]
            else:
                # If partner is not available, return error so user can choose a different assignment
                return jsonify({"error": f"Partner platform {partner} is not available for long train assignment."}), 400

    is_linked_assignment = len(platform_ids) > 1
    linked_map = {platform_ids[0]: platform_ids[1], platform_ids[1]: platform_ids[0]} if is_linked_assignment else {}
    for platform_id in platform_ids:
        for i, p in enumerate(state['platforms']):
            if p['id'] == platform_id:
                train_details = { "trainNo": train_to_assign['trainNo'], "name": train_to_assign['name'] }
                if is_linked_assignment:
                    train_details['linkedPlatformId'] = linked_map[platform_id]
                state['platforms'][i]['isOccupied'] = True
                state['platforms'][i]['trainDetails'] = train_details
                state['platforms'][i]['actualArrival'] = actual_arrival
                if stoppage_seconds > 0:
                    timer = threading.Timer(stoppage_seconds, push_departure_alert, args=[train_no, train_data.get('TRAIN NAME'), platform_id])
                    with timers_lock:
                        active_timers[platform_id] = timer
                    timer.start()
                break
    if is_from_waiting_list:
        state['waitingList'] = [t for t in state.get('waitingList', []) if t['trainNo'] != train_no]
    log_action(f"ARRIVED & ASSIGNED: Train {train_no} arrived at {actual_arrival} and assigned to {', '.join(platform_ids)}.")
    # Update daily report with actual arrival and actual platform(s)
    try:
        train_data = trains_collection.find_one({"TRAIN NO": str(train_no)})
        upsert_daily_report(train_no, {
            'trainName': (train_data or {}).get('TRAIN NAME', ''),
            'scheduled_arrival': (train_data or {}).get('ARRIVAL AT KGP', ''),
            'scheduled_departure': (train_data or {}).get('DEPARTURE FROM KGP', ''),
            'actual_arrival': actual_arrival,
            'actual_platform': ', '.join(platform_ids)
        })
        write_csv_for_date(_today_str())
    except Exception as e:
        print(f"WARNING: Persist assignment failed for train {train_no}: {e}")
    write_state(state)
    return jsonify({"message": f"Train {train_no} assigned to {', '.join(platform_ids)}."})

def _clear_platform(state, platform_id):
    platform_to_clear = next((p for p in state['platforms'] if p['id'] == platform_id), None)
    if not platform_to_clear or not platform_to_clear['isOccupied']:
        return None, None
    with timers_lock:
        if platform_id in active_timers:
            active_timers[platform_id].cancel()
            del active_timers[platform_id]
    train_details = platform_to_clear['trainDetails']
    linked_platform_id = train_details.get('linkedPlatformId')
    platform_to_clear['isOccupied'] = False
    platform_to_clear['trainDetails'] = None
    platform_to_clear['actualArrival'] = None
    return train_details, linked_platform_id

@app.route("/api/unassign-platform", methods=['POST'])
def unassign_platform():
    platform_id = request.json.get('platformId')
    state = read_state()
    train_details, linked_platform_id = _clear_platform(state, platform_id)
    if not train_details:
        return jsonify({"error": "Platform not found or is not occupied."}), 404
    cleared_platforms = [platform_id]
    if linked_platform_id:
        _clear_platform(state, linked_platform_id)
        cleared_platforms.append(linked_platform_id)

    # Arriving list remains static; do not modify it on unassign
    log_action(f"UNASSIGNED: Train {train_details['trainNo']} unassigned from {', '.join(cleared_platforms)} and returned to arrival list.")
    write_state(state)
    return jsonify({"message": f"Train {train_details['trainNo']} unassigned from {', '.join(cleared_platforms)}."})

@app.route("/api/depart-train", methods=['POST'])
def depart_train():
    platform_id = request.json.get('platformId')
    state = read_state()
    train_details, linked_platform_id = _clear_platform(state, platform_id)
    if not train_details:
        return jsonify({"error": "Platform not found or is not occupied."}), 404
    cleared_platforms = [platform_id]
    if linked_platform_id:
        _clear_platform(state, linked_platform_id)
        cleared_platforms.append(linked_platform_id)
    departure_time = datetime.now().strftime('%H:%M')
    log_action(f"DEPARTED: Train {train_details['trainNo']} departed from {', '.join(cleared_platforms)} at {departure_time}.")
    try:
        upsert_daily_report(train_details['trainNo'], {'actual_departure': departure_time})
        write_csv_for_date(_today_str())
    except Exception as e:
        print(f"WARNING: Persist departure failed for train {train_details['trainNo']}: {e}")
    write_state(state)
    return jsonify({"message": f"Train {train_details['trainNo']} departed from {', '.join(cleared_platforms)}."})

# --- NEW: Log departure line before departure ---
@app.route("/api/log-depart-line", methods=['POST'])
def log_depart_line():
    data = request.get_json()
    platform_id = data.get('platformId')
    line = data.get('line')
    if not platform_id or not line:
        return jsonify({"error": "platformId and line required."}), 400
    # Identify train number from occupied platform
    train_no = None
    try:
        state = read_state()
        for p in state.get('platforms', []):
            if p.get('id') == platform_id and p.get('isOccupied') and p.get('trainDetails'):
                train_no = str(p['trainDetails']['trainNo'])
                break
    except Exception:
        pass
    log_action(f"DEPART LINE: Train {train_no or ''} departing from {platform_id} via {line}.")
    if train_no:
        try:
            upsert_daily_report(train_no, {'outgoing_line': line})
            write_csv_for_date(_today_str())
        except Exception as e:
            print(f"WARNING: Persist outgoing line failed for train {train_no}: {e}")
    return jsonify({"message": "Departure line logged."})

@app.route("/api/toggle-maintenance", methods=['POST'])
def toggle_maintenance():
    platform_id = request.json.get('platformId')
    state = read_state()
    
    for i, p in enumerate(state['platforms']):
        if p['id'] == platform_id:
            if state['platforms'][i]['isOccupied']:
                return jsonify({"error": "Cannot change maintenance on an occupied platform."}), 400
            state['platforms'][i]['isUnderMaintenance'] = not state['platforms'][i]['isUnderMaintenance']
            status = "ON" if state['platforms'][i]['isUnderMaintenance'] else "OFF"
            break
    
    log_action(f"MAINTENANCE: Maintenance for {platform_id} set to {status}.")
    write_state(state)
    return jsonify({"message": f"Maintenance status toggled for {platform_id}."})

# Download date-wise report as CSV
@app.route("/api/report/download")
def download_report():
    date_str = request.args.get('date') or _today_str()
    # Fetch rows directly from DB and stream a CSV regardless of on-disk file
    try:
        rows = list(reports_collection.find({"date": date_str}, {"_id": 0}).sort("trainNo", 1))
    except Exception as e:
        return jsonify({"error": f"Failed to read reports: {e}"}), 500

    headers_list = [
        'date', 'trainNo', 'trainName', 'scheduled_arrival', 'scheduled_departure',
        'actual_arrival', 'actual_departure', 'top3_suggestions', 'actual_platform',
        'incoming_line', 'outgoing_line'
    ]

    def generate():
        # Write header
        yield ','.join(headers_list) + '\n'
        # Write rows
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
            # Ensure commas don't break CSV simple writer, quote where needed
            safe = []
            for v in values:
                s = str(v)
                if any(ch in s for ch in [',', '"', '\n']):
                    s = '"' + s.replace('"', '""') + '"'
                safe.append(s)
            yield ','.join(safe) + '\n'

    return Response(generate(), headers={
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{date_str}.csv"'
    })


if __name__ == "__main__":
    BLOCKAGE_MATRIX, INCOMING_LINES = load_blockage_matrix()
    if not BLOCKAGE_MATRIX:
        print("Shutting down due to error in loading blockage matrix.")
        exit()
    with app.app_context():
        initialize_station_state()
    port = int(os.environ.get("PORT", 5000))  # Render gives PORT env var
    app.run(host="0.0.0.0", port=port, debug=True)
    # app.run(port=5000, debug=True)

