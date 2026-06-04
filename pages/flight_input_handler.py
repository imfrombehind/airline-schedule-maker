import time
import streamlit as st
import pandas as pd
from utils import setup_page
from func import convert_local_to_utc, get_airport_info, is_domestic_route, calculate_circular_mean_time
from data_handler import get_active_operator_network

supabase = setup_page("Flights Input")
current_profile, operator_icaos = get_active_operator_network()

# Fetch Available Aircraft Variants for the dropdowns
available_variants = []
variant_to_body_category = {}
type_res = supabase.table("aircraft_type").select("variant", "body_category").order("variant").execute()
if type_res.data:
    available_variants = [row["variant"] for row in type_res.data]
    variant_to_body_category = {row["variant"]: row["body_category"] for row in type_res.data}

# --- HEADER LAYOUT ---
col_title, col_dash = st.columns([7, 1.5], vertical_alignment="bottom")
with col_title:
    st.title(f"Input flight information for {current_profile}")
with col_dash:
    if st.button("Dashboard", width='stretch'):
        st.switch_page("pages/dashboard_sub.py")

st.markdown("""
        1. First, map any newly discovered aircraft registrations to their correct variants. This ensures accurate maintenance and turnaround calculations.
        2. Next, define the scheduled routes by providing local departure and arrival times. The system will automatically convert these to UTC, calculate block times, and categorize the routes for you.
        3. Once saved, your dashboard will be fully updated with the new fleet and route information, ready for you to analyze and optimize!       
        """)
st.markdown("---")

# EXTRACT: RAW DATA
raw_data_res = supabase.table("historical_flight_input").select(
    "operator_icao, flight_number, callsign, type, reg, origin_icao, destination_icao_actual, datetime_takeoff, datetime_landed, painted_as" 
).in_("operator_icao", operator_icaos).execute()

df_raw = pd.DataFrame(raw_data_res.data)

if df_raw.empty:
    st.info(f"No raw data found for {current_profile}. Go to Operator Profiles and trigger the 7-day API download.")
    st.stop()

df_raw = df_raw.sort_values(by='datetime_takeoff', ascending=True).reset_index(drop=True)

# PHASE 1: THE FLEET BUILDER GRID
st.subheader("Fleet Builder: Map Aircraft to Variants")

# 1. Find planes in the raw data that are NOT in the fleet table yet
known_fleet_res = supabase.table("fleet").select("aircraft_reg").in_("operator_icao", operator_icaos).execute()
known_regs = [row["aircraft_reg"] for row in known_fleet_res.data]

df_missing_fleet = df_raw[~df_raw['reg'].isin(known_regs)][['reg', 'type', 'operator_icao']].drop_duplicates()

new_aircraft_discover = len(df_missing_fleet)

