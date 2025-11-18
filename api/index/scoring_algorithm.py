import re
import numpy as np

class ScoringTrain:
    def __init__(self, train_id, train_name, train_type, is_terminating, length, needs_platform, direction, zone, historical_platform=None):
        self.id = train_id
        self.name = train_name
        self.type = train_type
        self.is_terminating = is_terminating
        self.length = length
        self.needs_platform = needs_platform
        self.direction = direction
        self.historical_platform = historical_platform
        self.zone = zone


def normalize_historical_platform(raw):
    """Normalize various historical platform formats to canonical 'P<n>' form.
    Accepts values like '1', 'P1', 'Platform 1', 'P1,P3' and returns 'P1' or None.
    """
    if not raw:
        return None
    s = str(raw).strip().upper()
    # If multiple values present, take the first
    s = s.split(',')[0].strip()
    # Remove common prefixes like 'PLATFORM' or a leading 'P'
    s = re.sub(r'^PLATFORM\s*', '', s)
    s = re.sub(r'^P\s*', '', s)
    s = s.strip()
    if not s:
        return None
    return f"P{s}"
        
NON_PLATFORM_TRACKS = {'T1', 'T2', 'T3', 'T4', 'T5', 'T6'}
UP_TERMINATING = {'P1A', 'P2A'}
DOWN_TERMINATING = {'P3A', 'P4A'}

def _tie_break_rank(direction: str, platform_id: str) -> int:
    if platform_id in {'P1', 'P3'}:
        bucket = 'P1-3'
    elif platform_id in {'P2', 'P4'}:
        bucket = 'P2-4'
    else:
        bucket = platform_id

    # Directional tie-break order; include all platforms that may appear
    # Spec:
    #  - UP:   P2-4 > P1-3 > P5 > P6 > P8 > P7
    #  - DOWN: P8 > P7 > P6 > P5 > P2-4 > P1-3
    up_order = ['P2-4', 'P1-3', 'P5', 'P6', 'P8']
    down_order = ['P8', 'P7', 'P6', 'P5', 'P2-4', 'P1-3']
    order = up_order if str(direction).upper() == 'UP' else down_order
    # Gracefully handle buckets not present in the ordering (e.g., P1A/P3A)
    try:
        return order.index(bucket)
    except ValueError:
        return len(order)

def get_available_platforms(frontend_platforms):

    free_platforms = set()
    for p in frontend_platforms:
        if not p.get('isOccupied') and not p.get('isUnderMaintenance'):
            parts = p['id'].split(' ')
            if len(parts) == 2:
                simple_id = f"{'P' if parts[0] == 'Platform' else 'T'}{parts[1]}"
                free_platforms.add(simple_id)
    return free_platforms

def calculate_platform_scores(incoming_train, available_platforms, incoming_line, blockage_matrix):

    platform_scores = {}
    line_data = blockage_matrix.get(incoming_line, {})
    
    for platform_id in available_platforms:
        if platform_id.startswith('T'):
            continue

        matrix_column = platform_id
        if platform_id in {'P1', 'P3'}: matrix_column = 'P1-3'
        if platform_id in {'P2', 'P4'}: matrix_column = 'P2-4'

        routes = line_data.get(matrix_column)

        if not routes:
            continue

        route_scores = []
        for route in routes:
            full_blockages = len(route.get('full', []))
            partial_blockages = len(route.get('partial', []))
            score = (1 * full_blockages + 0.5 * partial_blockages)
            route_scores.append(score)

        if route_scores:
            platform_scores[platform_id] = np.mean(route_scores)

    ranked_platforms = list(platform_scores.items())

    def sort_key(item):
        platform_id, score = item

        hist_id = normalize_historical_platform(incoming_train.historical_platform)
        priority_historical = 0 if (hist_id and hist_id == platform_id) else 1

        priority_special = 1
        if incoming_train.is_terminating:
            terminating_set = UP_TERMINATING if incoming_train.direction == 'UP' else DOWN_TERMINATING
            if platform_id in terminating_set:
                priority_special = 0

        numeric_score = score

        tie_rank = _tie_break_rank(incoming_train.direction, platform_id)

        return (priority_historical, priority_special, numeric_score, tie_rank)

    ranked_platforms.sort(key=sort_key)

    final_suggestions = []
    for platform_id, score in ranked_platforms:
        best_route_info = "Not Applicable"
        
        matrix_column = platform_id
        if platform_id in {'P1', 'P3'}: matrix_column = 'P1-3'
        if platform_id in {'P2', 'P4'}: matrix_column = 'P2-4'
        
        if matrix_column in line_data:
            routes = line_data.get(matrix_column, [])
            if routes:
                best_route = min(routes, key=lambda r: (1 * len(r.get('full', [])) + 0.5 * len(r.get('partial', []))) / 1.5)
                full = ', '.join(best_route.get('full', []))
                part = ', '.join(best_route.get('partial', []))
                best_route_info = f": [{full or part or 'None'}]"

        # Indicate whether this platform matched the train's historical platform
        historical_platform = None
        historical_match = False
        historical_platform = normalize_historical_platform(incoming_train.historical_platform)
        historical_match = True if (historical_platform and historical_platform == platform_id) else False

        final_suggestions.append({
            "platformId": platform_id,
            "score": round(score, 2),
            "blockages": best_route_info,
            "historicalMatch": historical_match,
            "historicalPlatform": historical_platform
        })
        
    return final_suggestions

