from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import threading
import shutil
import time
import queue

# --- Import the scoring algorithm module ---
from scoring_algorithm import ScoringTrain, get_available_track_sets, calculate_platform_scores, LOWEST, HIGHEST, BORDER_STN_PRIO

app = Flask(__name__)
CORS(app)

# --- File Paths ---
API_DIR = os.path.dirname(__file__)
STATE_FILE = os.path.join(API_DIR, 'station_state.json')
PLATFORMS_MASTER_FILE = os.path.join(API_DIR, 'platform_data.json')
TRAINS_MASTER_FILE = os.path.join(API_DIR, 'train_data.json')
LOG_FILE = os.path.join(API_DIR, 'operations_log.txt')

# --- In-memory state for real-time events ---
sse_broadcaster = queue.Queue()
active_timers = {}

# --- Thread-safe Locks ---
state_lock = threading.Lock()
log_lock = threading.Lock()
timers_lock = threading.Lock()


# --- Utility Functions ---

def log_action(action_string):
    """Thread-safely logs an action to the operations_log.txt file."""
    with log_lock:
        try:
            with open(LOG_FILE, 'r') as f:
                logs = f.readlines()
        except FileNotFoundError:
            logs = []
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} | {action_string}\n"
        logs.insert(0, log_entry)
        logs = logs[:500] 

        with open(LOG_FILE, 'w') as f:
            f.writelines(logs)

def time_difference_seconds(time_str1, time_str2):
    """Calculate difference between two HH:MM time strings in seconds."""
    try:
        t1 = datetime.strptime(time_str1, '%H:%M')
        t2 = datetime.strptime(time_str2, '%H:%M')
        if t2 < t1: # Handles overnight case
            t2 += timedelta(days=1)
        return (t2 - t1).total_seconds()
    except (ValueError, TypeError):
        return 0 # Return 0 if times are invalid

# --- State Management ---

def initialize_station_state():
    """Initializes the station state from master files if it doesn't exist."""
    with state_lock:
        if not os.path.exists(STATE_FILE):
            print("State file not found. Initializing from master data...")
            try:
                with open(PLATFORMS_MASTER_FILE, 'r') as f:
                    platforms_data = json.load(f)
                with open(TRAINS_MASTER_FILE, 'r') as f:
                    trains_data = json.load(f)

                initial_platforms = []
                all_platform_definitions = platforms_data.get('platform_tracks', []) + platforms_data.get('non_platform_tracks', [])
                
                for p_data in all_platform_definitions:
                    is_platform = 'P' in p_data.get('id', '')
                    item_id = p_data['id'].replace('P', '').replace('T', '')
                    
                    initial_platforms.append({
                        "id": f"Platform {item_id}" if is_platform else f"Track {item_id}",
                        "isOccupied": False, 
                        "trainDetails": None, 
                        "isUnderMaintenance": False,
                        "actualArrival": None # Add field for arrival time
                    })

                initial_arriving_trains = [{
                    "trainNo": str(row['TRAIN NO']),
                    "name": row['TRAIN NAME'],
                    "scheduled_arrival": row['ARRIVAL AT KGP']
                } for row in trains_data if row.get('ARRIVAL AT KGP')]
                
                initial_state = {
                    "platforms": initial_platforms,
                    "arrivingTrains": sorted(initial_arriving_trains, key=lambda x: x['scheduled_arrival'] or '99:99')
                }
                
                with open(STATE_FILE, 'w') as f:
                    json.dump(initial_state, f, indent=2)
                log_action("System initialized: Station state created from master files.")
                print("State file initialized successfully.")

            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"FATAL: Could not initialize state file. Error: {e}")
                exit(1)

def read_state():
    """Reads the current station state from the JSON file."""
    with state_lock:
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            initialize_station_state()
            with open(STATE_FILE, 'r') as f:
                return json.load(f)