if not df_missing_fleet.empty:
    df_missing_fleet['variant'] = None
    
    st.write(f"**{new_aircraft_discover}** aircraft were found in the API pull but aren't in your fleet yet. Please assign their exact variant.")
    
    edited_fleet = st.data_editor(
        df_missing_fleet,
        width='stretch',
        hide_index=True,
        disabled=["reg", "type", "operator_icao"],
        column_config={
            "reg": st.column_config.TextColumn("Aircraft Registration"),
            "type": st.column_config.TextColumn("Aircraft Type"),
            "operator_icao": st.column_config.TextColumn("Operator ICAO"),
            "variant": st.column_config.SelectboxColumn("Assign Variant", options=available_variants, required=True)
        },
        key="fleet_editor"
    )

    if st.button("Save Fleet", type="primary"):
        valid_updates = edited_fleet.dropna(subset=['variant'])
        if valid_updates.empty:
            st.warning("No variants assigned yet.")
        else:
            # 1. Fetch the exact mapping of variant -> type_code from your database
            mapping_res = supabase.table("aircraft_type").select("variant, type_code").execute()
            variant_to_type = {row["variant"]: row["type_code"] for row in mapping_res.data}

            # 2. Scan the user's edits for any mismatches
            mismatches = []
            for _, row in edited_fleet.iterrows():
                assigned_var = row["variant"]
                raw_api_type = row["type"]
                expected_type = variant_to_type.get(assigned_var)
                
                # Check if the database type_code matches the FlightRadar24 type
                if expected_type != raw_api_type:
                    mismatches.append(f"**{row['reg']}**: Assigned variant '{assigned_var}' expects type `{expected_type}`, but API reported `{raw_api_type}`.")
            
            # 3. If there are errors, block the save and show the user what to fix
            if mismatches:
                st.error("❌ Mismatch Error! The assigned variants do not match the aircraft types from the API.")
                for error_msg in mismatches:
                    st.write(f"- {error_msg}")
                st.warning("Please correct these mismatches in the grid above before saving.")
            
            # 4. If everything matches perfectly, proceed with the save!
            else:
                payload = edited_fleet.to_dict('records')
            
                final_payload = [{
                    "aircraft_reg": row["reg"], 
                    "operator_icao": row["operator_icao"], 
                    "variant": row["variant"], 
                    "type": row["type"],
                    "min_turnaround_min": None 
                } for row in payload]

                try:
                    with st.spinner("Updating fleet..."):
                        supabase.table("fleet").insert(final_payload).execute()
                        st.success("Fleet updated successfully!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")
else:
    st.success("All aircraft are perfectly mapped to variants. No action required.")

st.markdown("---")

# PHASE 2: THE ROUTE BUILDER GRID
st.subheader("Define Scheduled Routes")

# 1. Find routes in the raw data that are NOT in the flight_list table
known_routes_res = supabase.table("flight_list").select("flight_number, departure_airport, arrival_airport").in_("operator_id", operator_icaos).execute()
known_route_sigs = [f"{r['flight_number']}_{r['departure_airport']}_{r['arrival_airport']}" for r in known_routes_res.data]

df_raw['route_sig'] = df_raw['flight_number'].astype(str) + "_" + df_raw['origin_icao'].astype(str) + "_" + df_raw['destination_icao_actual'].astype(str)

df_missing_routes = df_raw[~df_raw['route_sig'].isin(known_route_sigs)][['operator_icao', 'flight_number', 'callsign', 'painted_as', 'origin_icao', 'destination_icao_actual', 'datetime_takeoff']].drop_duplicates(subset=['operator_icao', 'flight_number', 'origin_icao', 'destination_icao_actual'])

new_route_discover = len(df_missing_routes)

