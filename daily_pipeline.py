import pandas as pd
import numpy as np
from utils import init_connection_1
import joblib
from datetime import datetime

supabase = init_connection_1()

# PHASE 4: RETRIEVE DATA FOR PREDICTION
def fetch_phase4_data(target_date_str, operator_id):
    print(f"--- Phase 4: Fetching Data for {operator_id} on {target_date_str} ---")
    
    # 4.1 Retrieve Flights
    flight_res = supabase.table("flight_list").select(
        "flight_number, day_of_week, departure_airport, scheduled_departure_time_utc, route_type, route_category, used_variant_1, used_variant_2, used_variant_3"
    ).eq("operator_id", operator_id).execute()
    df_flights = pd.DataFrame(flight_res.data)
    
    # 4.2 Retrieve Fleet Status + Variant from the inner 'fleet' table
    fleet_status_res = supabase.table("fleet_status").select(
        "aircraft_reg, current_airport, next_ready_utc, fleet!inner(variant, min_turnaround_min)"
    ).eq("operator_icao", operator_id).execute()
    df_fleet_status = pd.DataFrame(fleet_status_res.data)

    # Flatten the nested fleet data
    df_fleet_status['min_turnaround_min'] = df_fleet_status['fleet'].apply(lambda x: x['min_turnaround_min'])
    df_fleet_status['variant'] = df_fleet_status['fleet'].apply(lambda x: x['variant'])

    # 4.3 Retrieve Aircraft Type Capabilities
    aircraft_type_res = supabase.table("aircraft_type").select("variant, body_type, range_category").execute()
    df_aircraft_type = pd.DataFrame(aircraft_type_res.data)

    # Merge the capabilities into our candidate fleet
    df_fleet_status = df_fleet_status.merge(df_aircraft_type, on="variant", how="left")
       
    # Standardize Datetimes for mathematical comparison
    df_flights['scheduled_departure_datetime'] = pd.to_datetime(target_date_str + ' ' + df_flights['scheduled_departure_time_utc'])
    df_flights['departure_hour'] = df_flights['scheduled_departure_datetime'].dt.hour
    df_fleet_status['next_ready_utc'] = pd.to_datetime(df_fleet_status['next_ready_utc']).dt.tz_localize(None)

    return df_flights, df_fleet_status

# PHASE 5: PREDICT AIRCRAFT REGISTRATION
def run_phase5_prediction(df_flights, df_fleet_status, operator_id):
    print(f"--- Phase 5: Running ML Inference for {operator_id} ---")
    
    try:
        model = joblib.load(f"model_registry/model_{operator_id}.pkl")
        encoder = joblib.load(f"model_registry/encoder_{operator_id}.pkl")
    except FileNotFoundError:
        print(f"Warning: No ML model found for {operator_id}. Skipping.")
        return

    predictions_to_insert = []
    
    # Sort chronologically to prevent late flights from stealing planes from early flights
    df_flights = df_flights.sort_values('scheduled_departure_datetime')

    for _, flight in df_flights.iterrows():
        # 5.2 MASKING: Filter fleet by Location and Readiness
        mask_location = df_fleet_status['current_airport'] == flight['departure_airport']
        mask_time = df_fleet_status['next_ready_utc'] < flight['scheduled_departure_datetime']
        mask_range = df_fleet_status['range_category'] == flight['route_category']

        # Apply all constraints
        valid_candidates = df_fleet_status[mask_location & mask_time & mask_range].copy()
        
        if valid_candidates.empty:
            predictions_to_insert.append({
                "flight_number": flight['flight_number'],
                "predicted_reg": "UNASSIGNED",
                "confidence_score": 0.0,
                "prediction_reason": "No aircraft available at airport matching time constraints."
            })
            continue

        # 5.3 ML INFERENCE: Calculate dynamic features and ask the model
        valid_candidates['available_ground_time_min'] = (
            flight['scheduled_departure_datetime'] - valid_candidates['next_ready_utc']
        ).dt.total_seconds() / 60.0

        X_pred = pd.DataFrame({
            'day_of_week': [flight['day_of_week']] * len(valid_candidates),
            'departure_hour': [flight['departure_hour']] * len(valid_candidates),
            'departure_airport': [flight['departure_airport']] * len(valid_candidates),
            'route_type': [flight['route_type']] * len(valid_candidates),
            'route_category': [flight['route_category']] * len(valid_candidates),
            'used_variant_1': [flight['used_variant_1']] * len(valid_candidates),
            'used_variant_2': [flight['used_variant_2']] * len(valid_candidates),
            'used_variant_3': [flight['used_variant_3']] * len(valid_candidates),
            'available_ground_time_min': valid_candidates['available_ground_time_min'].values,
            'body_type': valid_candidates['body_type'].values
        })
        
        # Extract probabilities only for the valid candidates
        candidate_indices = encoder.transform(valid_candidates['aircraft_reg'])
        all_probabilities = model.predict_proba(X_pred)
        
        best_candidate_idx = np.argmax([all_probabilities[i][tail_idx] for i, tail_idx in enumerate(candidate_indices)])
        highest_score = all_probabilities[best_candidate_idx][candidate_indices[best_candidate_idx]]
        
        winning_tail = valid_candidates.iloc[best_candidate_idx]['aircraft_reg']
        
        # 5.4 SAVE PREDICTION
        predictions_to_insert.append({
            "flight_number": flight['flight_number'],
            "predicted_reg": winning_tail,
            "confidence_score": float(highest_score),
            "prediction_reason": f"Probability ({highest_score:.2f}) among {len(valid_candidates)} valid candidates."
        })
        
        # 5.3 UPDATE SIMULATION: Remove winning plane from today's pool
        df_fleet_status.loc[df_fleet_status['aircraft_reg'] == winning_tail, 'next_ready_utc'] = pd.Timestamp.max

    # 5.5 DB INSERTION
    if predictions_to_insert:
        supabase.table("predict_reg").insert(predictions_to_insert).execute()
        print(f"Successfully committed {len(predictions_to_insert)} predictions to database.")