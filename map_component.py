import pandas as pd
import pydeck as pdk
import streamlit as st
from utils import init_connection_2

@st.cache_data(ttl=3600)
def load_flight_data(days=30):
    engine = init_connection_2()

    # Ensure days is an integer to prevent any SQL syntax errors
    safe_days = int(days)
    
    query = f"""
    WITH FlightSequence AS (
        SELECT 
            fl.aircraft_reg,
            fl.aircraft_type,
            fl.operator_id,
            fl.was_at AS origin_icao,
            al.latitude AS start_lat,
            al.longitude AS start_lon,
            fl.curr_departure_datetime AS departure_time
        FROM public.flight_logs fl
        JOIN public.airport_list al ON fl.was_at = al.icao_code
        WHERE fl.curr_departure_datetime >= NOW() - INTERVAL '{safe_days} days'
    )
    SELECT 
        aircraft_reg,
        aircraft_type,
        operator_id,
        origin_icao,
        start_lat,
        start_lon,
        departure_time,
        LEAD(origin_icao) OVER (PARTITION BY aircraft_reg ORDER BY departure_time) AS dest_icao,
        LEAD(start_lat) OVER (PARTITION BY aircraft_reg ORDER BY departure_time) AS end_lat,
        LEAD(start_lon) OVER (PARTITION BY aircraft_reg ORDER BY departure_time) AS end_lon
    FROM FlightSequence;
    """
    
    # Use the engine connection with Pandas
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
        
    arcs_df = df.dropna(subset=['end_lat', 'end_lon']).copy()

    if not arcs_df.empty:
        # CLEANUP: Strip trailing spaces and enforce uppercase so it matches Supabase exact filters
        arcs_df['aircraft_reg'] = arcs_df['aircraft_reg'].astype(str).str.strip().str.upper()
        arcs_df['aircraft_type'] = arcs_df['aircraft_type'].astype(str).str.strip().str.upper()
        arcs_df['operator_id'] = arcs_df['operator_id'].astype(str).str.strip().str.upper()

        # Convert all coordinate columns to strict floats
        arcs_df['start_lat'] = arcs_df['start_lat'].astype(float)
        arcs_df['start_lon'] = arcs_df['start_lon'].astype(float)
        arcs_df['end_lat'] = arcs_df['end_lat'].astype(float)
        arcs_df['end_lon'] = arcs_df['end_lon'].astype(float)
    return arcs_df

def render_flight_map(filtered_df):
    if filtered_df.empty:
        st.warning("No flight data found for the selected criteria.")
        return

    # Force floats
    for col in ['start_lat', 'start_lon', 'end_lat', 'end_lon']:
        filtered_df[col] = filtered_df[col].astype(float)

    # --- PYDECK MAP ---
    st.subheader("3D Flight Paths")
    filtered_df['source_pos'] = filtered_df.apply(lambda r: [r['start_lon'], r['start_lat']], axis=1)
    filtered_df['target_pos'] = filtered_df.apply(lambda r: [r['end_lon'], r['end_lat']], axis=1)
    clean_data = filtered_df.to_dict(orient='records')

    arc_layer = pdk.Layer(
        "ArcLayer",
        data=clean_data,
        get_source_position="source_pos",
        get_target_position="target_pos",
        get_source_color=[0, 255, 0, 200],   
        get_target_color=[255, 0, 0, 200],   
        get_width=3,
    )
    
    view_state = pdk.ViewState(
        latitude=filtered_df["start_lat"].mean(),
        longitude=filtered_df["start_lon"].mean(),
        zoom=3,
        pitch=45
    )

    # Render with map_style=None
    st.pydeck_chart(pdk.Deck(
        map_style=None, 
        layers=[arc_layer],
        initial_view_state=view_state
    ))