def write_state(new_state):
    """Atomically writes the new state to the JSON file."""
    with state_lock:
        temp_file = STATE_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(new_state, f, indent=2)
        shutil.move(temp_file, STATE_FILE)

# --- Real-time Event Pushing ---

def push_departure_alert(train_number, train_name, platform_id):
    """Pushes a departure alert event to the SSE stream."""
    event_data = {
        'train_number': train_number,
        'train_name': train_name,
        'platform_id': platform_id
    }
    sse_broadcaster.put(f"event: departure_alert\ndata: {json.dumps(event_data)}\n\n")
    print(f"Pushed departure alert for {train_number} on {platform_id}")

@app.route("/stream")
def stream():
    def event_generator():
        messages = []
        while True:
            try:
                msg = sse_broadcaster.get(timeout=20)
                messages.append(msg)
                yield msg
            except queue.Empty:
                yield ": heartbeat\n\n"
    return Response(event_generator(), mimetype="text/event-stream")

# --- API Endpoints ---

@app.route("/api/station-data")
def get_station_data():
    return jsonify(read_state())

@app.route("/api/logs")
def get_logs():
    with log_lock:
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
            logs_json = [{"timestamp": parts[0], "action": parts[1]} for line in lines if len(parts := line.strip().split(' | ', 1)) == 2]
            return jsonify(logs_json)
        except FileNotFoundError:
            return jsonify([])

@app.route("/api/platform-suggestions", methods=['POST'])
def get_platform_suggestions():
    request_data = request.get_json()
    train_no = request_data.get('trainNo')
    frontend_platforms = request_data.get('platforms')
    freight_needs_platform = request_data.get('freightNeedsPlatform')

    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    
    train_data = next((t for t in trains_master if str(t.get('TRAIN NO')) == str(train_no)), None)
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
        historical_platform=str(train_data.get('PLATFORM NO', '')).split(',')[0].strip()
    )

    available_tracks = get_available_track_sets(frontend_platforms)
    ranked_scores_list = calculate_platform_scores(incoming_train, available_tracks)
    
    suggestions = []
    processed_tracks = set()
    ranked_scores_map = dict(ranked_scores_list)

    if incoming_train.type == 'Passenger' and incoming_train.direction == 'DOWN' and not incoming_train.is_terminating and incoming_train.length == 'long':
        if ranked_scores_map.get('P2') == HIGHEST and ranked_scores_map.get('P4') == HIGHEST:
            suggestions.append({
                "platformId": "Platform 2 & 4", "score": HIGHEST,
                "platformIds": ["Platform 2", "Platform 4"]
            })
            processed_tracks.update(['P2', 'P4'])
        
        if ranked_scores_map.get('P1') == BORDER_STN_PRIO and ranked_scores_map.get('P3') == BORDER_STN_PRIO:
            suggestions.append({
                "platformId": "Platform 1 & 3", "score": BORDER_STN_PRIO,
                "platformIds": ["Platform 1", "Platform 3"]
            })
            processed_tracks.update(['P1', 'P3'])

    for track_id, score in ranked_scores_list:
        if score > LOWEST and track_id not in processed_tracks:
            display_id = f"Platform {track_id.replace('P','')}" if track_id.startswith('P') else f"Track {track_id.replace('T','')}"
            suggestions.append({
                "platformId": display_id,
                "score": score,
                "platformIds": [display_id]
            })
    
    suggestions.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({"suggestions": suggestions})


