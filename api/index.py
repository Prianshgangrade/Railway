from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sse import sse
import os
import json
from datetime import datetime, timedelta
import threading
import shutil

app = Flask(__name__)
CORS(app)
app.config["REDIS_URL"] = "redis://localhost:6379"
app.register_blueprint(sse, url_prefix='/stream')

API_DIR = os.path.dirname(__file__)
STATE_FILE = os.path.join(API_DIR, 'station_state.json')
PLATFORMS_MASTER_FILE = os.path.join(API_DIR, 'platforms.json')
TRAINS_MASTER_FILE = os.path.join(API_DIR, 'trains.json')

# Global State for Timers
active_timers = {}
timers_lock = threading.Lock()
state_lock = threading.Lock()

def initialize_station_state():
    with state_lock:
        if not os.path.exists(STATE_FILE):
            print("State file not found. Initializing from master data...")
            try:
                with open(PLATFORMS_MASTER_FILE, 'r') as f:
                    platforms_data = json.load(f)
                with open(TRAINS_MASTER_FILE, 'r') as f:
                    trains_data = json.load(f)

                initial_platforms = [{
                    "id": f"Platform {row['platform_id']}" if not row.get('is_freight') else f"Track {row['platform_id']}",
                    "yard": row['direction'],
                    "type": "Freight Track" if row.get('is_freight') else "Platform",
                    "isOccupied": False,
                    "trainDetails": None,
                    "isUnderMaintenance": False,
                    "length": row['length'],
                    "isTerminating": bool(row.get('is_terminating', False))
                } for row in platforms_data]

                initial_arriving_trains = [{
                    "trainNo": str(row['trainNumber']),
                    "name": f"{row['train_type']} Train",
                    "origin": row['source'],
                    "scheduled_arrival": row['scheduled_arrival']
                } for row in trains_data]

                initial_state = {
                    "platforms": initial_platforms,
                    "arrivingTrains": sorted(initial_arriving_trains, key=lambda x: x['scheduled_arrival']),
                    "departedTrains": []
                }
                
                with open(STATE_FILE, 'w') as f:
                    json.dump(initial_state, f, indent=2)
                print("State file initialized successfully.")

            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"FATAL: Could not initialize state file. Error: {e}")
                exit(1)

def read_state():
    with state_lock:
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            initialize_station_state()
            with open(STATE_FILE, 'r') as f:
                return json.load(f)

def write_state(new_state):
    with state_lock:
        temp_file = STATE_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(new_state, f, indent=2)
        shutil.move(temp_file, STATE_FILE) 
    broadcast_state_update() 

def broadcast_state_update():
    state = read_state()
    with app.app_context():
        sse.publish(json.dumps(state), type='state_update')
    print("Broadcasted state update to all clients.")

class TimeUtils:
    @staticmethod
    def parse_time(time_str):
        if not time_str or not isinstance(time_str, str): return None
        try:
            return datetime.strptime(time_str, '%H:%M')
        except (ValueError, TypeError):
            return None

    @staticmethod
    def time_difference_minutes(time1, time2):
        t1 = TimeUtils.parse_time(time1)
        t2 = TimeUtils.parse_time(time2)
        if t1 is None or t2 is None: return 0
        if t2 < t1: t2 += timedelta(days=1)
        return (t2 - t1).total_seconds() / 60

class Train:
    def __init__(self, train_data):
        self.train_id = train_data.get('trainNumber')
        self.train_type = train_data.get('train_type')
        self.length = int(train_data.get('length', self._get_default_length()))
        self.direction = train_data.get('direction')
        self.destination = train_data.get('destination')
        self.priority = int(train_data.get('priority', self._get_default_priority()))
        self.platform_assigned = train_data.get('platform_assigned')
        self.scheduled_arrival = train_data.get('scheduled_arrival')
        self.scheduled_departure = train_data.get('scheduled_departure')

    def _get_default_priority(self):
        return {'Superfast': 3, 'Express': 2}.get(self.train_type, 1)

    def _get_default_length(self):
        return {'Superfast': 20, 'Express': 24, 'Freight': 28, 'Local': 10, 'Passenger': 18}.get(self.train_type, 15)

    def is_freight(self):
        return self.train_type == 'Freight'

    def is_long_train(self):
        return self.length > 22 

    def is_terminating(self):
        return self.destination == 'KGP'

    def is_memu(self):
        return 'MEMU' in str(self.train_type)

