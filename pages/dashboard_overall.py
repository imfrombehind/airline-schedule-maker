import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
from func import get_airport_info
from utils import setup_page
from data_handler import refresh_dashboard_cache, fetch_operators, fetch_schedules, fetch_history, fetch_fleet, fetch_airport_visits, process_merged_flight_data, process_turnarounds, fetch_aircraft_types

supabase = setup_page("Overview Dashboard - Airline Strategy Comparison")

# --- 1. FETCH OPERATORS & RENDER HEADER ---
@st.cache_data(show_spinner="Loading operators...")
def get_operators_data():
    return fetch_operators()

operators_df = get_operators_data()

col_title, col_refresh, col_back = st.columns([2.5, 1, 0.5], vertical_alignment="bottom")
with col_title:
    st.title("Comparative Dashboard")
with col_refresh:
    st.button("Refresh Data", width="stretch", on_click=refresh_dashboard_cache)
with col_back:
    if st.button("Back", width='stretch'):
        st.switch_page("app.py")

st.markdown("Analyze fleet strategy, network efficiency, and operational performance across multiple airlines.")
st.markdown("---")

# --- 2. COMPARISON CONTROLS ---
if not operators_df.empty:
    op_dict = dict(zip(operators_df['name'], operators_df['icao_designator']))
    icao_to_name = dict(zip(operators_df['icao_designator'], operators_df['name']))
    available_airlines = sorted(list(op_dict.keys()))
else:
    st.error("No operators found in database.")
    st.stop()

col_ctrl1, col_ctrl2 = st.columns([3, 1], vertical_alignment="bottom")

with col_ctrl1:
    selected_airline_names = st.multiselect(
        "Select Airlines to Compare (Choose 2 to 4 recommended):", 
        options=available_airlines,
        default=available_airlines[:2] if len(available_airlines) >= 2 else available_airlines
    )

if not selected_airline_names:
    st.info("Select at least one airline to begin analysis.")
    st.stop()

selected_icaos = [op_dict[name] for name in selected_airline_names]
selected_icaos_tuple = tuple(selected_icaos)

# --- 3. FETCH TARGETED DATA ENGINE ---
@st.cache_data(show_spinner="Loading and calculating strategic data...")
def get_strategic_comparison_data(cache_date, icaos_tuple):
    df_sched = fetch_schedules(icaos_tuple) 
    df_hist_raw = fetch_history(icaos_tuple)
    df_fleet_raw = fetch_fleet(icaos_tuple)
    df_visits = fetch_airport_visits(icaos_tuple)
    df_type_raw = fetch_aircraft_types()

    df_hist_processed = process_turnarounds(df_hist_raw)

    if not df_fleet_raw.empty and not df_type_raw.empty:
        df_fleet = pd.merge(df_fleet_raw, df_type_raw, on="variant", how='left')
    else:
        df_fleet = df_fleet_raw.copy()

    return df_sched, df_hist_raw, df_hist_processed, df_fleet, df_visits

current_date_str = date.today().isoformat()
df_sched, df_hist_raw, df_hist_processed, df_fleet, df_visits = get_strategic_comparison_data(current_date_str, selected_icaos_tuple)

# Populate the Route Dropdown based on fetched schedules
with col_ctrl2:
    available_route_types = ["All Routes"]
    if not df_sched.empty and 'route_type' in df_sched.columns:
        base_routes = {str(x).split('-')[0].strip().title() for x in df_sched['route_type'].dropna().unique() if str(x).strip()}
        available_route_types.extend(sorted(list(base_routes)))
    else:
        available_route_types.extend(["Passenger", "Cargo"])
        
    selected_route = st.selectbox("Select Route Type:", options=available_route_types)

# --- APPLY FILTERS TO ALL BASE DATASETS ---
sched_base = df_sched.copy()
hist_base = df_hist_processed.copy()
fleet_base = df_fleet.copy()
visits_base = df_visits.copy()