@app.route("/api/assign-platform", methods=['POST'])
def assign_platform():
    data = request.get_json()
    train_no = data.get('trainNo')
    platform_ids_raw = data.get('platformIds') 
    actual_arrival = data.get('actualArrival')

    platform_ids = [platform_ids_raw] if isinstance(platform_ids_raw, str) else platform_ids_raw

    state = read_state()
    train_to_assign = next((t for t in state['arrivingTrains'] if t['trainNo'] == train_no), None)
    if not train_to_assign:
        return jsonify({"error": "Train not found in arriving trains list."}), 404

    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    train_data = next((t for t in trains_master if str(t.get('TRAIN NO')) == str(train_no)), None)
    
    # CORRECTED: Calculate timer duration based on SCHEDULED arrival and departure.
    stoppage_seconds = time_difference_seconds(train_data.get('ARRIVAL AT KGP'), train_data.get('DEPARTURE FROM KGP'))

    for platform_id in platform_ids:
        platform_to_update = next((p for p in state['platforms'] if p['id'] == platform_id), None)
        if platform_to_update:
            platform_to_update['isOccupied'] = True
            platform_to_update['trainDetails'] = { "trainNo": train_to_assign['trainNo'], "name": train_to_assign['name'] }
            platform_to_update['actualArrival'] = actual_arrival
            
            if stoppage_seconds > 0:
                timer = threading.Timer(stoppage_seconds, push_departure_alert, args=[train_no, train_data.get('TRAIN NAME'), platform_id])
                with timers_lock:
                    active_timers[platform_id] = timer
                timer.start()
                print(f"Departure timer set for {platform_id} in {stoppage_seconds} seconds (based on scheduled halt time).")

    log_action(f"ARRIVED & ASSIGNED: Train {train_no} arrived at {actual_arrival} and assigned to {', '.join(platform_ids)}.")
    write_state(state)
    return jsonify({"message": f"Train {train_no} assigned to {', '.join(platform_ids)}."})


@app.route("/api/unassign-platform", methods=['POST'])
def unassign_platform():
    platform_id = request.json.get('platformId')
    state = read_state()
    platform_to_clear = next((p for p in state['platforms'] if p['id'] == platform_id), None)

    if not platform_to_clear or not platform_to_clear['isOccupied']:
        return jsonify({"error": "Platform not found or is not occupied."}), 404

    with timers_lock:
        if platform_id in active_timers:
            active_timers[platform_id].cancel()
            del active_timers[platform_id]
            print(f"Cancelled timer for {platform_id} due to unassignment.")

    train_details = platform_to_clear['trainDetails']
    platform_to_clear['isOccupied'] = False
    platform_to_clear['trainDetails'] = None
    platform_to_clear['actualArrival'] = None

    log_action(f"UNASSIGNED: Train {train_details['trainNo']} unassigned from {platform_id}.")
    write_state(state)
    return jsonify({"message": f"Train {train_details['trainNo']} unassigned from {platform_id}."})

@app.route("/api/depart-train", methods=['POST'])
def depart_train():
    platform_id = request.json.get('platformId')
    state = read_state()
    platform_to_free = next((p for p in state['platforms'] if p['id'] == platform_id), None)

    if not platform_to_free or not platform_to_free['isOccupied']:
        return jsonify({"error": "Platform not found or is not occupied."}), 404

    with timers_lock:
        if platform_id in active_timers:
            active_timers[platform_id].cancel()
            del active_timers[platform_id]
            print(f"Cancelled timer for {platform_id} due to manual departure.")

    departed_train = platform_to_free['trainDetails']
    platform_to_free['isOccupied'] = False
    platform_to_free['trainDetails'] = None
    platform_to_free['actualArrival'] = None
    
    departure_time = datetime.now().strftime('%H:%M')
    log_action(f"DEPARTED: Train {departed_train['trainNo']} departed from {platform_id} at {departure_time}.")
    write_state(state)
    return jsonify({"message": f"Train {departed_train['trainNo']} departed from {platform_id}."})

# Other endpoints (add, delete, maintenance, etc.) remain the same...