class Platform:
    def __init__(self, platform_data):
        self.platform_id = platform_data.get('platform_id')
        self.length = int(platform_data.get('length'))
        self.direction = platform_data.get('direction')
        self.is_freight = bool(platform_data.get('is_freight'))
        self.is_terminating = bool(platform_data.get('is_terminating'))

class ScoreCalculator:
    @staticmethod
    def calculate_score(train, platform, delay=0):
        score = 100
        reasons = []
        if train.length > platform.length:
            if not (train.is_long_train() and platform.platform_id in ['1', '2', '3', '4']):
                score -= 500
                reasons.append(f"Train too long")
        if train.direction != platform.direction:
            score -= 200
            reasons.append(f"Direction mismatch")
        if train.is_freight() and not platform.is_freight:
            score -= 500
            reasons.append("Freight on passenger platform")
        if not train.is_freight() and platform.is_freight:
            score -= 500
            reasons.append("Passenger on freight track")
        if (train.is_terminating() or train.is_memu()) and not platform.is_terminating:
            score -= 150
            reasons.append("Terminating on non-terminating platform")
        score += train.priority * 10
        if train.platform_assigned and str(platform.platform_id) == str(train.platform_assigned):
            score += 75
            reasons.append("Historical preference")
        if delay > 120:
            penalty = min(100, delay / 3)
            score -= penalty
            reasons.append(f"High delay (-{int(penalty)})")
        elif delay > 0:
            penalty = min(50, delay / 4)
            score -= penalty
            reasons.append(f"Delay (-{int(penalty)})")
        return score, reasons

def load_master_data():
    try:
        with open(PLATFORMS_MASTER_FILE, 'r') as f:
            platforms_data = json.load(f)
        with open(TRAINS_MASTER_FILE, 'r') as f:
            trains_data = json.load(f)
        return platforms_data, trains_data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading master JSON data: {e}")
        return None, None

#API Endpoints
@app.route("/api/station-data")
def get_station_data():
    state = read_state()
    return jsonify(state)

@app.route("/api/platform-suggestions", methods=['POST'])
def get_platform_suggestions():
    request_data = request.get_json()
    train_no = request_data.get('trainNo')
    frontend_platforms = request_data.get('platforms')
    actual_arrival = request_data.get('actualArrival')
    freight_needs_platform = request_data.get('freightNeedsPlatform')
    needs_multiple_platforms = request_data.get('needsMultiplePlatforms')

    platforms_master, trains_master = load_master_data()
    if platforms_master is None or trains_master is None:
        return jsonify({"error": "Server master data files (JSON) not found or are invalid."}), 500

    train_data_list = [t for t in trains_master if str(t.get('trainNumber')) == str(train_no)]
    if not train_data_list:
        return jsonify({"error": f"Train {train_no} not found."}), 404
    
    train = Train(train_data_list[0])
    delay = TimeUtils.time_difference_minutes(train.scheduled_arrival, actual_arrival)

    available_platforms = [p for p in frontend_platforms if not p.get('isOccupied') and not p.get('isUnderMaintenance')]
    
    # Filter based on train type
    if train.is_freight():
        if freight_needs_platform == False:
            available_platforms = [p for p in available_platforms if p['type'] == 'Freight Track']
    else: # If it's NOT a freight train, only show platforms
        available_platforms = [p for p in available_platforms if p['type'] == 'Platform']


    suggestions = []
    
    # Multi suggestions only if requested
    if needs_multiple_platforms:
        platform_map = {p['id']: p for p in available_platforms}
        if "Platform 1" in platform_map and "Platform 3" in platform_map:
            p1_master = next((p for p in platforms_master if p['platform_id'] == '1' and not p['is_freight']), None)
            if p1_master:
                score, reasons = ScoreCalculator.calculate_score(train, Platform(p1_master), delay)
                suggestions.append({"platformId": "Platform 1 & 3", "platformIds": ["Platform 1", "Platform 3"], "score": score + 50, "reasons": reasons + ["Combined platform"]})
        
        if "Platform 2" in platform_map and "Platform 4" in platform_map:
            p2_master = next((p for p in platforms_master if p['platform_id'] == '2' and not p['is_freight']), None)
            if p2_master:
                score, reasons = ScoreCalculator.calculate_score(train, Platform(p2_master), delay)
                suggestions.append({"platformId": "Platform 2 & 4", "platformIds": ["Platform 2", "Platform 4"], "score": score + 50, "reasons": reasons + ["Combined platform"]})

    # single platform suggestions
    for p_data in available_platforms:
        platform_numeric_id = str(p_data['id']).replace("Platform ", "").replace("Track ", "")
        is_freight_lookup = p_data['type'] == 'Freight Track'
        
        platform_master_list = [p for p in platforms_master if str(p.get('platform_id')) == platform_numeric_id and bool(p.get('is_freight')) == is_freight_lookup]

        if platform_master_list:
            platform = Platform(platform_master_list[0])
            score, reasons = ScoreCalculator.calculate_score(train, platform, delay)
            
            suggestions.append({
                "platformId": p_data['id'],
                "score": score,
                "reasons": reasons
            })
    
    sorted_suggestions = sorted(suggestions, key=lambda x: x['score'], reverse=True)
    
    return jsonify({
        "suggestions": sorted_suggestions,
        "delay": delay if delay > 0 else 0
    })

