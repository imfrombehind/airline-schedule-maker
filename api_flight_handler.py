import pandas as pd
import streamlit as st
import pycountry
import airportsdata
import os
import requests
import time
from datetime import datetime, timezone, timedelta
from fr24sdk.client import Client
from utils import inject_global_css, init_connection_1

inject_global_css()
supabase = init_connection_1()
airports_db = airportsdata.load('ICAO')

def safe_parse_datetime(date_str):
    """Converts naive FR24 timestamps to strict UTC for Supabase."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.isoformat()
    except ValueError:
        return None

def bulk_sync_airports(icao_list, status_ui=None):
    """Takes a list of ICAO codes, checks which are missing, and bulk inserts them efficiently."""
    if not icao_list: return
        
    unique_icaos = list(set([str(icao).strip().upper() for icao in icao_list if icao and pd.notna(icao)]))
    if not unique_icaos: return

    known_ap_res = supabase.table("airport_list").select("icao_code").in_("icao_code", unique_icaos).execute()
    known_airports = [row["icao_code"] for row in known_ap_res.data]
    missing_airports = [ap for ap in unique_icaos if ap not in known_airports]
    
    if missing_airports:
        if status_ui:
            status_ui.write(f"Analyzing {len(missing_airports)} missing airports against local database...")

        new_ap_payloads = []
        for clean_icao in missing_airports:
            # 1. Start with default/fallback data
            payload = {
                "icao_code": clean_icao,
                "iata_code": "UNK",
                "name": "Unknown / Not in DB",
                "country": "Unknown",
                "city": "Unknown",
                "iana_tz": "UTC",
                "latitude": 0.0,
                "longitude": 0.0
            }

            # 2. If we have real data, overwrite the default
            if clean_icao in airports_db:
                ap_info = airports_db[clean_icao]

                # Get proper country name
                raw_country_code = ap_info.get("country")
                full_country_name = raw_country_code or "Unknown"
                if raw_country_code:
                    country_obj = pycountry.countries.get(alpha_2=raw_country_code)
                    if country_obj:
                        full_country_name = country_obj.name

                payload.update({
                    "iata_code": ap_info.get("iata") or "UNK",
                    "iana_tz": ap_info.get("tz") or "UTC",
                    "latitude": ap_info.get("lat") or 0.0,
                    "longitude": ap_info.get("lon") or 0.0,
                    "name": ap_info.get("name") or "Unknown",
                    "city": ap_info.get("city") or "Unknown",
                    "country": full_country_name
                })
            new_ap_payloads.append(payload)
                
        if new_ap_payloads:
            try:
                supabase.table("airport_list").upsert(new_ap_payloads, on_conflict="icao_code").execute()
                print(f"Auto-synced {len(new_ap_payloads)} airports.")
                if status_ui:
                    status_ui.write(f"Auto-synced {len(new_ap_payloads)} new airports to database.")
            except Exception as e:
                print(f"Error bulk syncing airports: {e}")
                if status_ui:
                    status_ui.error(f"Error bulk syncing airports: {e}")

def _format_sdk_date(val):
    if not val: return None
    return str(val)

def fetch_fr24_data(operator_string="TEST", start_date_str=None, end_date_str=None, status_ui=None):
    """
    Fetches real historical flight data using the official Flightradar24 SDK.
    """
    # 1. Check Streamlit secrets first, then OS environment variables
    api_key = st.secrets.get("FR24_API_TOKEN") or os.environ.get("FR24_API_TOKEN")

    if not api_key:
        print("Warning: FR24_API_TOKEN not found in environment or secrets.")
        if status_ui: 
            status_ui.error("Missing FR24_API_TOKEN.")
        return {"data": []}
    
    # Format the operator string (max 15 allowed by the API)
    operators = [op.strip() for op in operator_string.split(",") if op.strip()][:15]
    operating_as_param = ",".join(operators)

    # 1. Setup the exact API endpoint we saw in your error logs
    url = "https://fr24api.flightradar24.com/api/flight-summary/light"

    # 2. Move parameters into a dictionary for the request body
    params = {
        "operating_as": operating_as_param,
        "flight_datetime_from": start_date_str,
        "flight_datetime_to": end_date_str,
        "limit": 20000 
    }

    # 3. Use the Bearer token authorization exactly as the SDK does internally
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Accept-Version": "v1"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status() 
        json_data = response.json()
        
        raw_flights = json_data.get("data", json_data) if isinstance(json_data, dict) else json_data

        mapped_data = []
        for flight in raw_flights:
            mapped_data.append({
                "fr24_id": str(flight.get("fr24_id", "")),
                "flight": flight.get("flight", ""),
                "callsign": flight.get("callsign", ""),
                "operated_as": flight.get("operating_as", operator_string.split(",")[0]),
                "painted_as": flight.get("painted_as", ""),         
                "type": flight.get("type", ""),
                "reg": flight.get("reg", ""),
                "origin_icao": flight.get("orig_icao", ""), 
                "datetime_takeoff": _format_sdk_date(flight.get("datetime_takeoff")),
                "destination_icao": flight.get("dest_icao", ""), 
                "destination_icao_actual": flight.get("dest_icao_actual", ""), 
                "datetime_landed": _format_sdk_date(flight.get("datetime_landed")),
                "hex": flight.get("hex", ""),
                "first_seen": _format_sdk_date(flight.get("first_seen")),        
                "last_seen": _format_sdk_date(flight.get("last_seen")),
                "flight_ended": flight.get("flight_ended", True)
            })
                
        return {"data": mapped_data}

    except requests.exceptions.RequestException as e:
        print(f"Direct API call failed: {e}")
        if status_ui: 
            status_ui.error(f"Network error on current block: {e}")
        return {"data": []}

def process_and_store_flights(operator_icao, api_response, status_ui=None):
    raw_flights = api_response.get("data", [])
    success_count = 0

    if not raw_flights: 
        print("No flights returned by API.")
        return 0
    
    # 1. Bulk sync all airports first
    all_icaos_to_sync = set()
    for flight in raw_flights:
        if flight.get("origin_icao"): all_icaos_to_sync.add(flight.get("origin_icao"))
        if flight.get("destination_icao"): all_icaos_to_sync.add(flight.get("destination_icao"))
        if flight.get("destination_icao_actual"): all_icaos_to_sync.add(flight.get("destination_icao_actual"))
    
    # 2. Sync them BEFORE processing any flights
    bulk_sync_airports(list(all_icaos_to_sync), status_ui=status_ui)

    # Create a transient log space beneath active status steps for rapid upserts
    log_space = st.empty() if status_ui else None
    
    for flight in raw_flights:
        orig = flight.get("origin_icao", "")
        dest = flight.get("destination_icao", "")
        dest_actual = flight.get("destination_icao_actual", "")

        # 1. SKIP THE FLIGHT if the API gave us no airport data
        if not orig or not dest:
            print(f"Skipping flight {flight.get('flight')} - Missing ICAO codes.")
            continue

        fr24_id = str(flight.get("fr24_id"))
        flight_num = flight.get("flight", "UNKNOWN")
        
        # Double Dip Protection
        check_res = supabase.table("historical_flight_input").select("source").eq("fr24_id", fr24_id).execute()
        if len(check_res.data) > 0:
            continue
                
        payload = {
            "fr24_id": fr24_id,
            "operator_icao": flight.get("operated_as", operator_icao),
            "painted_as": flight.get("painted_as", ""),
            "flight_number": flight_num,
            "callsign": flight.get("callsign", ""),
            "type": flight.get("type", ""),
            "reg": flight.get("reg", ""),
            "origin_icao": orig,
            "destination_icao": dest,
            "destination_icao_actual": dest_actual,
            "datetime_takeoff": safe_parse_datetime(flight.get("datetime_takeoff")),
            "datetime_landed": safe_parse_datetime(flight.get("datetime_landed")),
            "hex": flight.get("hex", ""),
            "first_seen": safe_parse_datetime(flight.get("first_seen")),
            "last_seen": safe_parse_datetime(flight.get("last_seen")),
            "flight_ended": flight.get("flight_ended", ""),
            "source": "api-upload"
        }

        if log_space:
            log_space.caption(f"Database staging: `{flight_num}` ({orig} ➔ {dest})")

        print(f"Attempting upsert for flight {flight_num} | Origin: '{orig}' Dest: '{dest}'")
        
        try:
            supabase.table("historical_flight_input").upsert(payload).execute()
            success_count += 1
        except Exception as e:
            print(f"Error saving {flight_num}: {e}")
            if status_ui: 
                status_ui.warning(f"Flagged flight record {flight_num}: {e}")

    if log_space: 
        log_space.empty()

    return success_count

def run_historical_ingestion(operator_list, days_back=7):
    api_operator_string = ",".join(operator_list)   
    
    now_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_str = now_utc.strftime('%Y-%m-%dT%H:%M:%S')
    
    # 1. Set the default start date to be 'days_back' days before today at midnight UTC
    default_start = now_utc - timedelta(days=days_back)
    current_start = default_start
    total_flights = 0
    
    print(f"Starting ingestion from {current_start.strftime('%Y-%m-%d')} to {now_utc.strftime('%Y-%m-%d')}")
    with st.status(f"Executing Historical Ingestion Pipeline [{', '.join(operator_list)}]", expanded=True) as status:
        status.write("Verifying database history for EACH operator...")

        # --- RESUME LOGIC ---
        # Logic to check newly added subsidiaries and ensure we start from the correct point in time for each operator, rather than just the most recent flight across all operators.
        try:
            oldest_latest_time = None
            has_new_operator = False

            # Check each operator individually to find the furthest one behind
            for op in operator_list:
                recent_res = supabase.table("historical_flight_input") \
                    .select("first_seen") \
                    .eq("operator_icao", op) \
                    .order("first_seen", desc=True) \
                    .limit(1) \
                    .execute()
                
                if recent_res.data and len(recent_res.data) > 0 and recent_res.data[0].get("first_seen"):
                    latest_saved_str = recent_res.data[0]["first_seen"]
                    latest_saved_dt = datetime.fromisoformat(latest_saved_str.replace('Z', '+00:00'))
                    
                    # Track the operator that is furthest behind
                    if oldest_latest_time is None or latest_saved_dt < oldest_latest_time:
                        oldest_latest_time = latest_saved_dt
                else:
                    # We found an operator with absolutely NO data in the database
                    has_new_operator = True
                    break
            
            # Set the starting timestamp based on the weakest link
            if has_new_operator:
                current_start = default_start
                status.write(f"Detected a newly added subsidiary with no data. Starting fresh {days_back}-day ingestion to catch them up.")
            elif oldest_latest_time and oldest_latest_time > default_start:
                current_start = oldest_latest_time + timedelta(seconds=1)
                status.write(f"Resuming from the oldest known flight among operators at `{current_start.strftime('%Y-%m-%d %H:%M:%S')}` UTC.")
            else:
                current_start = default_start
                status.write(f"Last saved flight is older than {days_back} days. Starting fresh ingestion.")

        except Exception as e:
            status.warning(f"Could not verify previous records. Defaulting to full {days_back} days. Error: {e}")

        # --- INGESTION LOOP ---
        while current_start < now_utc:
            start_date_str = current_start.strftime('%Y-%m-%dT%H:%M:%S')
            print(f"Fetching 20 flights starting from {start_date_str}...")
            status.write(f"Querying time-block initialization from: `{start_date_str}`...")
            
            try:
                api_response = fetch_fr24_data(api_operator_string, start_date_str, end_date_str, status_ui=status) 
                raw_flights = api_response.get("data", [])
                
                if not raw_flights:
                    print("No more flights found.")
                    status.write("Pipeline scanning complete: No further records detected.")
                    break
                    
                count = process_and_store_flights(operator_list[0], api_response)
                total_flights += count
                status.write(f"Batch update finalized. Added `{count}` tracking elements to ledger.")
                
                # If we got LESS than 20 flights, we have reached the very end of the 7 days
                if len(raw_flights) < 20:
                    print(f"Reached the end. Total flights saved: {total_flights}")
                    break
                    
                # Grab the 'first_seen' time of the very last (20th) flight in the list
                last_flight_time_str = raw_flights[-1].get("first_seen")
                last_flight_dt = datetime.fromisoformat(last_flight_time_str.replace('Z', '+00:00'))
                current_start = last_flight_dt + timedelta(seconds=1)
                
            except Exception as e:
                print(f"Failed on chunk starting {start_date_str}: {e}")
                status.error(f"Thread failure on block sequence near {start_date_str}: {e}")
                break 
            
            status.write("API Rate Limit Cooldown: Pausing for 6.5 seconds...")
            time.sleep(6.5) 

        # Complete the state rendering nicely
        status.update(label=f"Ingestion Success: {total_flights} total operational segments processed.", state="complete", expanded=False)

    return True, total_flights