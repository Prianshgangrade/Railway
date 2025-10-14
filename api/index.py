from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import threading
import time
import queue
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import certifi # <-- ADDED THIS LINE

# --- Load Environment Variables ---
load_dotenv()

# --- MongoDB Connection Setup ---
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    print("\n--- FATAL ERROR ---")
    print("MONGO_URI not found in environment variables.")
    print("Please create an '.env' file in the '/api' directory and add your MongoDB connection string.")
    print("-------------------\n")
    exit()

try:
    # --- THIS IS THE MODIFIED LINE ---
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where()) 
    # --- END MODIFICATION ---
    db = client.get_database('railwayDB')
    trains_collection = db['trains']
    platforms_collection = db['platforms']
    state_collection = db['station_state']
    logs_collection = db['operations_log']
    print("DEBUG: MongoDB connection successful.")
except Exception as e:
    print(f"\n--- MONGODB CONNECTION ERROR ---")
    print(f"Could not connect to MongoDB. Error: {e}")
    print("Please check your MONGO_URI in the .env file and your network connection.")
    print("--------------------------------\n")
    exit()


# --- Import the scoring algorithm module ---
try:
    from scoring_algorithm import ScoringTrain, get_available_track_sets, calculate_platform_scores, LOWEST, HIGHEST, BORDER_STN_PRIO
except ImportError:
    print("Warning: scoring_algorithm.py not found.")

app = Flask(__name__)
CORS(app)

# --- In-memory state for real-time events ---
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
    state_collection.replace_one({"_id": "current_station_state"}, new_state, upsert=True)


# --- The rest of your Flask app ---

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
    return jsonify(read_state())

@app.route("/api/logs")
def get_logs():
    log_entries = list(logs_collection.find().sort("timestamp", -1).limit(100))
    logs_json = [{"timestamp": log['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), "action": log['action']} for log in log_entries]
    return jsonify(logs_json)

@app.route("/api/platform-suggestions", methods=['POST'])
def get_platform_suggestions():
    request_data = request.get_json()
    train_no = request_data.get('trainNo')
    frontend_platforms = request_data.get('platforms')
    freight_needs_platform = request_data.get('freightNeedsPlatform')

    train_data = trains_collection.find_one({"TRAIN NO": train_no})
    if not train_data:
        train_data = trains_collection.find_one({"TRAIN NO": str(train_no)})
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
            combined_score = max(ranked_scores_map.get('P1'), ranked_scores_map.get('P3'))
            suggestions.append({
                "platformId": "Platform 1 & 3", "score": combined_score,
                "platformIds": ["Platform 1", "Platform 3"]
            })
            processed_tracks.update(['P1', 'P3'])

        if 'P2' in ranked_scores_map and 'P4' in ranked_scores_map:
            combined_score = max(ranked_scores_map.get('P2'), ranked_scores_map.get('P4'))
            suggestions.append({
                "platformId": "Platform 2 & 4", "score": combined_score,
                "platformIds": ["Platform 2", "Platform 4"]
            })
            processed_tracks.update(['P2', 'P4'])
    
    for track_id, score in ranked_scores_list:
        if score > LOWEST and track_id not in processed_tracks:
            display_id = f"Platform {track_id.replace('P','')}" if track_id.startswith('P') else f"Track {track_id.replace('T','')}"
            suggestions.append({"platformId": display_id, "score": score, "platformIds": [display_id]})
    
    suggestions.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({"suggestions": suggestions})

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
    
    train_data = trains_collection.find_one({"TRAIN NO": str(train_no)})
    
    stoppage_seconds = time_difference_seconds(train_data.get('ARRIVAL AT KGP'), train_data.get('DEPARTURE FROM KGP'))
    is_linked_assignment = len(platform_ids) > 1
    linked_map = {platform_ids[0]: platform_ids[1], platform_ids[1]: platform_ids[0]} if is_linked_assignment else {}
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

    train_master_data = trains_collection.find_one({"TRAIN NO": str(train_details['trainNo'])})
    if train_master_data:
        unassigned_train_obj = {
            "trainNo": train_details['trainNo'], "name": train_details['name'],
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
    
    for i, p in enumerate(state['platforms']):
        if p['id'] == platform_id:
            state['platforms'][i]['isUnderMaintenance'] = not state['platforms'][i]['isUnderMaintenance']
            status = "ON" if state['platforms'][i]['isUnderMaintenance'] else "OFF"
            break
    
    log_action(f"MAINTENANCE: Maintenance for {platform_id} set to {status}.")
    write_state(state)
    return jsonify({"message": f"Maintenance status toggled for {platform_id}."})


# When running locally, run Flask directly
if __name__ == "__main__":
    with app.app_context():
        initialize_station_state()
    app.run(host="0.0.0.0", port=5000, debug=True)