if selected_route != "All Routes":
    route_lower = selected_route.lower()
    
    # 1. Filter Schedule 
    if not sched_base.empty and 'route_type' in sched_base.columns:
        sched_base = sched_base[sched_base['route_type'].astype(str).str.contains(selected_route, case=False, na=False)]
    elif not sched_base.empty and 'is_cargo' in sched_base.columns:
        sched_cargo = sched_base['is_cargo'].astype(str).str.lower()
        if route_lower == "passenger":
            sched_base = sched_base[sched_cargo.isin(['false', '0', 'passenger'])]
        elif route_lower == "cargo":
            sched_base = sched_base[sched_cargo.isin(['true', '1', 'cargo'])]

    # 2. Filter Visits 
    if not visits_base.empty and not sched_base.empty:
        valid_airports = set(sched_base['departure_airport'].dropna()).union(set(sched_base['arrival_airport'].dropna()))
        visits_base = visits_base[visits_base['airport_icao'].isin(valid_airports)]
    else:
        visits_base = pd.DataFrame()

    # 3. Filter Fleet & Cascade to Turnaround History
    if not fleet_base.empty and 'body_category' in fleet_base.columns:
        fleet_body_str = fleet_base['body_category'].astype(str).str.lower()
        if route_lower == "passenger":
            fleet_base = fleet_base[fleet_body_str.isin(['passenger', 'pax'])]
        elif route_lower == "cargo":
            fleet_base = fleet_base[fleet_body_str.isin(['cargo', 'freighter', 'freight'])]

    if not hist_base.empty and not fleet_base.empty and 'reg' in hist_base.columns:
        valid_regs = fleet_base['aircraft_reg'].dropna().unique()
        if len(valid_regs) > 0:
            hist_base = hist_base[hist_base['reg'].isin(valid_regs) | hist_base['reg'].isna()]

# --- 4. DYNAMICALLY COMPUTE MERGED DATA ---
# LEFT JOIN ensures cancelled flights remain in the dataframe for Completion Rate math
merged_base = process_merged_flight_data(sched_base.copy(), df_hist_raw.copy(), join_type="left")

# --- FILTER DATASETS BY SELECTED OPERATORS ---
sched_f = sched_base[sched_base['operator_id'].isin(selected_icaos)].copy() if not sched_base.empty else pd.DataFrame()
merged_f = merged_base[merged_base['operator_id'].isin(selected_icaos)].copy() if not merged_base.empty else pd.DataFrame()
fleet_f = fleet_base[fleet_base['operator_icao'].isin(selected_icaos)].copy() if not fleet_base.empty else pd.DataFrame()
hist_f = hist_base[hist_base['operator_icao'].isin(selected_icaos)].copy() if not hist_base.empty else pd.DataFrame()
visits_f = visits_base[visits_base['operator_icao'].isin(selected_icaos)].copy() if not visits_base.empty else pd.DataFrame()

# --- 5. CALCULATE STRATEGIC METRICS ---
comp_data = []

