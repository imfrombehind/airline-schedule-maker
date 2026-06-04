import streamlit as st
import pandas as pd
from utils import init_connection_1
from func import get_airport_info, format_day_of_week, is_domestic_route, is_cargo

supabase = init_connection_1()

def refresh_dashboard_cache():
    st.cache_data.clear()

@st.cache_data(show_spinner="Fetching Operators...")
def fetch_operators():
    op_res = supabase.table("operators").select("icao_designator, name, subsidiary_of, iata_designator, country").execute()
    return pd.DataFrame(op_res.data) if op_res.data else pd.DataFrame()

@st.cache_data(show_spinner="Fetching Schedules...")
def fetch_schedules(operator_icaos_tuple=None):
    query = supabase.table("flight_list").select(
        "flight_number, operator_id, painted_as, day_of_week, " \
        "departure_airport, arrival_airport, route_type, scheduled_departure_time_utc, scheduled_arrival_time_utc, " \
        "blocktime_min, route_category, used_variant_1, used_variant_2, used_variant_3"
    )
    
    if operator_icaos_tuple:
         query = query.in_("operator_id", list(operator_icaos_tuple))

    # 1. PAGINATION: Safely fetch thousands of rows bypassing server limits
    all_data = []
    start = 0
    step = 1000 
    while True:
        sched_res = query.range(start, start + step - 1).execute()
        data = sched_res.data
        if not data: break
        all_data.extend(data)
        if len(data) < step: break
        start += step

    df_sched = pd.DataFrame(all_data) if all_data else pd.DataFrame()

    if not df_sched.empty:
        # 2. LOCAL CACHING: Prevent Errno 35 by halting row-by-row DB calls
        # Gather unique airports and routes
        unique_airports = set(df_sched['departure_airport'].dropna()).union(set(df_sched['arrival_airport'].dropna()))
        
        # Ask the database ONLY ONCE per unique airport (~150 calls instead of 10,000+)
        apt_dict = {}
        for apt in unique_airports:
            apt_dict[apt] = {
                'iata_code': get_airport_info(apt, 'iata_code'),
                'country': get_airport_info(apt, 'country'),
                'city': get_airport_info(apt, 'city')
            }

        # Map values instantly from local memory
        df_sched['dep_iata'] = df_sched['departure_airport'].apply(lambda x: apt_dict.get(x, {}).get('iata_code', x))
        df_sched['arr_iata'] = df_sched['arrival_airport'].apply(lambda x: apt_dict.get(x, {}).get('iata_code', x))
        df_sched['dep_country'] = df_sched['departure_airport'].apply(lambda x: apt_dict.get(x, {}).get('country', 'Unknown'))
        df_sched['arr_country'] = df_sched['arrival_airport'].apply(lambda x: apt_dict.get(x, {}).get('country', 'Unknown'))
        df_sched['dep_city'] = df_sched['departure_airport'].apply(lambda x: apt_dict.get(x, {}).get('city', 'Unknown'))
        df_sched['arr_city'] = df_sched['arrival_airport'].apply(lambda x: apt_dict.get(x, {}).get('city', 'Unknown'))
        
        df_sched['Route'] = df_sched['dep_iata'] + " ➔ " + df_sched['arr_iata']
        df_sched['R_Airport'] = df_sched['dep_iata'] + " - " + df_sched['arr_iata']
        df_sched['T_Route'] = df_sched['dep_city'] + " (" + df_sched['dep_country'] + ") - " + df_sched['arr_city'] + " (" + df_sched['arr_country'] + ")"

        # 3. CACHE THE MARKET LOGIC
        # Ask the database ONLY ONCE per unique route combination 
        route_market_cache = {}
        def get_market_cached(dep, arr, op_id):
            route_key = f"{dep}-{arr}-{op_id}"
            if route_key not in route_market_cache:
                route_market_cache[route_key] = is_domestic_route(dep, arr, op_id)
            return route_market_cache[route_key]

        df_sched['Market'] = df_sched.apply(lambda row: get_market_cached(row.get('departure_airport'), row.get('arrival_airport'), row.get('operator_id')), axis=1)
        
        # 4. CACHE THE CARGO LOGIC
        variant_cache = {}
        def get_is_cargo_cached(variant):
            if not variant: return False
            if variant not in variant_cache:
                variant_cache[variant] = is_cargo(variant)
            return variant_cache[variant]

        df_sched['weekly_freq'] = df_sched['day_of_week'].apply(lambda x: len(str(x).split(',')) if pd.notna(x) and x != "" else 0)
        df_sched['is_cargo'] = df_sched.apply(
            lambda row: get_is_cargo_cached(row.get('used_variant_1')) or 
                        get_is_cargo_cached(row.get('used_variant_2')) or 
                        get_is_cargo_cached(row.get('used_variant_3')), 
            axis=1
        )
    
    return df_sched