@app.route("/api/toggle-maintenance", methods=['POST'])
def toggle_maintenance():
    platform_id = request.json.get('platformId')
    state = read_state()
    platform_to_toggle = next((p for p in state['platforms'] if p['id'] == platform_id), None)

    if not platform_to_toggle: return jsonify({"error": "Platform not found."}), 404
    if platform_to_toggle['isOccupied']: return jsonify({"error": "Cannot change maintenance on an occupied platform."}), 400

    platform_to_toggle['isUnderMaintenance'] = not platform_to_toggle['isUnderMaintenance']
    status = "ON" if platform_to_toggle['isUnderMaintenance'] else "OFF"
    log_action(f"MAINTENANCE: Maintenance for {platform_id} set to {status}.")
    write_state(state)
    return jsonify({"message": f"Maintenance status toggled for {platform_id}."})

@app.route("/api/add-train", methods=['POST'])
def add_train():
    new_train_data_frontend = request.get_json()
    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    
    new_train_data_master = {
        "TRAIN NO": new_train_data_frontend.get("trainNumber"),
        "TRAIN NAME": f"{new_train_data_frontend.get('train_type')} Train",
        "TYPE": new_train_data_frontend.get("train_type"),
        "ZONE": "NA",
        "DIRECTION": new_train_data_frontend.get("direction"),
        "ISTERMINATING": new_train_data_frontend.get("destination") == "KGP",
        "PLATFORM NO": "",
        "DAYS": "Daily",
        "LENGTH": new_train_data_frontend.get("size"),
        "ORIGIN FROM STATION": new_train_data_frontend.get("source"),
        "DEPARTURE FROM ORIGIN": "",
        "TERMINAL": "KGP" if new_train_data_frontend.get("scheduled_arrival") else "",
        "ARRIVAL AT KGP": new_train_data_frontend.get("scheduled_arrival"),
        "DEPARTURE FROM KGP": new_train_data_frontend.get("scheduled_departure"),
        "DESTINATION": new_train_data_frontend.get("destination"),
        "ARRIVAL AT DESTINATION": ""
    }

    if str(new_train_data_master['TRAIN NO']) in [str(t.get('TRAIN NO')) for t in trains_master]:
        return jsonify({"error": f"Train number {new_train_data_master['TRAIN NO']} already exists."}), 409

    trains_master.append(new_train_data_master)
    with open(TRAINS_MASTER_FILE, 'w') as f:
        json.dump(trains_master, f, indent=4)

    state = read_state()
    if new_train_data_master.get('ARRIVAL AT KGP'):
        state['arrivingTrains'].append({
            "trainNo": str(new_train_data_master['TRAIN NO']),
            "name": new_train_data_master['TRAIN NAME'],
            "scheduled_arrival": new_train_data_master.get('ARRIVAL AT KGP')
        })
        state['arrivingTrains'].sort(key=lambda x: x.get('scheduled_arrival') or '99:99')
    
    log_action(f"TRAIN ADDED: New train {new_train_data_master['TRAIN NO']} added to the master schedule.")
    write_state(state)
    return jsonify({"message": f"Train {new_train_data_master['TRAIN NO']} added successfully."})

@app.route("/api/delete-train", methods=['POST'])
def delete_train():
    train_no_to_delete = request.json.get('trainNo')
    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    
    initial_count = len(trains_master)
    trains_master = [t for t in trains_master if str(t.get('TRAIN NO')) != str(train_no_to_delete)]
    
    if len(trains_master) == initial_count:
        return jsonify({"error": f"Train {train_no_to_delete} not found in master list."}), 404

    with open(TRAINS_MASTER_FILE, 'w') as f:
        json.dump(trains_master, f, indent=4)

    state = read_state()
    state['arrivingTrains'] = [t for t in state['arrivingTrains'] if str(t['trainNo']) != str(train_no_to_delete)]
    
    log_action(f"TRAIN DELETED: Train {train_no_to_delete} removed from the master schedule.")
    write_state(state)
    return jsonify({"message": f"Train {train_no_to_delete} deleted successfully."})


if __name__ == "__main__":
    initialize_station_state() 
    app.run(port=5000, debug=True, threaded=True)