def push_departure_alert(train_id, train_type, platform_id):
    print(f"TIMER EXPIRED: Pushing departure alert for Train {train_id} from {platform_id}")
    with app.app_context():
        sse.publish(json.dumps({
            'train_number': train_id,
            'train_name': f"{train_type} Train",
            'platform_id': platform_id,
        }), type='departure_alert')
    
    with timers_lock:
        if platform_id in active_timers:
            del active_timers[platform_id]

@app.route("/api/assign-platform", methods=['POST'])
def assign_platform():
    data = request.get_json()
    train_no = data.get('trainNo')
    platform_ids = data.get('platformIds') 

    if not isinstance(platform_ids, list):
        return jsonify({"error": "platformIds must be a list."}), 400

    state = read_state()
    
    train_to_assign = next((t for t in state['arrivingTrains'] if t['trainNo'] == train_no), None)
    if not train_to_assign:
        return jsonify({"error": "Train not found in current state."}), 404

    for platform_id in platform_ids:
        platform_to_assign = next((p for p in state['platforms'] if p['id'] == platform_id), None)
        if platform_to_assign:
            platform_to_assign['isOccupied'] = True
            platform_to_assign['trainDetails'] = { "trainNo": train_to_assign['trainNo'], "name": train_to_assign['name'] }
        else:
            print(f"Warning: Platform {platform_id} not found during multi-assign.")

    state['arrivingTrains'] = [t for t in state['arrivingTrains'] if t['trainNo'] != train_no]
    write_state(state)

    _, trains_master = load_master_data()
    train_master_list = [t for t in trains_master if str(t.get('trainNumber')) == str(train_no)]
    if train_master_list:
        train = Train(train_master_list[0])
        stoppage_minutes = TimeUtils.time_difference_minutes(train.scheduled_arrival, train.scheduled_departure)
        stoppage_seconds = stoppage_minutes * 60
        
        if stoppage_seconds > 0:
            for platform_id in platform_ids:
                print(f"Train {train.train_id} assigned. Scheduling departure alert for {platform_id} in {stoppage_seconds:.0f} seconds.")
                timer = threading.Timer(stoppage_seconds, push_departure_alert, args=[train.train_id, train.train_type, platform_id])
                
                with timers_lock:
                    if platform_id in active_timers:
                        active_timers[platform_id].cancel()
                    active_timers[platform_id] = timer
                timer.start()

    return jsonify({"message": f"Train {train_no} assigned successfully. State updated."})

@app.route("/api/unassign-platform", methods=['POST'])
def unassign_platform():
    data = request.get_json()
    platform_id = data.get('platformId')

    if not platform_id:
        return jsonify({"error": "Platform ID is required."}), 400

    with timers_lock:
        if platform_id in active_timers:
            active_timers[platform_id].cancel()
            del active_timers[platform_id]
            print(f"Cancelled departure timer for {platform_id}.")

    state = read_state()
    platform_to_clear = next((p for p in state['platforms'] if p['id'] == platform_id), None)

    if not platform_to_clear or not platform_to_clear['isOccupied']:
        return jsonify({"error": "Platform not found or is not occupied."}), 404

    train_details = platform_to_clear['trainDetails']
    train_no_to_readd = train_details['trainNo']
    
    _, trains_master = load_master_data()
    if trains_master is None:
         return jsonify({"error": "Server master data file (trains.json) not found."}), 500

    original_train_data = next((t for t in trains_master if str(t.get('trainNumber')) == str(train_no_to_readd)), None)
    if not original_train_data:
        return jsonify({"error": f"Could not find original data for train {train_no_to_readd}."}), 500

    platform_to_clear['isOccupied'] = False
    platform_to_clear['trainDetails'] = None

    state['arrivingTrains'].append({
        "trainNo": str(original_train_data['trainNumber']),
        "name": f"{original_train_data['train_type']} Train",
        "origin": original_train_data['source'],
        "scheduled_arrival": original_train_data['scheduled_arrival']
    })
    state['arrivingTrains'].sort(key=lambda x: x['scheduled_arrival'])

    write_state(state)
    return jsonify({"message": f"Train {train_no_to_readd} unassigned from {platform_id}."})