@st.cache_data(show_spinner="Fetching History...")
def fetch_history(operator_icaos_tuple=None):
    query = supabase.table("historical_flight_input").select(
        "flight_number, operator_icao, callsign, painted_as, type, reg, " \
        "origin_icao, destination_icao, destination_icao_actual, " \
        "datetime_takeoff, datetime_landed, flight_ended, source"
    )
    
    if operator_icaos_tuple:
        query = query.in_("operator_icao", list(operator_icaos_tuple))

    hist_res = query.limit(50000).execute()
    df_hist = pd.DataFrame(hist_res.data) if hist_res.data else pd.DataFrame()

    if not df_hist.empty:
        df_hist['datetime_takeoff'] = pd.to_datetime(df_hist['datetime_takeoff'], format='mixed', utc=True)
        df_hist['datetime_landed'] = pd.to_datetime(df_hist['datetime_landed'], format='mixed', utc=True)
        df_hist = df_hist.sort_values(by=['reg', 'datetime_landed'])

    return df_hist

@st.cache_data(show_spinner="Fetching Fleet...")
def fetch_fleet(operator_icaos_tuple=None):
    query = supabase.table("fleet").select("aircraft_reg, operator_icao, variant, type, min_turnaround_min")
    
    if operator_icaos_tuple:
        query = query.in_("operator_icao", list(operator_icaos_tuple))
        
    fleet_res = query.execute()
    df_fleet = pd.DataFrame(fleet_res.data) if fleet_res.data else pd.DataFrame()

    return df_fleet

@st.cache_data(show_spinner="Fetching Airport Visits...")
def fetch_airport_visits(operator_icaos_tuple=None):
    query = supabase.table("airport_operators").select("airport_icao, flight_count, operator_icao")
    if operator_icaos_tuple:
        query = query.in_("operator_icao", list(operator_icaos_tuple))
    
    airport_op_res = query.execute()
    df_airport_op = pd.DataFrame(airport_op_res.data) if airport_op_res.data else pd.DataFrame()

    if df_airport_op.empty:
        return df_airport_op

    df_airports = fetch_airport_list()
    
    # Merge them together
    if not df_airports.empty:
        df_airport_op = pd.merge(
            df_airport_op, 
            df_airports[['icao_code', 'iata_code', 'country', 'latitude', 'longitude']], 
            left_on='airport_icao', 
            right_on='icao_code', 
            how='left'
        )
        
        df_airport_op = df_airport_op.rename(columns={'iata_code': 'iata'})
        df_airport_op = df_airport_op.drop(columns=['icao_code'])
        
    else:
        df_airport_op['iata'] = None
        df_airport_op['country'] = None
        df_airport_op['latitude'] = None
        df_airport_op['longitude'] = None

    return df_airport_op

@st.cache_data(show_spinner="Fetching Airport List...")
def fetch_airport_list():
    airport_list_res = supabase.table("airport_list").select("icao_code, iana_tz, latitude, longitude, city, iata_code, name, country").execute()
    return pd.DataFrame(airport_list_res.data) if airport_list_res.data else pd.DataFrame()

@st.cache_data(show_spinner="Fetching Aircraft Types...")
def fetch_aircraft_types():
    type_res = supabase.table("aircraft_type").select("variant", "type_code", "manufacturer", "body_category", "body_type", "range_category").execute()
    return pd.DataFrame(type_res.data) if type_res.data else pd.DataFrame()

