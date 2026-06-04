import streamlit as st
from datetime import datetime
from utils import setup_page
from func import convert_utc_to_local_1, get_airport_info
from map_component import load_flight_data, render_flight_map
from data_handler import get_active_operator_network

# --- 1. GET CURRENT PROFILE & SUBSIDIARIES ---
supabase = setup_page("Fleet Status")
current_profile, operator_icaos = get_active_operator_network()

# --- 2. FETCH FLEET STATUS FOR ALL RELATED ICAOS ---
# Fetch Fleet Status Data
fleet_res = supabase.table("fleet_status").select(
    "aircraft_reg, aircraft_type, prev_arrival_datetime, current_airport, next_ready_airport, next_ready_utc, last_updated, fleet!inner(operator_icao)"
).in_("fleet.operator_icao", operator_icaos).execute()

raw_fleet_data = fleet_res.data if fleet_res.data else []

# --- 3. TOP HEADER NAVIGATION ---
col_title, col_back = st.columns([2.5, 1], vertical_alignment="bottom")

with col_title:
    st.title(f"{current_profile}")
with col_back:
    if st.button("Back", width='stretch'):
        st.switch_page("pages/dashboard_sub.py")

st.markdown("""
        This dashboard provides a real-time snapshot of your fleet's current status and recent movements. Use the filters to narrow down by aircraft type or registration, and explore the interactive map to visualize recent flight paths. This is your command center for monitoring fleet readiness and optimizing operations!    
        """)
st.markdown("---")

# --- 4. DASHBOARD SECTIONS ---

# ROW 1: FLEET STATUS
st.markdown("### Fleet Status")

# Extract unique types and registrations for filters
available_types = ["All Types"]
available_regs = ["All Aircraft"]

if raw_fleet_data:
    unique_types = sorted({str(row.get('aircraft_type', '')).strip() for row in raw_fleet_data if row.get('aircraft_type')})
    available_types.extend(unique_types)

# --- CONTROL PANEL ---
col1, col2 = st.columns(2)

with col1:
    selected_type = st.selectbox("Select Aircraft Type (Status & Map):", options=available_types)
    if raw_fleet_data:
        if selected_type == "All Types":
            unique_regs = sorted({str(row.get('aircraft_reg', '')).strip() for row in raw_fleet_data if row.get('aircraft_reg')})
        else:
            # Show only registrations matching the selected type
            unique_regs = sorted({
                str(row.get('aircraft_reg', '')).strip() for row in raw_fleet_data 
                if row.get('aircraft_reg') and str(row.get('aircraft_type', '')).strip() == selected_type
            })
        available_regs.extend(unique_regs)

with col2:
    selected_reg = st.selectbox("Select Aircraft Registration (Status & Map):", options=available_regs)

with st.container(border=True):
    st.write("Current static positioning and turnaround readiness.")

st.markdown("<br>", unsafe_allow_html=True)

# --- ROW 2: FLEET LOCATION ---
filtered_fleet_data = raw_fleet_data

# 1. Filter by Type
if selected_type != "All Types":
    filtered_fleet_data = [row for row in filtered_fleet_data if str(row.get('aircraft_type', '')).strip() == selected_type]

# 2. Filter by Reg
if selected_reg != "All Aircraft":
    filtered_fleet_data = [row for row in filtered_fleet_data if str(row.get('aircraft_reg', '')).strip() == selected_reg]

# 3. Build the table
if filtered_fleet_data:
    processed_fleet_rows = []

    for row in filtered_fleet_data:  
        airport_code = get_airport_info(row.get('current_airport'), 'iata_code')
        airport_city = get_airport_info(row.get('current_airport'), 'city')
        cur_loc_str = f"{airport_code} - {airport_city}" if row.get('current_airport') else "--"

        prev_arr_local = convert_utc_to_local_1(row.get("prev_arrival_datetime"), get_airport_info(row.get("current_airport"), "iana_tz"))
        next_ready_local = convert_utc_to_local_1(row.get("next_ready_utc"), get_airport_info(row.get("next_ready_airport"), "iana_tz"))

        # Handle Date for Sorting
        display_date = "--"
        sort_val = "1970-01-01"
            
        if row.get("next_ready_utc"):
            dt_obj = datetime.fromisoformat(row["next_ready_utc"].replace("Z", "+00:00"))
            display_date = dt_obj.strftime("%Y-%m-%d")
            sort_val = display_date
                
        processed_fleet_rows.append({
            "sort_date": sort_val,
            "display_date": display_date,
            "reg": row.get('aircraft_reg', '--'),
            "cur_loc": cur_loc_str,
            "prev_arr": prev_arr_local,
            "next_ready": next_ready_local
        })

    # 4. Sort rows by date (descending) and then by previous arrival time (descending)
    sorted_rows = sorted(processed_fleet_rows, key=lambda x: (x["sort_date"], x["prev_arr"]), reverse=True)

    # 5. Build the UI Header Row
    h1, h2, h3, h4, h5 = st.columns([1, 1.2, 2.5, 1.4, 1.4])
    with h1: st.markdown("**Date**")
    with h2: st.markdown("**Reg. Number**")
    with h3: st.markdown("**Current Location**")
    with h4: st.markdown("**Previous Arrival Time (Local)**")
    with h5: st.markdown("**Next Ready Time (Local)**")

    st.divider() 
        
    # 6. Build the Data Rows
    for row in sorted_rows:
        c1, c2, c3, c4, c5 = st.columns([1, 1.2, 2.5, 1.4, 1.4], vertical_alignment="center")
        with c1: st.write(row['display_date']) 
        with c2: st.write(f"**{row['reg']}**")
        with c3: st.write(row['cur_loc']) 
        with c4: st.write(row['prev_arr'])
        with c5: st.write(row['next_ready'])
            
        st.markdown("<div style='margin-top: 8px; margin-bottom: 8px; border-bottom: 1px solid #333;'></div>", unsafe_allow_html=True)

else:
    st.warning("No fleet status data available for this operator.")
st.markdown("<br>", unsafe_allow_html=True)

# ROW 4: AIRCRAFT MOVEMENT MAP
st.markdown("#### Aircraft Movement Map")

selected_days = st.selectbox("Select Timeframe (Map Only):", options=[1, 2, 3, 4, 5, 6, 7], index=6, format_func=lambda x: f"Last {x} Day{'s' if x > 1 else ''}")

with st.container(border=True):
    try:
        with st.spinner("Loading flight paths..."):
            map_df = load_flight_data(days=selected_days)
    except Exception as e:
        st.error(f"Database error: {e}")
        st.stop()

    # 2. Filter map data strictly to the operator(s) we are currently viewing
    if not map_df.empty:
        filtered_df = map_df[map_df['operator_id'].isin(operator_icaos)]
    else:
        filtered_df = map_df.copy()

    # 3. Apply the Aircraft Type filter
    if selected_type != "All Types" and 'aircraft_type' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['aircraft_type'] == selected_type]

    # 4. Apply the Aircraft Registration filter
    if selected_reg != "All Aircraft":
        filtered_df = filtered_df[filtered_df['aircraft_reg'] == selected_reg]

    # -- RENDER THE MAP --
    st.write(f"Displaying flight paths for **{selected_reg}** over the past **{selected_days}** day{'s' if selected_days > 1 else ''}.")
    st.markdown("---") 

    if not filtered_df.empty:
        render_flight_map(filtered_df)
    else:
        st.info("No flight movement recorded for this selection within the chosen timeframe.")

st.markdown("<br>", unsafe_allow_html=True)

