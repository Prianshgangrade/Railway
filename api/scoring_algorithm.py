
# --- Scoring Constants ---
HIGHEST = 100
LOWEST = 0
MIN_POSSIBLE = 10
HISTORICAL_PREF = 80
BORDER_STN_PRIO = 60
NON_TERMINAL_DOWN = 50
NON_TERMINAL_UP = 50 
DIRECTION_MATCH = 20
THROUGH = 40

# --- Helper Class for Scoring ---
class ScoringTrain:
    """A simplified Train object specifically for the scoring algorithm."""
    def __init__(self, train_id, train_name, train_type, is_terminating, length, needs_platform, direction,zone, historical_platform=None,days=None,
                 origin=None, departure_origin=None,
                 terminal=None, arrival_kgp=None, departure_kgp=None,
                 destination=None, arrival_destination=None):
        self.id = train_id
        self.name = train_name
        self.type = train_type
        self.is_terminating = is_terminating
        self.length = length
        self.needs_platform = needs_platform
        self.direction = direction
        self.historical_platform = historical_platform
        self.zone=zone
        self.days = days
        self.origin = origin
        self.departure_origin = departure_origin
        self.terminal = terminal
        self.arrival_kgp = arrival_kgp
        self.departure_kgp = departure_kgp
        self.destination = destination
        self.arrival_destination = arrival_destination
        

# --- Predefined Track Sets (Corrected Layout) ---
DOWN_NonPlatform_tracks = {'T7', 'T8', 'T9', 'T10', 'T11', 'T12'}
UP_NonPlatform_tracks = {'T1', 'T2', 'T3', 'T4', 'T5', 'T6'}
DOWN_Terminating = {'P3A', 'P4A'}
DOWN_middle = {'P5', 'P6'}
DOWN_border = {'P7', 'P8'}
UP_Terminating = {'P1A', 'P2A'}
UP_middle = {'P2', 'P4'}
UP_border = {'P1', 'P3'}

NonPlatform_tracks = DOWN_NonPlatform_tracks.union(UP_NonPlatform_tracks)
DOWN_NonTerminating = DOWN_middle.union(DOWN_border)
DOWN_All_Platform = DOWN_Terminating.union(DOWN_NonTerminating)
UP_NonTerminating = UP_middle.union(UP_border)
UP_All_Platform = UP_Terminating.union(UP_NonTerminating)
Platform_tracks = DOWN_All_Platform.union(UP_All_Platform)
All_track_ids = NonPlatform_tracks.union(Platform_tracks)

def get_available_track_sets(frontend_platforms):
    """
    Filters the master track sets to only include tracks marked as 'FREE' (not occupied or under maintenance).
    """
    # Create a map of platform IDs to their state for quick lookup
    platform_state_map = {p['id']: ('OCCUPIED' if p.get('isOccupied') else 'MAINTENANCE' if p.get('isUnderMaintenance') else 'FREE') for p in frontend_platforms}

    free_tracks = {
        'DOWN_NonPlatform': {tid for tid in DOWN_NonPlatform_tracks if platform_state_map.get(f"Track {tid.replace('T', '')}") == 'FREE'},
        'UP_NonPlatform': {tid for tid in UP_NonPlatform_tracks if platform_state_map.get(f"Track {tid.replace('T', '')}") == 'FREE'},
        'DOWN_Terminating': {tid for tid in DOWN_Terminating if platform_state_map.get(f"Platform {tid.replace('P', '')}") == 'FREE'},
        'DOWN_middle': {tid for tid in DOWN_middle if platform_state_map.get(f"Platform {tid.replace('P', '')}") == 'FREE'},
        'DOWN_border': {tid for tid in DOWN_border if platform_state_map.get(f"Platform {tid.replace('P', '')}") == 'FREE'},
        'UP_Terminating': {tid for tid in UP_Terminating if platform_state_map.get(f"Platform {tid.replace('P', '')}") == 'FREE'},
        'UP_middle': {tid for tid in UP_middle if platform_state_map.get(f"Platform {tid.replace('P', '')}") == 'FREE'},
        'UP_border': {tid for tid in UP_border if platform_state_map.get(f"Platform {tid.replace('P', '')}") == 'FREE'}
    }
    
    free_tracks['Platform'] = free_tracks['DOWN_Terminating'].union(free_tracks['DOWN_middle'], free_tracks['DOWN_border'],
                                                                    free_tracks['UP_Terminating'], free_tracks['UP_middle'], free_tracks['UP_border'])
    free_tracks['DOWN_All_Platform'] = free_tracks['DOWN_Terminating'].union(free_tracks['DOWN_middle'], free_tracks['DOWN_border'])
    free_tracks['UP_All_Platform'] = free_tracks['UP_Terminating'].union(free_tracks['UP_middle'], free_tracks['UP_border'])
    free_tracks['DOWN_NonTerminating'] = free_tracks['DOWN_middle'].union(free_tracks['DOWN_border'])
    free_tracks['UP_NonTerminating'] = free_tracks['UP_middle'].union(free_tracks['UP_border'])

    return free_tracks