@st.cache_data(show_spinner="Processing analytical flight data...")
def process_merged_flight_data(df_sched, df_hist, join_type="left"):
    """Merges schedule and history, calculating delays, timeframes, and performance statuses."""
    if df_sched.empty or df_hist.empty:
        return pd.DataFrame()

    # 1. Merge
    df_merged = pd.merge(
        df_sched, df_hist, 
        left_on=["operator_id", "flight_number", "departure_airport", "arrival_airport"], 
        right_on=["operator_icao", "flight_number", "origin_icao", "destination_icao"], 
        how=join_type
    )

    cols_to_drop = ["departure_airport", "arrival_airport"]
    df_merged = df_merged.drop(columns=[c for c in cols_to_drop if c in df_merged.columns])

    # 2. Convert ACTUAL times to full datetimes
    df_merged['actual_dep'] = pd.to_datetime(df_merged['datetime_takeoff'], format='mixed', utc=True)
    df_merged['actual_arr'] = pd.to_datetime(df_merged['datetime_landed'], format='mixed', utc=True)

    # 3. Generate Timeframes
    df_merged['Year'] = df_merged['actual_dep'].dt.strftime('%Y')
    df_merged['Month'] = df_merged['actual_dep'].dt.month_name()
    df_merged['Week'] = df_merged['actual_dep'].dt.isocalendar().week
    if 'day_of_week' in df_merged.columns:
        df_merged['Day of Week'] = df_merged['day_of_week'].apply(format_day_of_week)
        df_merged['weekly_freq'] = df_merged['day_of_week'].apply(lambda x: len(str(x).split(',')) if pd.notna(x) and x != "" else 0)

    # 4. Handle Time-Only Delay Calculations
    sched_dep_dt = pd.to_datetime(df_merged['scheduled_departure_time_utc'].astype(str), format='mixed', errors='coerce')
    sched_arr_dt = pd.to_datetime(df_merged['scheduled_arrival_time_utc'].astype(str), format='mixed', errors='coerce')

    sched_dep_td = pd.to_timedelta(sched_dep_dt.dt.strftime('%H:%M:%S'), errors='coerce')
    sched_arr_td = pd.to_timedelta(sched_arr_dt.dt.strftime('%H:%M:%S'), errors='coerce')
    actual_dep_td = pd.to_timedelta(df_merged['actual_dep'].dt.strftime('%H:%M:%S'), errors='coerce')
    actual_arr_td = pd.to_timedelta(df_merged['actual_arr'].dt.strftime('%H:%M:%S'), errors='coerce')

    raw_dep_delay = (actual_dep_td - sched_dep_td).dt.total_seconds() / 60
    raw_arr_delay = (actual_arr_td - sched_arr_td).dt.total_seconds() / 60

    # Correct for midnight crossovers
    df_merged['dep_delays_mins'] = raw_dep_delay.apply(lambda x: x + 1440 if pd.notna(x) and x < -720 else (x - 1440 if pd.notna(x) and x > 720 else x))
    df_merged['arr_delay_mins'] = raw_arr_delay.apply(lambda x: x + 1440 if pd.notna(x) and x < -720 else (x - 1440 if pd.notna(x) and x > 720 else x))

    # 5. Status Tracking & Performance Categorization
    def determine_performance(row):
        # 1. Check for Cancellation (No actual arrival time recorded)
        if pd.isna(row.get('actual_arr')) or pd.isna(row.get('arr_delay_mins')):
            return "Cancelled"
        
        # 2. Check for Diversion (Scheduled Destination != Actual Destination)
        dest = str(row.get('destination_icao', '')).strip()
        actual_dest = str(row.get('destination_icao_actual', '')).strip()
        
        if dest and actual_dest and (dest != actual_dest):
            return "Diverted"
            
        # 3. Standard Delay Logic (If it actually landed where it was supposed to)
        delay = row.get('arr_delay_mins', 0)
        if delay >= 45: return "45m+ Late"
        elif delay >= 30: return "30m Late"
        elif delay >= 15: return "15m Late"
        elif delay >= 0: return "On Time"
        else: return "Early"
    
    # Apply the combined function to create the unified column the dashboard expects
    df_merged['Performance_Status'] = df_merged.apply(determine_performance, axis=1)
    df_merged['is_on_time'] = df_merged['arr_delay_mins'] <= 15

    return df_merged

@st.cache_data(show_spinner="Calculating turnaround efficiency...")
def process_turnarounds(df_hist):
    """Calculates ground turnaround times for historical flights."""
    if df_hist.empty or 'reg' not in df_hist.columns:
        return df_hist
        
    df_t = df_hist.copy()
    df_t = df_t.sort_values(by=['reg', 'datetime_landed'])
    df_t['next_takeoff'] = df_t.groupby('reg')['datetime_takeoff'].shift(-1)
    df_t['turnaround_mins'] = (df_t['next_takeoff'] - df_t['datetime_landed']).dt.total_seconds() / 60
    
    return df_t

def get_active_operator_network():
    """Fetches the current profile from session state and returns the main profile name and its network of ICAOs."""
    if "selected_profile" not in st.session_state:
        st.switch_page("pages/operators.py")

    current_profile = st.session_state.selected_profile
    operator_icaos = []
    
    try:
        main_op_res = supabase.table("operators").select("icao_designator").eq("name", current_profile).execute()
        if main_op_res.data:
            main_icao = main_op_res.data[0]["icao_designator"]
            operator_icaos.append(main_icao)
            
            sub_res = supabase.table("operators").select("icao_designator").eq("subsidiary_of", main_icao).execute()
            for row in sub_res.data:
                operator_icaos.append(row["icao_designator"])
    except Exception as e:
        st.error(f"Error fetching operators: {e}")
        
    return current_profile, operator_icaos