@app.route("/api/depart-train", methods=['POST'])
def depart_train():
    data = request.get_json()
    platform_id = data.get('platformId')

    state = read_state()
    platform_to_free = next((p for p in state['platforms'] if p['id'] == platform_id), None)

    if not platform_to_free or not platform_to_free['isOccupied']:
        return jsonify({"error": "Platform not found or is not occupied."}), 404

    departed_train = platform_to_free['trainDetails']
    departed_train['departureTime'] = datetime.now().strftime('%H:%M')

    platform_to_free['isOccupied'] = False
    platform_to_free['trainDetails'] = None
    state['departedTrains'].insert(0, departed_train) 
    state['departedTrains'] = state['departedTrains'][:20] 

    with timers_lock:
        if platform_id in active_timers:
            active_timers[platform_id].cancel()
            del active_timers[platform_id]
            print(f"Cancelled departure timer for {platform_id} due to manual departure.")

    write_state(state)
    return jsonify({"message": f"Train {departed_train['trainNo']} departed from {platform_id}."})

@app.route("/api/toggle-maintenance", methods=['POST'])
def toggle_maintenance():
    data = request.get_json()
    platform_id = data.get('platformId')

    state = read_state()
    platform_to_toggle = next((p for p in state['platforms'] if p['id'] == platform_id), None)

    if not platform_to_toggle:
        return jsonify({"error": "Platform not found."}), 404
    
    if platform_to_toggle['isOccupied']:
        return jsonify({"error": "Cannot change maintenance on an occupied platform."}), 400

    platform_to_toggle['isUnderMaintenance'] = not platform_to_toggle['isUnderMaintenance']
    
    write_state(state)
    return jsonify({"message": f"Maintenance status toggled for {platform_id}."})

@app.route("/api/add-train", methods=['POST'])
def add_train():
    new_train_data = request.get_json()
    
    required_keys = ['trainNumber', 'train_type', 'length', 'direction', 'source', 'destination', 'scheduled_arrival', 'scheduled_departure', 'priority']
    if not all(k in new_train_data for k in required_keys):
        return jsonify({"error": "Missing required train data."}), 400

    _, trains_master = load_master_data()
    if trains_master is None:
        return jsonify({"error": "Server master data file (trains.json) not found."}), 500
    
    if str(new_train_data['trainNumber']) in [str(t.get('trainNumber')) for t in trains_master]:
        return jsonify({"error": f"Train number {new_train_data['trainNumber']} already exists."}), 409

    trains_master.append(new_train_data)
    
    with open(TRAINS_MASTER_FILE, 'w') as f:
        json.dump(trains_master, f, indent=2)

    state = read_state()
    state['arrivingTrains'].append({
        "trainNo": str(new_train_data['trainNumber']),
        "name": f"{new_train_data['train_type']} Train",
        "origin": new_train_data.get('source', 'N/A'),
        "scheduled_arrival": new_train_data.get('scheduled_arrival', 'N/A')
    })
    state['arrivingTrains'].sort(key=lambda x: x['scheduled_arrival'])
    
    write_state(state)

    return jsonify({"message": f"Train {new_train_data['trainNumber']} added successfully."})

@app.route("/api/delete-train", methods=['POST'])
def delete_train():
    data = request.get_json()
    train_no_to_delete = data.get('trainNo')

    if not train_no_to_delete:
        return jsonify({"error": "Train number is required."}), 400

    _, trains_master = load_master_data()
    if trains_master is None:
        return jsonify({"error": "Server master data file (trains.json) not found."}), 500
    
    initial_count = len(trains_master)
    trains_master = [t for t in trains_master if str(t.get('trainNumber')) != str(train_no_to_delete)]
    
    if len(trains_master) == initial_count:
        return jsonify({"error": f"Train {train_no_to_delete} not found in master list."}), 404

    with open(TRAINS_MASTER_FILE, 'w') as f:
        json.dump(trains_master, f, indent=2)

    state = read_state()
    state['arrivingTrains'] = [t for t in state['arrivingTrains'] if str(t['trainNo']) != str(train_no_to_delete)]
    
    write_state(state)

    return jsonify({"message": f"Train {train_no_to_delete} deleted successfully."})

if __name__ == "__main__":
    initialize_station_state() 
    app.run(port=5000, debug=True, threaded=True)