for name in selected_airline_names:
    icao = op_dict[name]
    
    al_sched = sched_f[sched_f['operator_id'] == icao] if not sched_f.empty else pd.DataFrame()
    weekly_flights = al_sched['weekly_freq'].sum() if not al_sched.empty else 0
    unique_routes = al_sched['Route'].nunique() if not al_sched.empty and 'Route' in al_sched.columns else 0

    # Turnaround
    operator_col_hist = 'operator_icao' if 'operator_icao' in hist_f.columns else ('operator_id' if 'operator_id' in hist_f.columns else None)
    if operator_col_hist and not hist_f.empty:
        al_hist = hist_f[hist_f[operator_col_hist] == icao]
        if not al_hist.empty and 'turnaround_mins' in al_hist.columns:
            valid_turns = al_hist[(al_hist['turnaround_mins'] >= 20) & (al_hist['turnaround_mins'] <= 720)]
            avg_turn = int(round(valid_turns['turnaround_mins'].mean(), 0)) if not valid_turns.empty else None
        else: avg_turn = None
    else: avg_turn = None
    
    # Hub Dominance
    hub_icao = None
    hub_str = "--"
    if not al_sched.empty and 'departure_airport' in al_sched.columns and weekly_flights > 0:
        hub_icao = al_sched.groupby('departure_airport')['weekly_freq'].sum().idxmax()
        top_airport_flights = al_sched.groupby('departure_airport')['weekly_freq'].sum().max()
        hub_dominance = round((top_airport_flights / weekly_flights) * 100, 1)
        hub_iata = get_airport_info(hub_icao, 'iata_code') or hub_icao
        hub_str = f"{hub_iata} ({hub_dominance}%)"

    # Fleet
    al_fleet = fleet_f[fleet_f['operator_icao'] == icao] if not fleet_f.empty else pd.DataFrame()
    fleet_size = len(al_fleet)
    uniformity_score = int((al_fleet['variant'].value_counts(normalize=True) ** 2).sum() * 100) if fleet_size > 0 and 'variant' in al_fleet.columns else 0

    # Operations & OTP Math
    al_merged = merged_f[merged_f['operator_id'] == icao] if not merged_f.empty else pd.DataFrame()
    
    if not al_merged.empty and 'Performance_Status' in al_merged.columns:
        total_scheduled = len(al_merged)
        
        # 1. Calculate Completion Rate (Cancellations against Total Schedule)
        cancelled_legs = al_merged['Performance_Status'].astype(str).str.contains('Cancel', case=False, na=False).sum()
        total_completed = total_scheduled - cancelled_legs
        
        comp_rate = round((total_completed / total_scheduled) * 100, 1) if total_scheduled > 0 else 0.0
        
        # 2. Calculate OTP (On-Time against Flights that actually flew)
        if total_completed > 0:
            on_time = al_merged['Performance_Status'].isin(['Early', 'On Time']).sum()
            otp_pct = round((on_time / total_completed) * 100, 1)
        else:
            otp_pct = 0.0
    else:
        otp_pct, comp_rate = 0.0, 0.0

    comp_data.append({
        "Airline": name,
        "Hub_ICAO": hub_icao, 
        "Fleet Size": fleet_size,
        "Uniformity Score": uniformity_score,
        "Hub Focus": hub_str,
        "OTP (%)": otp_pct,
        "Completion (%)": comp_rate,
        "Avg Turnaround (mins)": avg_turn,
        "Unique Routes": unique_routes,
        "Weekly Flights": weekly_flights,
    })

df_metrics = pd.DataFrame(comp_data)

