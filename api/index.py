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
# Assuming scoring_algorithm.py exists and is correctly implemented
try:
    from scoring_algorithm import ScoringTrain, get_available_track_sets, calculate_platform_scores, LOWEST, HIGHEST, BORDER_STN_PRIO
except ImportError:
    # Mocking for environments where the module might be missing
    print("Warning: scoring_algorithm.py not found. Using mock implementation.")
    ScoringTrain = dict
    def get_available_track_sets(platforms): return []
    def calculate_platform_scores(train, tracks): return []
    LOWEST, HIGHEST, BORDER_STN_PRIO = 0, 100, 60


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
                all_track_definitions = platforms_data.get('tracks', [])
                
                for track_data in all_track_definitions:
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
                for row in trains_data:
                    initial_schedule.append({
                        "trainNo": str(row['TRAIN NO']),
                        "name": row['TRAIN NAME'],
                        "scheduled_arrival": row.get('ARRIVAL AT KGP'),
                        "scheduled_departure": row.get('DEPARTURE FROM KGP')
                    })
                
                initial_state = {
                    "platforms": initial_platforms,
                    "arrivingTrains": sorted(initial_schedule, key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99'),
                    "waitingList": []
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
    is_long_train = train_data.get('LENGTH', 'long').lower() == 'long'
    
    incoming_train = ScoringTrain(
        train_id=train_data.get('TRAIN NO'),
        train_name=train_data.get('TRAIN NAME'),
        train_type='Freight' if is_freight else 'Passenger',
        is_terminating=train_data.get('ISTERMINATING', False),
        length=train_data.get('LENGTH', 'Long').lower(),
        needs_platform=freight_needs_platform if is_freight else True,
        direction=train_data.get('DIRECTION'),
        historical_platform=str(train_data.get('PLATFORM NO', '')).split(',')[0].strip(),
        zone=train_data.get('ZONE'),
        days=train_data.get('DAYS'),
        origin=train_data.get('ORIGIN FROM STATION'),
        departure_origin=train_data.get('DEPARTURE FROM ORIGIN'),
        terminal=train_data.get('TERMINAL'),
        arrival_kgp=train_data.get('ARRIVAL AT KGP'),
        departure_kgp=train_data.get('DEPARTURE FROM KGP'),
        destination=train_data.get('DESTINATION'),
        arrival_destination=train_data.get('ARRIVAL AT DESTINATION')
    )

    available_tracks = get_available_track_sets(frontend_platforms)
    ranked_scores_list = calculate_platform_scores(incoming_train, available_tracks)
    
    ranked_scores_map = dict(ranked_scores_list)

    suggestions = []
    processed_tracks = set()

    if is_long_train:
        if 'P1' in ranked_scores_map and 'P3' in ranked_scores_map:
            # The score for the pair is the highest of the individual scores.
            combined_score = max(ranked_scores_map.get('P1'), ranked_scores_map.get('P3'))
            suggestions.append({
                "platformId": "Platform 1 & 3",
                "score": combined_score,
                "platformIds": ["Platform 1", "Platform 3"]
            })
            processed_tracks.update(['P1', 'P3'])

        if 'P2' in ranked_scores_map and 'P4' in ranked_scores_map:
            # The score for the pair is the highest of the individual scores.
            combined_score = max(ranked_scores_map.get('P2'), ranked_scores_map.get('P4'))
            suggestions.append({
                "platformId": "Platform 2 & 4",
                "score": combined_score,
                "platformIds": ["Platform 2", "Platform 4"]
            })
            processed_tracks.update(['P2', 'P4'])
    

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
    state['arrivingTrains'] = [t for t in state['arrivingTrains'] if t['trainNo'] != train_no]
    
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

    if not any(t['trainNo'] == train_no for t in state['arrivingTrains']):
        state['arrivingTrains'].append(train_to_remove)
        state['arrivingTrains'].sort(key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99')

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
    
    train_to_assign = next((t for t in state['arrivingTrains'] if t['trainNo'] == train_no), None)
    is_from_waiting_list = False
    
    if not train_to_assign:
        train_to_assign = next((t for t in state.get('waitingList', []) if t['trainNo'] == train_no), None)
        is_from_waiting_list = True

    if not train_to_assign:
        return jsonify({"error": "Train not found in arriving or waiting lists."}), 404

    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    train_data = next((t for t in trains_master if str(t.get('TRAIN NO')) == str(train_no)), None)
    
    stoppage_seconds = time_difference_seconds(train_data.get('ARRIVAL AT KGP'), train_data.get('DEPARTURE FROM KGP'))

    is_linked_assignment = len(platform_ids) > 1
    linked_map = {}
    if is_linked_assignment:
        linked_map = {platform_ids[0]: platform_ids[1], platform_ids[1]: platform_ids[0]}

    for platform_id in platform_ids:
        platform_to_update = next((p for p in state['platforms'] if p['id'] == platform_id), None)
        if platform_to_update:
            train_details = { "trainNo": train_to_assign['trainNo'], "name": train_to_assign['name'] }
            if is_linked_assignment:
                train_details['linkedPlatformId'] = linked_map[platform_id]

            platform_to_update['isOccupied'] = True
            platform_to_update['trainDetails'] = train_details
            platform_to_update['actualArrival'] = actual_arrival
            
            if stoppage_seconds > 0:
                timer = threading.Timer(stoppage_seconds, push_departure_alert, args=[train_no, train_data.get('TRAIN NAME'), platform_id])
                with timers_lock:
                    active_timers[platform_id] = timer
                timer.start()
                print(f"Departure timer set for {platform_id} in {stoppage_seconds} seconds.")

    if is_from_waiting_list:
        state['waitingList'] = [t for t in state.get('waitingList', []) if t['trainNo'] != train_no]
    else:
        state['arrivingTrains'] = [t for t in state['arrivingTrains'] if t['trainNo'] != train_no]


    log_action(f"ARRIVED & ASSIGNED: Train {train_no} arrived at {actual_arrival} and assigned to {', '.join(platform_ids)}.")
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
            print(f"Cancelled timer for {platform_id}.")

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
        
    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    
    train_master_data = next((t for t in trains_master if str(t.get('TRAIN NO')) == str(train_details['trainNo'])), None)
    
    if train_master_data:
        unassigned_train_obj = {
            "trainNo": train_details['trainNo'],
            "name": train_details['name'],
            "scheduled_arrival": train_master_data.get('ARRIVAL AT KGP'),
            "scheduled_departure": train_master_data.get('DEPARTURE FROM KGP')
        }
        if not any(t['trainNo'] == unassigned_train_obj['trainNo'] for t in state['arrivingTrains']):
            state['arrivingTrains'].append(unassigned_train_obj)
            state['arrivingTrains'].sort(key=lambda x: x.get('scheduled_arrival') or x.get('scheduled_departure') or '99:99')

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
    write_state(state)
    return jsonify({"message": f"Train {train_details['trainNo']} departed from {', '.join(cleared_platforms)}."})


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
    new_train_data = request.get_json()
    with open(TRAINS_MASTER_FILE, 'r') as f:
        trains_master = json.load(f)
    
    if str(new_train_data.get('TRAIN NO')) in [str(t.get('TRAIN NO')) for t in trains_master]:
        return jsonify({"error": f"Train number {new_train_data.get('TRAIN NO')} already exists."}), 409

    for key in ['PLATFORM NO', 'DEPARTURE FROM ORIGIN', 'TERMINAL', 'ARRIVAL AT DESTINATION']:
        if key not in new_train_data:
            new_train_data[key] = ""

    trains_master.append(new_train_data)
    with open(TRAINS_MASTER_FILE, 'w') as f:
        json.dump(trains_master, f, indent=4)

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
    state['waitingList'] = [t for t in state.get('waitingList', []) if str(t['trainNo']) != str(train_no_to_delete)]
    
    log_action(f"TRAIN DELETED: Train {train_no_to_delete} removed from the master schedule.")
    write_state(state)
    return jsonify({"message": f"Train {train_no_to_delete} deleted successfully."})


if __name__ == "__main__":
    initialize_station_state() 
    app.run(port=5000, debug=True, threaded=True)


