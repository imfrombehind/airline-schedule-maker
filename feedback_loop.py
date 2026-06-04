import pandas as pd
import numpy as np
from utils import init_connection_1
from api_flight_handler import safe_parse_datetime, bulk_sync_airports
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import lightgbm as lgb
import joblib

supabase = init_connection_1()

# PHASE 6.1 - 6.6: EVALUATION & CORRECTION LOGS
def evaluate_predictions(temporary_api_data): 
# Compares API truth data against predict_reg and writes to correction_logs temporary_api_data should be a dataframe containing actual landed flights
    print("--- Phase 6: Auditing Predictions ---")

    # 1. BULK SYNC AIRPORTS FIRST (Protects against diversion crashes)
    # Extract all unique airports from the temporary API data
    all_icaos = pd.concat([
        temporary_api_data['origin_icao'],
        temporary_api_data['destination_icao'],
        temporary_api_data['destination_icao_actual']
    ]).unique().tolist()
    
    bulk_sync_airports(all_icaos)
    
    # Pull the predictions we made yesterday
    flight_numbers = temporary_api_data['flight_number'].tolist()
    pred_res = supabase.table("predict_reg").select("id, flight_number, predicted_reg").in_("flight_number", flight_numbers).execute()
    df_preds = pd.DataFrame(pred_res.data)
    
    if df_preds.empty:
        return

    # Merge Truth with Prediction
    df_eval = pd.merge(temporary_api_data, df_preds, on="flight_number", how="inner")
    
    correction_logs_payload = []
    
    for _, row in df_eval.iterrows():
        # Only evaluate landed flights (Phase 6.4)
        if row['status'] != "landed":
            continue
            
        is_match = (row['reg'] == row['predicted_reg'])
        source_label = "good_prediction" if is_match else "correction"
        
        # Construct Correction Log (Phase 6.5)
        correction_logs_payload.append({
            "correction_id": f"CORR-{row['fr24_id']}",
            "prediction_id": row['id'],
            "actual_reg": row['reg'],
            "actual_departure_time_utc": safe_parse_datetime(row['datetime_takeoff']),
            "actual_arrival_time_utc": safe_parse_datetime(row['datetime_landed']),
            "is_confirmed": is_match
        })
        
        # Append back to historical input (Phase 6.6)
        supabase.table("historical_flight_input").insert({
            "fr24_id": row['fr24_id'],
            "operator_icao": row['operated_as'],
            "flight_number": row['flight'],
            "callsign": row['callsign'],
            "type": row['type'],
            "reg": row['reg'],
            "origin_icao": row['origin_icao'],
            "destination_icao": row['destination_icao'],
            "destination_icao_actual": row['destination_icao_actual'],
            "datetime_takeoff": safe_parse_datetime(row['datetime_takeoff']),
            "datetime_landed": safe_parse_datetime(row['datetime_landed']),
            "first_seen": safe_parse_datetime(row['first_seen']),
            "last_seen": safe_parse_datetime(row['last_seen']),
            "source": source_label
        }).execute()

    # Commit Logs to Database
    if correction_logs_payload:
        supabase.table("correction_logs").insert(correction_logs_payload).execute()
        accuracy = sum([1 for log in correction_logs_payload if log['is_confirmed']]) / len(correction_logs_payload)
        print(f"Audit Complete. Model Accuracy for batch: {accuracy * 100:.2f}%")

# PHASE 6.7: RETRAIN THE ML
def retrain_models_from_history():
# Pulls historical inputs, translates text to math, and trains LightGBM.
    print("--- Phase 6.7: Retraining ML Models ---")
    
    # 1. Get the training data
    hist_res = supabase.table("historical_flight_input").select(
        "operator_icao, reg, origin_icao, datetime_takeoff"
    ).execute()
    
    df = pd.DataFrame(hist_res.data) 
    
    # (Mocking the joined features for the sake of the code structure)
    df['day_of_week'] = 1
    df['departure_hour'] = pd.to_datetime(df['datetime_takeoff']).dt.hour
    df['route_type'] = 'Domestic'
    df['route_category'] = 'Trunk'
    df['used_variant_1'] = 'B738'
    df['available_ground_time_min'] = 90.0

    # Define the columns that the ML will look at
    features = [
        'day_of_week', 'departure_hour', 'origin_icao', 
        'route_type', 'route_category', 'used_variant_1', 'used_variant_2', 'used_variant_3',
        'available_ground_time_min', 'body_type'
    ]
    categorical_features = [
        'origin_icao', 'route_type', 'route_category', 
        'used_variant_1', 'used_variant_2', 'used_variant_3',
        'body_type'
    ]
    numerical_features = ['day_of_week', 'departure_hour', 'available_ground_time_min']

    unique_operators = df['operator_icao'].unique()

    # 2. The Multi-Operator Loop
    for operator in unique_operators:
        operator_df = df[df['operator_icao'] == operator].copy()
        
        if len(operator_df) < 50: 
            continue # Skip if the airline doesn't have enough history
            
        X = operator_df[features]
        y = operator_df['reg'] # The actual tail numbers
        
        # ---> LABEL ENCODER IN ACTION <---
        # Turns ["C-FNSA", "C-GJVA"] into [0, 1]
        encoder = LabelEncoder()
        y_encoded = encoder.fit_transform(y)
        
        # ---> COLUMN TRANSFORMER & ONE-HOT ENCODER IN ACTION <---
        # Translates 'YYZ' into a binary math matrix
        preprocessor = ColumnTransformer(
            transformers=[
                ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_features),
                ('num', 'passthrough', numerical_features)
            ]
        )
        
        # ---> LIGHTGBM & PIPELINE IN ACTION <---
        # Glues the preprocessor to the LightGBM brain
        pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('classifier', lgb.LGBMClassifier(
                objective='multiclass',
                num_class=len(np.unique(y_encoded)),
                n_estimators=100,
                verbose=-1
            ))
        ])
        
        # Train the model!
        pipeline.fit(X, y_encoded)
        
        # Save them so Phase 5 can use them tomorrow
        joblib.dump(pipeline, f"model_registry/model_{operator}.pkl")
        joblib.dump(encoder, f"model_registry/encoder_{operator}.pkl")
        print(f"Successfully retrained model for {operator}.")

    print("Retraining completed.")