import streamlit as st
import pandas as pd
import numpy as np
import pytz
import airportsdata
from datetime import datetime
from utils import init_connection_1

supabase = init_connection_1()
airports_db = airportsdata.load('ICAO')

def parse_time(time_input):
    if pd.isna(time_input) or not time_input:
        return None
    clean_str = str(time_input).replace(":", "").strip()
    if len(clean_str) == 3: clean_str = "0" + clean_str
    if len(clean_str) == 4: 
        return f"{clean_str[:2]}:{clean_str[2:]}:00"
    return None

def convert_utc_to_local_1(utc_time_str, tz_string):
    if not utc_time_str or not tz_string:
        return "--"
    try:
        # Parse the UTC time (assuming ISO 8601 format from Supabase)
        utc_dt = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
        local_tz = pytz.timezone(tz_string)
        local_dt = utc_dt.astimezone(local_tz)
        return local_dt.strftime("%H:%M") # Just time, or change to "%Y-%m-%d %H:%M"
    except Exception as e:
        return f"Err: {str(utc_time_str)[:5]}"

def convert_utc_to_local_2(utc_time_str, tz_string):
    if not utc_time_str or not tz_string:
        return "--"
    try:
        parsed_time_time = datetime.strptime(utc_time_str, "%H:%M:%S").time()
        modern_date = datetime.now().date()
        utc_dt = datetime.combine(modern_date, parsed_time_time).replace(tzinfo=pytz.utc)

        local_tz = pytz.timezone(tz_string)
        local_dt = utc_dt.astimezone(local_tz)
        return local_dt.strftime("%H:%M") 
    except Exception as e:
        return f"Err: {str(utc_time_str)[:5]}"

def convert_local_to_utc(local_time_str, base_datetime, icao_code, airport_tz_map):
    parsed_time_str = parse_time(local_time_str)
    if not parsed_time_str: 
        return "00:00:00"
        
    tz_str = airport_tz_map.get(icao_code, "UTC")
    try:
        local_tz = pytz.timezone(tz_str)
        base_date = pd.to_datetime(base_datetime).date()
        time_obj = datetime.strptime(parsed_time_str, "%H:%M:%S").time()
        # Combine date and time into a naive datetime
        naive_dt = datetime.combine(base_date, time_obj)
        # Localize and convert to UTC
        local_dt = local_tz.localize(naive_dt, is_dst=None)
        utc_dt = local_dt.astimezone(pytz.utc)
        
        return utc_dt.strftime("%H:%M:%S")
    except Exception as e:
        return parsed_time_str
    
def calculate_circular_mean_time(time_series):
    """
    Calculates the circular average of a pandas Series of datetime objects.
    Safely handles times that cross the midnight boundary.
    Returns a formatted string "HH:MM".
    """
    if time_series.empty:
        return None
        
    # Extract hours and minutes
    hours = time_series.dt.hour
    minutes = time_series.dt.minute
    
    # Convert to total minutes past midnight
    total_minutes = hours * 60 + minutes
    
    # Convert minutes to angles in radians (1440 minutes = 2*pi)
    angles = (total_minutes / 1440.0) * 2 * np.pi
    
    # Calculate the mean of the sine and cosine vectors
    mean_sin = np.sin(angles).mean()
    mean_cos = np.cos(angles).mean()
    
    # Calculate the mean angle using arctangent
    mean_angle = np.arctan2(mean_sin, mean_cos)
    
    # If the angle is negative, wrap it around the circle
    if mean_angle < 0:
        mean_angle += 2 * np.pi
        
    # Convert the final angle back to minutes
    avg_minutes = int(round(mean_angle / (2 * np.pi) * 1440))
    
    # Handle the exact midnight edge case
    if avg_minutes == 1440:
        avg_minutes = 0
        
    return f"{avg_minutes // 60:02d}:{avg_minutes % 60:02d}"

@st.cache_data(ttl=86400)
def get_all_airports():
    res = supabase.table("airport_list").select("icao_code, iata_code, city, iana_tz, name, country").execute()
    df = pd.DataFrame(res.data)
    df = df.drop_duplicates(subset=['icao_code'], keep='first')
    
    #if res.data: return {row["icao_code"]: row for row in res.data}
    # return pd.DataFrame(res.data).set_index('icao_code').to_dict('index')
    return df.set_index('icao_code').to_dict('index')

def get_airport_info(icao_code, field="iata_code"):
    if not icao_code:
        return "--"
        
    airport_sub_db = get_all_airports() 
    airport_data = airport_sub_db.get(icao_code, {})
    fallback_value = icao_code if field == "iata_code" else "Unknown"
    
    return airport_data.get(field, fallback_value)

def get_operator_info(operator_icao, field="name"):
    if not operator_icao:
        return "--"
    
    res = supabase.table("operators").select("*").eq("icao_designator", operator_icao).execute()
    if res.data and len(res.data) > 0:
        operator_data = res.data[0]
        return operator_data.get(field, operator_icao)

def format_day_of_week(day_value):
    day_mapping = {
        1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 
        5: "Thu", 6: "Fri", 7: "Sat"
    }
    
    def get_day(val):
        try:
            return day_mapping.get(int(str(val).strip()), "--")
        except (ValueError, TypeError):
            return "--"
        
    if isinstance(day_value, str) and "," in day_value:
        items = day_value.split(",")
        return ", ".join(get_day(item) for item in items)
        
    elif isinstance(day_value, (list, set, tuple)):
        return ", ".join(get_day(item) for item in sorted(day_value))
        
    else:
        return get_day(day_value)
    
def is_domestic_route(origin_icao, dest_icao, operator):
    origin_country = get_airport_info(origin_icao, "country")
    dest_country = get_airport_info(dest_icao, "country")
    operator_country = get_operator_info(operator, "country")

    if origin_country == operator_country and dest_country == operator_country:
        return "DOMESTIC"
    else:
        return "INTERNATIONAL"
    
def get_aircraft_type_info(variant, field="manufacturer"):
    if not variant:
        return "--"
    
    res = supabase.table("aircraft_type").select("*").eq("variant", variant).execute()
    if res.data and len(res.data) > 0:
        aircraft_data = res.data[0]
        return aircraft_data.get(field, variant)

def is_cargo(variant):
    if not variant:
        return False
    cargo_aircraft = get_aircraft_type_info(variant, "body_category")
    if cargo_aircraft and cargo_aircraft.upper() == "CARGO":
        return "Cargo"
    else:        
        return "Passenger"