def calculate_platform_scores(incoming_train, available_tracks):
    """
    Calculates scores for available tracks using predefined sets and dictionary updates.
    This logic is preserved exactly from the user's specification.
    """
    scores = {track_id: LOWEST for track_id in All_track_ids}

    if incoming_train.type == 'Freight':
        if incoming_train.needs_platform:
            scores.update(dict.fromkeys(available_tracks['Platform'], HIGHEST))
        else:
            if incoming_train.direction == 'DOWN':
                scores.update(dict.fromkeys(available_tracks['DOWN_NonPlatform'], HIGHEST))
            elif incoming_train.direction == 'UP':
                scores.update(dict.fromkeys(available_tracks['UP_NonPlatform'], HIGHEST))

    else:
        scores.update(dict.fromkeys(available_tracks['Platform'], MIN_POSSIBLE))
        
        hist_platform_id = f"P{incoming_train.historical_platform}"
        if incoming_train.historical_platform and hist_platform_id in available_tracks['Platform']:
            scores[hist_platform_id] = HISTORICAL_PREF

        if incoming_train.direction == 'UP':
                
            if incoming_train.is_terminating:   
                scores.update(dict.fromkeys(available_tracks['UP_Terminating'], HIGHEST))
            else: # Non-terminating
                scores.update(dict.fromkeys(available_tracks['UP_NonTerminating'], NON_TERMINAL_UP))
                scores.update(dict.fromkeys(available_tracks['DOWN_NonTerminating'], THROUGH))
                if incoming_train.length.lower() == 'short':
                    scores.update(dict.fromkeys(available_tracks['UP_middle'], HIGHEST))
                    scores.update(dict.fromkeys(available_tracks['UP_border'], BORDER_STN_PRIO))
                
                elif incoming_train.length == 'long':
                    if {'P2', 'P4'}.issubset(available_tracks['UP_middle']):
                        # If both are free, score them highly as a pair.
                        scores.update(dict.fromkeys(available_tracks['UP_middle'].intersection({'P2', 'P4'}), HIGHEST))
                    else:
                        if 'P2' in available_tracks['UP_middle']: scores['P2'] = LOWEST
                        if 'P4' in available_tracks['UP_middle']: scores['P4'] = LOWEST

                    if {'P1', 'P3'}.issubset(available_tracks['UP_border']):
                        scores.update(dict.fromkeys(available_tracks['UP_border'].intersection({'P1', 'P3'}), BORDER_STN_PRIO))
                    else:
                        if 'P1' in available_tracks['UP_border']: scores['P1'] = LOWEST
                        if 'P3' in available_tracks['UP_border']: scores['P3'] = LOWEST
        
        elif incoming_train.direction == 'DOWN':

            if incoming_train.is_terminating:
                scores.update(dict.fromkeys(available_tracks['DOWN_Terminating'], HIGHEST))
            else: # Non-terminating
                scores.update(dict.fromkeys(available_tracks['DOWN_middle'], HIGHEST))
                scores.update(dict.fromkeys(available_tracks['DOWN_border'], BORDER_STN_PRIO))
                scores.update(dict.fromkeys(available_tracks['UP_NonTerminating'], THROUGH))

    ranked_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked_scores