if not df_missing_routes.empty:
    # 1. Map historical registrations to variants
    fleet_res = supabase.table("fleet").select("aircraft_reg, variant").in_("operator_icao", operator_icaos).execute()
    reg_to_var = {f["aircraft_reg"]: f["variant"] for f in fleet_res.data}
    df_raw['mapped_variant'] = df_raw['reg'].map(reg_to_var)

    # 2. Map those variants to their body category (Passenger vs Cargo)
    df_raw['body_category'] = df_raw['mapped_variant'].map(variant_to_body_category)

    # 3. Scan function to check a flight number's most common historical category
    def check_route_cargo(flight_num):
        cats = df_raw[df_raw['flight_number'] == flight_num]['body_category'].dropna()
        if not cats.empty:
            # If the most frequent historical body category is CARGO, return True
            return cats.mode().iloc[0].upper() == "CARGO"
        return False
    
    # 4. Apply the scan to automatically toggle the checkbox
    df_missing_routes['is_cargo'] = df_missing_routes['flight_number'].apply(check_route_cargo)
    
    df_missing_routes['sch_dep_local'] = None
    df_missing_routes['sch_arr_local'] = None
    
    st.write(f"**{new_route_discover}** new routes were discovered. Please provide their scheduled **local times**. Cargo scheduled time have been automatically detected based on historical fleet usage so you don't need to fill their time.")
    
    edited_routes = st.data_editor(
        df_missing_routes,
        width="stretch",
        hide_index=True,
        disabled=["operator_icao", "flight_number", "painted_as", "callsign", "origin_icao", "destination_icao_actual", "datetime_takeoff"],
        column_config={
            "operator_icao": st.column_config.TextColumn("Operator"),
            "flight_number": st.column_config.TextColumn("Flight Number"),
            "painted_as": st.column_config.TextColumn("Flight of"),
            "callsign": st.column_config.TextColumn("Callsign"),
            "origin_icao": st.column_config.TextColumn("Origin ICAO"),
            "destination_icao_actual": st.column_config.TextColumn("Destination ICAO"),
            "datetime_takeoff": None, 
            "is_cargo": st.column_config.CheckboxColumn("Is Cargo?", help="Checked automatically if historical equipment was primarily cargo. System will use median times."),
            "sch_dep_local": st.column_config.TextColumn("Scheduled Dep Local Time (HH:MM)", required=True, help="Must be in 24-hour format, e.g., 14:30"),
            "sch_arr_local": st.column_config.TextColumn("Scheduled Arr Local Time (HH:MM)", required=True, help="Must be in 24-hour format, e.g., 08:15"),
        },
        key="route_editor"
    )
    
    if st.button("Save Filled Routes", type="primary"):
        from collections import Counter
        
        # --- PRE-CALCULATE VARIANTS ---
        # 1. Get the current mapped fleet to translate historical 'reg' into 'variant'
        fleet_res = supabase.table("fleet").select("aircraft_reg, variant").in_("operator_icao", operator_icaos).execute()
        reg_to_var = {f["aircraft_reg"]: f["variant"] for f in fleet_res.data}
        df_raw['mapped_variant'] = df_raw['reg'].map(reg_to_var)

        # Create an absolute fallback (the operator's most popular plane) just in case a flight has zero history
        global_var_counts = Counter(df_raw['mapped_variant'].dropna().tolist())
        global_top_variant = global_var_counts.most_common(1)[0][0] if global_var_counts else "UNKNOWN"    
            
        def calculate_flight_metrics(dep_utc_str, arr_utc_str):
            try:
                t1 = pd.to_datetime(dep_utc_str)
                t2 = pd.to_datetime(arr_utc_str)
                
                # Calculate difference in minutes
                delta_mins = (t2 - t1).total_seconds() / 60.0
                # Handle flights that cross midnight UTC
                if delta_mins < 0:
                    delta_mins += 1440 
                
                blocktime = int(delta_mins)
                
                # Determine category
                if blocktime <= 0:
                    return 0, "INVALID"
                elif blocktime < 120:
                    category = "SHORT HAUL"
                elif blocktime <= 360:
                    category = "MEDIUM HAUL"
                else:
                    category = "LONG HAUL"
                    
                return blocktime, category
            except Exception as e:
                print(f"Metric Calculation Error: {e}") 
                return 0, "Unknown"
        
        # def operates_on_date(day_of_week_str, target_date): return str(target_date.isoweekday()) in str(day_of_week_str)

        route_payload = []
        
        for _, row in edited_routes.iterrows():
            is_cargo = row.get("is_cargo", False)
            dep_local = row['sch_dep_local']
            arr_local = row['sch_arr_local']
            flt_num = row["flight_number"]
            painted_as = row.get("painted_as")
            origin = row["origin_icao"]
            dest = row["destination_icao_actual"]

            dep_tz = get_airport_info(origin, "iana_tz")
            arr_tz = get_airport_info(dest, "iana_tz")
            is_domestic = is_domestic_route(origin, dest, row["operator_icao"])

            # --- THE MEDIAN TIME FALLBACK LOGIC ---
            if is_cargo:
                hist_flights = df_raw[(df_raw['flight_number'] == flt_num) & (df_raw['origin_icao'] == origin)]
                
                # Calculate Circular Mean Departure
                if (pd.isna(dep_local) or str(dep_local).strip() == "") and not hist_flights.empty:
                    takeoffs_utc = pd.to_datetime(hist_flights['datetime_takeoff'].dropna(), utc=True)
                    if not takeoffs_utc.empty:
                        takeoffs_local = takeoffs_utc.dt.tz_convert(dep_tz)
                        dep_local = calculate_circular_mean_time(takeoffs_local)

                # Calculate Circular Mean Arrival 
                if (pd.isna(arr_local) or str(arr_local).strip() == "") and not hist_flights.empty:
                    if 'datetime_landed' in hist_flights.columns: 
                        landings_utc = pd.to_datetime(hist_flights['datetime_landed'].dropna(), utc=True)
                        if not landings_utc.empty:
                            landings_local = landings_utc.dt.tz_convert(arr_tz)
                            arr_local = calculate_circular_mean_time(landings_local)
            
            # --- PROCEED WITH NORMAL PIPELINE --- Only if both departure and arrival local times are provided (either by user or median fallback)      
            if pd.notna(dep_local) and pd.notna(arr_local) and str(dep_local).strip() != "" and str(arr_local).strip() != "":
                
                # 1. Convert Times
                dep_utc = convert_local_to_utc(dep_local, row['datetime_takeoff'], origin, {origin: dep_tz})
                arr_utc = convert_local_to_utc(arr_local, row['datetime_takeoff'], dest, {dest: arr_tz})

                # 2. Calculate blocktime_min and route_category
                blocktime_min, route_category = calculate_flight_metrics(dep_utc, arr_utc)
                
                # 3. Check used_variants for this flight number across the entire historical dataset and get the top 3 most common variants they've flown on this route
                historical_vars = df_raw[df_raw['flight_number'] == flt_num]['mapped_variant'].dropna().tolist()
                var_counts = Counter(historical_vars)
                top_3 = [v for v, c in var_counts.most_common(3)]
                
                while len(top_3) < 3:
                    if len(top_3) > 0:
                        top_3.append(top_3[0])
                    else:
                        top_3.append(global_top_variant)

                # Default to PASSENGER if the body category isn't found
                primary_body_cat = variant_to_body_category.get(top_3[0], "PASSENGER")
                service_prefix = "CARGO" if primary_body_cat == "CARGO" else "PASSENGER"
                route_type = f"{service_prefix}-{is_domestic}"

                # 4. Check day_off_week for this flight number across the entire historical dataset and create a string of unique operating days (1=Mon, 7=Sun)
                historical_takeoffs = df_raw[df_raw['flight_number'] == flt_num]['datetime_takeoff'].dropna().tolist()
                operating_days = set(str(pd.to_datetime(dt).isoweekday()) for dt in historical_takeoffs)
                day_string = ",".join(sorted(list(operating_days))) if operating_days else "1,2,3,4,5,6,7"
                
                # 5. Append to payload
                route_payload.append({
                    "flight_number": flt_num,
                    "operator_id": row["operator_icao"],
                    "painted_as": painted_as,
                    "day_of_week": day_string, 
                    "departure_airport": row["origin_icao"],
                    "arrival_airport": row["destination_icao_actual"],
                    "scheduled_departure_time_utc": dep_utc, 
                    "scheduled_arrival_time_utc": arr_utc,
                    "blocktime_min": blocktime_min, 
                    "route_type": route_type,
                    "route_category": route_category,
                    "callsign": row["callsign"],
                    "used_variant_1": top_3[0],
                    "used_variant_2": top_3[1], 
                    "used_variant_3": top_3[2]
                })
        
        if len(route_payload) > 0:
            try:
                with st.spinner("Processing flight data and refreshing fleet status..."):
                    supabase.rpc("sync_flight_pipeline", {"route_payload": route_payload}).execute()
                    
                st.success(f"Successfully saved and scheduled {len(route_payload)} routes!")
                time.sleep(1.5) 
                st.switch_page("pages/dashboard_sub.py")
                st.rerun()
            except Exception as e:
                st.error(f"Database Error: {e}")
        else:
            st.error("No valid routes were processed. Ensure all required times are filled out.")
else:
    st.success("All historical routes are fully mapped. No action required.")

st.markdown("---")