# --- 6. RENDER SCORECARDS ---
cols = st.columns(len(selected_airline_names))
for i, row in df_metrics.iterrows():
    name = row['Airline']
    icao = op_dict[name]

    with cols[i]:
        with st.container(border=True):
            st.markdown(f"<h3 style='text-align: center; margin-bottom: 0px;'>{name}</h3>", unsafe_allow_html=True)
            st.markdown("<hr style='margin-top: 8px; margin-bottom: 16px;'>", unsafe_allow_html=True)
            
            m1, m2 = st.columns(2)
            with m1: st.markdown(f"<small>On-Time Performance</small><br><b style='font-size:24px;'>{row['OTP (%)']}%</b>", unsafe_allow_html=True)
            with m2: st.markdown(f"<small>Completion Rate</small><br><b style='font-size:24px;'>{row['Completion (%)']}%</b>", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
            
            m3, m4 = st.columns(2)
            with m3: st.markdown(f"<small>Main Hub</small><br><span style='font-size:24px; font-weight:600; line-height:1.2;'>{row['Hub Focus']}</span>", unsafe_allow_html=True)
            with m4: st.markdown(f"<small>Weekly Flights</small><br><b style='font-size:24px;'>{int(row['Weekly Flights']):,}</b>", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

            m5, m6 = st.columns(2)
            with m5: st.markdown(f"<small>Routes Served</small><br><b style='font-size:24px;'>{int(row['Unique Routes'])}</b>", unsafe_allow_html=True)     
            with m6:
                st.markdown("<small>Route Categories</small><br><span style='font-size:24px; font-weight:600; line-height:1.2;'></span>", unsafe_allow_html=True)
                al_sched = sched_f[sched_f['operator_id'] == icao] if not sched_f.empty and 'operator_id' in sched_f.columns else pd.DataFrame()
                if not al_sched.empty and 'is_cargo' in al_sched.columns:
                    for cp, count in al_sched['is_cargo'].value_counts().items():
                        st.markdown(f"""<div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 2px; padding: 2px 4px; background: rgba(255,255,255,0.03); border-radius: 4px;"><span>{cp}</span><span style="font-weight: bold;">{count} flights</span></div>""", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
            
            m7, m8 = st.columns(2)
            with m7:
                u_color = "#00CC96" if row['Uniformity Score'] > 80 else "#f59e0b" if row['Uniformity Score'] > 50 else "#FF4B4B"
                st.markdown(f"<small>Fleet Uniformity</small><br><b style='font-size:24px; color:{u_color};'>{row['Uniformity Score']}%</b>", unsafe_allow_html=True)
            with m8: st.markdown(f"<small>Fleet Size</small><br><b style='font-size:24px;'>{int(row['Fleet Size'])} aircrafts</b>", unsafe_allow_html=True)

            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
            st.markdown("<p style='margin-bottom: 4px; font-weight: 600; font-size: 14px;'>Fleet</p>", unsafe_allow_html=True)

            if not fleet_f.empty:
                al_fleet = fleet_f[fleet_f['operator_icao'] == icao].copy()
                if not al_fleet.empty and 'type' in al_fleet.columns:
                    for _, f_row in al_fleet[['type']].drop_duplicates().sort_values(by=['type']).iterrows():
                        count = len(al_fleet[al_fleet['type'] == f_row['type']])
                        st.markdown(f"""<div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 2px; padding: 2px 4px; background: rgba(255,255,255,0.03); border-radius: 4px;"><span>• {f_row['type']}</span><span style="font-weight: bold;">{count} aircrafts</span></div>""", unsafe_allow_html=True)
                else: st.markdown("<span style='color:gray; font-size:12px;'>No active fleet detected</span>", unsafe_allow_html=True)
            else: st.markdown("<span style='color:gray; font-size:12px;'>No fleet data available</span>", unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<p style='margin-bottom: 4px; font-weight: 600; font-size: 14px;'>Min Turnaround Baseline</p>", unsafe_allow_html=True)

            if not fleet_f.empty:
                al_fleet = fleet_f[fleet_f['operator_icao'] == icao].copy()
                if not al_fleet.empty and 'type' in al_fleet.columns and 'variant' in al_fleet.columns:
                    for _, f_row in al_fleet[['type', 'variant', 'min_turnaround_min']].drop_duplicates().sort_values(by=['type', 'variant']).iterrows():
                        min_turn = f"{int(f_row['min_turnaround_min'])} mins" if pd.notna(f_row['min_turnaround_min']) else "N/A"
                        st.markdown(f"""<div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 2px; padding: 2px 4px; background: rgba(255,255,255,0.03); border-radius: 4px;"><span>• {f_row['type']} <span style="opacity: 0.7;">({f_row['variant']})</span></span><span style="font-weight: bold;">{min_turn}</span></div>""", unsafe_allow_html=True)
                else: st.markdown("<span style='color:gray; font-size:12px;'>No active fleet detected</span>", unsafe_allow_html=True)
            else: st.markdown("<span style='color:gray; font-size:12px;'>No fleet data available</span>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# --- 7. NETWORK DNA (MARKET & HAUL) ---
st.markdown("### Analysis of Market Focus & Flight Range")
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    with st.container(border=True):
        st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Scale Comparison (Flights vs Fleet)</div>", unsafe_allow_html=True)
        if not df_metrics.empty:
            fig_scale = go.Figure()
            fig_scale.add_trace(go.Bar(x=df_metrics['Airline'], y=df_metrics['Weekly Flights'], name='Weekly Flights', marker_color='#8b5cf6'))
            fig_scale.add_trace(go.Bar(x=df_metrics['Airline'], y=df_metrics['Fleet Size'], name='Fleet Size', marker_color='#3b82f6'))
            fig_scale.update_layout(barmode='group', margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_scale, width='stretch')

with chart_col2:
    with st.container(border=True):
        st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Turnaround Efficiency (Mins)</div>", unsafe_allow_html=True)
        if not df_metrics.empty:
            valid_turns_df = df_metrics.dropna(subset=['Avg Turnaround (mins)'])
            if not valid_turns_df.empty:
                fig_turn = px.bar(valid_turns_df, x='Airline', y='Avg Turnaround (mins)', color='Airline', text_auto='.0f', color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_turn.update_traces(textposition='outside', cliponaxis=False)
                fig_turn.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Minutes", margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_turn, width='stretch')
            else:
                st.info("No turnaround data available for the selected airlines.")

st.markdown("<br>", unsafe_allow_html=True)

chart_col3, chart_col4 = st.columns(2)

with chart_col3:
    with st.container(border=True):
        st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Domestic vs. International Focus</div>", unsafe_allow_html=True)
        if not sched_f.empty and 'Market' in sched_f.columns:
            market_counts = sched_f.groupby(['operator_id', 'Market'])['weekly_freq'].sum().reset_index()
            market_counts['Airline'] = market_counts['operator_id'].map(icao_to_name)
            fig_market = px.bar(market_counts, x="Airline", y="weekly_freq", color="Market", barmode="group", text_auto=True, color_discrete_map={"Domestic": "#3b82f6", "International": "#8b5cf6"})
            fig_market.update_layout(xaxis_title=None, yaxis_title="Weekly Flights", margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_market, width='stretch')
        else:
            st.info("Market Focus data unavailable.")

with chart_col4:
    with st.container(border=True):
        st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Flight Range Distribution</div>", unsafe_allow_html=True)
        if not sched_f.empty and 'route_category' in sched_f.columns:
            haul_counts = sched_f.groupby(['operator_id', 'route_category'])['weekly_freq'].sum().reset_index()
            haul_counts['Airline'] = haul_counts['operator_id'].map(icao_to_name)
            fig_haul = px.bar(haul_counts, x="Airline", y="weekly_freq", color="route_category", barmode="stack", text_auto=True, color_discrete_sequence=px.colors.qualitative.Safe)
            fig_haul.update_layout(xaxis_title=None, yaxis_title="Weekly Flights", margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_haul, width='stretch')
        else:
            st.info("Route Category data unavailable.")

st.markdown("<br>", unsafe_allow_html=True)

# --- 8. SHARED ROUTE COLLISION MATRIX ---
st.markdown("### Direct Market Competition")
st.markdown("Routes where the selected airlines operate head-to-head.")

with st.container(border=True):
    if len(selected_airline_names) < 2:
        st.info("Select at least 2 airlines to analyze shared routes.")
    elif sched_f.empty or 'Route' not in sched_f.columns:
        st.info("No schedule data available.")
    else:
        route_ops = sched_f.groupby(['Route', 'operator_id'])['weekly_freq'].sum().reset_index()
        route_ops['Airline_Name'] = route_ops['operator_id'].map(icao_to_name)
        overlap_df = route_ops.pivot(index='Route', columns='Airline_Name', values='weekly_freq').fillna(0)
        
        overlap_df['Airlines_On_Route'] = (overlap_df > 0).sum(axis=1)
        shared_routes = overlap_df[overlap_df['Airlines_On_Route'] >= 2].copy()
        
        if shared_routes.empty:
            st.success("No overlapping routes detected. These airlines operate entirely independent networks.")
        else:
            shared_routes = shared_routes.drop(columns=['Airlines_On_Route'])
            shared_routes['Total_Market_Frequency'] = shared_routes.sum(axis=1)
            shared_routes = shared_routes.sort_values(by='Total_Market_Frequency', ascending=False)
            for col in shared_routes.columns: shared_routes[col] = shared_routes[col].astype(int)
            st.dataframe(shared_routes, width='stretch')

st.markdown("<br>", unsafe_allow_html=True)

# --- 9. COMPARATIVE HUB & SPOKE MAP ---
st.markdown("### Comparative Network Overlay")
st.markdown("Visualizes destinations served from each airline's primary hub. Bubble size indicates flight frequency.")

with st.container(border=True):
    if df_metrics.empty or visits_f.empty:
        st.info("Insufficient data to generate network map.")
    else:
        fig_map = go.Figure()
        colors = px.colors.qualitative.G10 

        for idx, row in df_metrics.iterrows():
            icao = op_dict[row['Airline']]
            hub_icao = row['Hub_ICAO']
            color = colors[idx % len(colors)]

            if not hub_icao: continue
            
            airline_visits = visits_f[visits_f['operator_icao'] == icao]
            hub_data = airline_visits[airline_visits['airport_icao'] == hub_icao]

            if not hub_data.empty:
                try:
                    hub_lat = float(hub_data.iloc[0]['latitude'])
                    hub_lon = float(hub_data.iloc[0]['longitude'])
                    hub_iata = hub_data.iloc[0]['iata']
                except: continue 
            else: continue
            
            lats, lons, texts, sizes = [], [], [], []
            
            for _, v_row in airline_visits.iterrows():
                dest = v_row['airport_icao']
                try:
                    dest_lat = float(v_row.get('latitude'))
                    dest_lon = float(v_row.get('longitude'))
                except: continue

                count = v_row.get('flight_count', 0)
                lats.append(dest_lat)
                lons.append(dest_lon)
                texts.append(f"<b>{v_row.get('iata', dest)}</b><br>{count} visits")
                sizes.append(min(max((count ** 0.5) * 3, 5), 40))

                if dest != hub_icao:
                    fig_map.add_trace(go.Scattergeo(lon=[hub_lon, dest_lon], lat=[hub_lat, dest_lat], mode='lines', line=dict(width=1.5, color=color), opacity=0.3, showlegend=False, hoverinfo='skip'))
            
            if lats and lons:
                fig_map.add_trace(go.Scattergeo(lon=lons, lat=lats, mode='markers', marker=dict(size=sizes, color=color, opacity=0.8, line=dict(width=0.5, color='white')), name=row['Airline'], text=texts, hoverinfo='text+name'))
            
            fig_map.add_trace(go.Scattergeo(lon=[hub_lon], lat=[hub_lat], mode='markers+text', marker=dict(size=14, color=color, symbol='star', line=dict(width=1, color='black')), text=[f"HUB: {hub_iata}"], textposition="bottom right", textfont=dict(size=12, color="white" if color in ['#3366CC', '#109618'] else "black"), name=f"{row['Airline']} Hub", showlegend=False))
                
        fig_map.update_layout(height=600, geo=dict(projection_type="natural earth", showland=True, landcolor="rgba(243, 244, 246, 0.5)", showocean=True, oceancolor="rgba(255, 255, 255, 0.1)", showcountries=True, countrycolor="rgba(209, 213, 219, 0.5)", coastlinecolor="rgba(209, 213, 219, 0.8)"), margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_map, width='stretch')