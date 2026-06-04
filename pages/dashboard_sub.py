import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from utils import setup_page
from func import convert_utc_to_local_2, get_airport_info, format_day_of_week
from data_handler import get_active_operator_network, refresh_dashboard_cache, fetch_schedules, fetch_history, fetch_fleet, fetch_airport_visits, fetch_aircraft_types, process_merged_flight_data

# --- 1. GET CURRENT PROFILE & SUBSIDIARIES ---
supabase = setup_page("Detail Operations")
current_profile, operator_icaos = get_active_operator_network()

# --- 2. TOP HEADER NAVIGATION ---
col_title, col_edit, col_nav1, col_nav2, col_back = st.columns([2.5, 1, 1, 1, 1], vertical_alignment="bottom")

with col_title:
    st.title(f"{current_profile}")
with col_edit:
    if st.button("Edit Profile", width='stretch'):
        st.session_state.edit_profile_name = current_profile
        st.switch_page("pages/operator_profiles.py")
with col_nav1:
    if st.button("Daily Prediction", width='stretch'):
        st.session_state.edit_profile_name = current_profile
        st.switch_page("pages/daily_prediction.py")
with col_nav2:
    if st.button("Input Flights", width='stretch'):
        st.switch_page("pages/flight_input_handler.py")
with col_back:
    if st.button("Back", width='stretch'):
        st.switch_page("pages/operators.py")

st.markdown("---")

# --- 3. CACHED DATA FETCHING & PRE-PROCESSING ---
@st.cache_data(show_spinner="Loading and processing dashboard data (daily cache)...")
def get_daily_dashboard_data(operator_icaos_tuple, cache_date):
    df_sched_raw = fetch_schedules(operator_icaos_tuple)
    df_hist = fetch_history(operator_icaos_tuple)
    df_visits_raw = fetch_airport_visits(operator_icaos_tuple)
    df_fleet_raw = fetch_fleet(operator_icaos_tuple)
    df_type_raw = fetch_aircraft_types()
        
    return df_sched_raw, df_hist, df_visits_raw, df_fleet_raw, df_type_raw

# Execute the Cached Function
current_date_str = date.today().isoformat() # Changes every day, invalidating cache at midnight
df_sched_raw, df_hist, df_visits_raw, df_fleet_raw, df_type_raw = get_daily_dashboard_data(tuple(operator_icaos), current_date_str)

# --- 3.5. DASHBOARD FILTERS (CONTROL PANEL) ---
st.markdown("### Dashboard Filters")
col_f1, col_f2, col_f3 = st.columns([2, 2, 1], vertical_alignment="bottom")

available_operators = ["All Operators"] + operator_icaos
available_route_types = ["All Routes"]

if not df_sched_raw.empty:
    base_routes = {str(x).split('-')[0].strip().title() for x in df_sched_raw['route_type'].dropna().unique() if str(x).strip()}
    available_route_types.extend(sorted(list(base_routes)))
else:
    available_route_types.extend(["Passenger", "Cargo"])

with col_f1:
    selected_operator = st.selectbox("Select Operator:", options=available_operators)
with col_f2:
    selected_route = st.selectbox("Select Route Type:", options=available_route_types)
with col_f3:
    st.button("Refresh Data", width="stretch", on_click=refresh_dashboard_cache)

st.markdown("<br>", unsafe_allow_html=True)

# Apply filters to DataFrames
df_sched = df_sched_raw.copy()

if not df_sched.empty:
    if 'dep_iata' in df_sched.columns and 'arr_iata' in df_sched.columns:
        df_sched = df_sched[df_sched['dep_iata'] != df_sched['arr_iata']]

if not df_sched.empty:
    if selected_operator != "All Operators":
        if 'operator_id' in df_sched.columns:
            df_sched = df_sched[df_sched['operator_id'] == selected_operator]
        else:
            st.warning("Please click 'Refresh Data' to update the cache.")
    if selected_route != "All Routes":
        if 'route_type' in df_sched.columns:
            df_sched = df_sched[df_sched['route_type'].astype(str).str.contains(selected_route, case=False, na=False)]

df_visits = df_visits_raw.copy()
if not df_visits.empty:
    if selected_operator != "All Operators":
        if 'operator_icao' in df_visits.columns:
            df_visits = df_visits[df_visits['operator_icao'] == selected_operator]
    if selected_route != "All Routes":
        if not df_sched.empty:
            valid_airports = set(df_sched['departure_airport'].dropna()).union(set(df_sched['arrival_airport'].dropna()))
            df_visits = df_visits[df_visits['airport_icao'].isin(valid_airports)]
        else:
            df_visits = pd.DataFrame()

target_icaos = [selected_operator] if selected_operator != "All Operators" else operator_icaos

# Process Visit Counts 
if not df_visits.empty:
    visit_counts = df_visits.groupby(["airport_icao", "iata", "country"])["flight_count"].sum().reset_index()
    visit_counts.columns = ['icao', 'iata', 'country', 'Flights']
    visit_counts = visit_counts.sort_values('Flights', ascending=False)
else:
    visit_counts = pd.DataFrame(columns=['icao', 'Flights', 'iata', 'country'])

# --- 4. PREPARE MERGED ANALYTICS DATA ---

# Merged big data
df_merged = process_merged_flight_data(df_sched, df_hist, join_type="left")

# Merge fleet and type
if not df_fleet_raw.empty and not df_type_raw.empty:
    df_fleet_with_cat = pd.merge(df_fleet_raw, df_type_raw, on="variant", how='left')
else:
    df_fleet_with_cat = df_fleet_raw.copy()

# Logic for Hub Airport Identification, Multiple Leg Flights, and On-Time Ratio Calculation
hub_airports_str = "--"
ratio_str = "--"
multi_leg_count = 0
multi_leg_list_str = "None"

if not df_sched.empty:
    # 1. Hub Airports (Combined top activity for both departures and arrivals)
    dep_counts = df_sched['dep_iata'].value_counts()
    arr_counts = df_sched['arr_iata'].value_counts()
    total_airport_activity = dep_counts.add(arr_counts, fill_value=0).sort_values(ascending=False)
    if not total_airport_activity.empty:
        max_activity = total_airport_activity.iloc[0]
        # Qualify airports within 85% volume threshold of the leading hub
        hubs = total_airport_activity[total_airport_activity >= (max_activity * 0.85)].index.tolist()
        hub_airports_str = ", ".join(str(h) for h in hubs[:3])

    # 2. Multiple Leg Flights (Same flight number containing > 1 unique route connection)
    unique_flight_segments = df_sched[['flight_number', 'dep_iata', 'arr_iata', 'blocktime_min']].drop_duplicates(subset=['flight_number', 'dep_iata', 'arr_iata'])
    leg_counts = unique_flight_segments.groupby('flight_number').size()
    multi_leg_flights = leg_counts[leg_counts > 1].index.tolist()
    multi_leg_count = len(multi_leg_flights)

    if multi_leg_flights:
        multi_leg_list_str = ", ".join(str(f) for f in multi_leg_flights[:5])
        if len(multi_leg_flights) > 5: 
            multi_leg_list_str += "..."
    else:
        multi_leg_list_str = "None"

if 'Performance_Status' in df_merged.columns and not df_merged.empty:
    # 3. Early/Late Flight Ratio Calculation
    on_time_early = df_merged['Performance_Status'].isin(['Early', 'On Time']).sum()
    delayed_flights = df_merged['Performance_Status'].str.contains('Late', na=False).sum()
    if delayed_flights > 0:
        ratio_str = f"{round(on_time_early / delayed_flights, 1)}x"
    else:
        ratio_str = f"{on_time_early}x" if on_time_early > 0 else "100% On-Time"

# --- 5. MAIN DASHBOARD LAYOUT ---
col_dashboard, col_detail = st.columns([5, 1])

with col_dashboard:
    # ROW 1: OVERVIEW METRICS
    st.markdown("### Airlines Overview")

    if df_sched.empty:
        st.info("No schedule data available yet. Please use the Input Flights page to generate a schedule.")
    else:
        # --- HIGHLIGHT METRICS ---
        with st.container(border=True):
            # 1
            sc1, sc2, sc3, sc4 = st.columns(4)
            # 1.1 
            sc1.metric("Operating Entities", len(target_icaos))
            # 1.2
            if not df_fleet_with_cat.empty:
                fleet_filter = df_fleet_with_cat['operator_icao'].isin(target_icaos)
                if selected_route != "All Routes":
                    fleet_filter &= (df_fleet_with_cat['body_category'].str.upper() == selected_route.upper())

                tracked_aircraft_count = df_fleet_with_cat[fleet_filter]['aircraft_reg'].nunique()
            else:
                tracked_aircraft_count = 0
            sc2.metric("Aircraft Currently Tracked", tracked_aircraft_count)
            # 1.3 
            hub_card_html = f"""
            <div style="display: flex; flex-direction: column; gap: 0px;">
                <div style="font-size: 14px; color: var(--text-color); opacity: 1.0; margin-bottom: 4px;">Hub</div>
                <div style="font-size: 36px; color: var(--text-color); line-height: 1.1; margin-bottom: 10px;">{hub_airports_str}</div>
            </div>
            """
            sc3.markdown(hub_card_html, unsafe_allow_html=True)
            # 1.4
            ratio_card_html = f"""
            <div style="display: flex; flex-direction: column; gap: 0px;">
                <div style="font-size: 14px; color: var(--text-color); opacity: 1.0; margin-bottom: 4px;">Early/Late Ratio</div>
                <div style="font-size: 36px; color: var(--text-color); line-height: 1.1; margin-bottom: 10px;">{ratio_str}</div>
                <div style="font-size: 14px; color: var(--text-color); opacity: 0.6;">On-time flights observed per 1 delayed flight</div>
            </div>
            """
            sc4.markdown(ratio_card_html, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # 2
            m1, m2, m3, m4 = st.columns(4)
            # 2.1.
            total_flights = len(df_sched)
            route_counts = df_sched['route_type'].value_counts()
            
            breakdown_html = ""
            for r_type, count in route_counts.items():
                display_name = str(r_type).title()
                breakdown_html += f'<div style="font-size: 15px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">{count} {display_name}</div>\n                '
            
            flights_card_html = f"""
            <div style="display: flex; flex-direction: column; gap: 0px;">
                <div style="font-size: 14px; color: var(--text-color); opacity: 1.0; margin-bottom: 4px;">Flights</div>
                <div style="font-size: 36px; color: var(--text-color); line-height: 1.1; margin-bottom: 10px;">{total_flights}</div>
                {breakdown_html}
            </div>
            """
            m1.markdown(flights_card_html, unsafe_allow_html=True)

            # 2.2
            short_haul = len(df_sched[df_sched['route_category'].astype(str).str.contains('SHORT HAUL', case=False, na=False)])
            medium_haul = len(df_sched[df_sched['route_category'].astype(str).str.contains('MEDIUM HAUL', case=False, na=False)])
            long_haul = len(df_sched[df_sched['route_category'].astype(str).str.contains('LONG HAUL', case=False, na=False)])

            hauls_card_html = f"""
            <div style="display: flex; flex-direction: column; gap: 0px;">
                <div style="font-size: 14px; color: var(--text-color); opacity: 1.0; margin-bottom: 4px;">Flight Types</div>
                <div style="font-size: 36px; color: var(--text-color); line-height: 1.1; margin-bottom: 10px;">{short_haul + medium_haul + long_haul}</div>
                <div style="font-size: 15px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">{short_haul} Short Haul</div>
                <div style="font-size: 15px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">{medium_haul} Medium Haul</div>
                <div style="font-size: 15px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">{long_haul} Long Haul</div>
            </div>
            """
            m2.markdown(hauls_card_html, unsafe_allow_html=True)

            # 2.3 & 2.4
            valid_times = df_sched[df_sched['blocktime_min'] > 0]
            if not valid_times.empty:
                shortest_flight = valid_times.loc[valid_times['blocktime_min'].idxmin()]
                longest_flight = valid_times.loc[valid_times['blocktime_min'].idxmax()]

                shortest_flight_card_html = f""" 
                <div style="display: flex; flex-direction: column; gap: 0px;"> 
                    <div style="font-size: 14px; color: var(--text-color); opacity: 1.0; margin-bottom: 4px;">Shortest Flight</div> 
                    <div style="font-size: 25px; color: var(--text-color); line-height: 1.1; margin-bottom: 8px;">{shortest_flight['T_Route']}</div> 
                    <div style="font-size: 14px; color: var(--text-color); opacity: 0.7; margin-top: 2px;">{shortest_flight['R_Airport']} | {shortest_flight['flight_number']} - {round(int(shortest_flight['blocktime_min'])/60, 1)} hrs</div>
                </div>
                """

                longest_flight_card_html = f""" 
                <div style="display: flex; flex-direction: column; gap: 0px;"> 
                    <div style="font-size: 14px; color: var(--text-color); opacity: 1.0; margin-bottom: 4px;">Longest Flight</div>
                    <div style="font-size: 25px; color: var(--text-color); line-height: 1.1; margin-bottom: 8px;">{longest_flight['T_Route']}</div>
                    <div style="font-size: 14px; color: var(--text-color); opacity: 0.7; margin-top: 2px;">{longest_flight['R_Airport']} | {longest_flight['flight_number']} - {round(int(longest_flight['blocktime_min'])/60, 1)} hrs</div>  
                </div>
                """

                m3.markdown(shortest_flight_card_html, unsafe_allow_html=True)
                m4.markdown(longest_flight_card_html, unsafe_allow_html=True)
            else:
                m3.metric("Shortest Flight", "--")
                m4.metric("Longest Flight", "--")

            st.markdown("<br>", unsafe_allow_html=True)
            
            # 3
            mx1, mx2, mx3, mx4 = st.columns(4)
            # 3.3
            if 'arr_delay_mins' in df_merged.columns:
                max_delay_mins = int(df_merged['arr_delay_mins'].max())
                mx3.metric("Longest Arrival Delay (mins)", max_delay_mins)    
            # 3.4
            if 'arr_delay_mins' in df_merged.columns:
                delayed_flights = df_merged[df_merged['arr_delay_mins'] > 30]
                avg_delay = int(round(delayed_flights['arr_delay_mins'].mean(), 0))
            else:
                avg_delay = 0 
            mx4.metric("Average Arrival Delay (mins)", avg_delay)

    # AIRPORTS & COUNTRIES
    chart_col5, chart_col6 = st.columns(2)

    # --- WIDGET 1: SERVING AIRPORTS ---
    with chart_col5:
        with st.container(border=True):
            total_airports = visit_counts['icao'].nunique() if not visit_counts.empty else 0

            airport_header = f"""
                <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 10px;">
                    <div style="font-size: 18px; font-weight: 600;">Serving Airports</div>
                    <div style="display: flex; align-items: baseline; gap: 8px;">
                        <span style="font-size: 42px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{total_airports}</span>
                        <span style="font-size: 24px; color: #a1a1aa;">total airports</span>
                    </div>
                </div>
            """
            st.markdown(airport_header, unsafe_allow_html=True)

            if not visit_counts.empty:
                chart_data_airports = visit_counts
                                
                fig_airports = px.bar(
                    chart_data_airports, 
                    x='Flights', 
                    y='iata', 
                    orientation='h', 
                    color_discrete_sequence=['#8b5cf6'],
                    text_auto='.0f' 
                )
                                
                fig_airports.update_traces(textposition='outside', cliponaxis=False)
                fig_airports.update_layout(
                    xaxis=dict(showgrid=False, showticklabels=False, title=None),
                    yaxis={'categoryorder':'total ascending', 'title': None}, 
                    margin=dict(l=20, r=40, t=10, b=0)
                )
                st.plotly_chart(fig_airports, width='stretch')
            else:
                st.info("No airport data available.")

    # --- WIDGET 2: COUNTRIES AND TERRITORIES ---
    with chart_col6:
        with st.container(border=True):
            if not visit_counts.empty:
                country_counts = visit_counts.groupby('country')['Flights'].sum().reset_index()
                country_counts = country_counts.sort_values('Flights', ascending=False)
                total_countries = country_counts['country'].nunique()
            else:
                country_counts = pd.DataFrame()
                total_countries = 0

            country_header = f"""
                <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 15px;">
                    <div style="font-size: 18px; font-weight: 600;">Countries & Territories</div>
                    <div style="display: flex; align-items: baseline; gap: 8px;">
                        <span style="font-size: 42px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{total_countries}</span>
                        <span style="font-size: 24px; color: #a1a1aa;">total</span>
                    </div>
                </div>
            """
            st.markdown(country_header, unsafe_allow_html=True)

            if not country_counts.empty:
                list_html = "<div style='display: flex; flex-direction: column;'>"
                                
                for _, row in country_counts.iterrows():
                    c_name = row['country']
                    c_flights = row['Flights']
                                    
                    list_html += (
                        "<div style='display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid rgba(150, 150, 150, 0.2);'>"
                            f"<div style='font-size: 16px; font-weight: 600; color: var(--text-color);'>{c_name}</div>"
                            f"<div style='font-size: 15px; color: #a1a1aa;'>{c_flights} flights</div>"
                        "</div>"
                    )
                                
                    list_html += "</div>"
                st.markdown(list_html, unsafe_allow_html=True)
            else:
                st.info("No country data available.")
    
    st.markdown("<br>", unsafe_allow_html=True)

    # MULTI-LEG FLIGHTS 
    chart_col11, chart_col12 = st.columns(2)
    
    with chart_col11:
        st.markdown("### Multi-Leg Flight Networks")
    with st.container(border=True):
        if multi_leg_count == 0 or df_sched.empty:
            st.info("No multi-leg flights detected in the current schedule.")
        else:
            multi_leg_data = []

            df_multi_unique = unique_flight_segments[unique_flight_segments['flight_number'].isin(multi_leg_flights)]
            
            for flight_num, group in df_multi_unique.groupby('flight_number', sort=False):
                deps = group['dep_iata'].tolist()
                arrs = group['arr_iata'].tolist()
                
                origins = [ap for ap in deps if ap not in arrs]
                current_stop = origins[0] if origins else deps[0]
                
                route_seq = [current_stop]
                
                unmapped_arrs = arrs.copy()
                unmapped_deps = deps.copy()
                
                while current_stop in unmapped_deps:
                    idx = unmapped_deps.index(current_stop)
                    next_stop = unmapped_arrs[idx]
                    route_seq.append(next_stop)
                    
                    unmapped_deps.pop(idx)
                    unmapped_arrs.pop(idx)
                    current_stop = next_stop

                sequence_str = " ➔ ".join(route_seq)
                total_time = group['blocktime_min'].sum() if 'blocktime_min' in group.columns else 0
                
                multi_leg_data.append({
                    'Flight Number': flight_num,
                    'Sequence': sequence_str,
                    'Legs': len(group),
                    'Total Blocktime (mins)': total_time
                })
            
            df_multi_summary = pd.DataFrame(multi_leg_data).sort_values(by=['Legs', 'Total Blocktime (mins)'], ascending=[False, False])

            # 3. Render the UI
            col_chart, col_table = st.columns([1, 1.5])
            
            with col_chart:
                st.markdown("<div style='margin-top: 14px; font-size: 16px; font-weight: 600;'>Legs per Flight</div>", unsafe_allow_html=True)
                fig_multileg = px.bar(
                    df_multi_summary.head(10), 
                    x='Flight Number', 
                    y='Legs', 
                    color_discrete_sequence=['#f59e0b'], # Amber color to distinguish from other charts
                    text_auto=True
                )
                fig_multileg.update_traces(textposition='outside', cliponaxis=False)
                fig_multileg.update_layout(
                    xaxis_title=None, 
                    yaxis_title=None, 
                    margin=dict(l=0, r=0, t=15, b=0),
                    xaxis={'categoryorder':'total descending', 'type': 'category'}
                )
                st.plotly_chart(fig_multileg, width='stretch')

            with col_table:
                st.markdown("<div style='margin-top: 14px; font-size: 16px; font-weight: 600;'>Routing Sequences</div>", unsafe_allow_html=True)
                st.dataframe(df_multi_summary[['Flight Number', 'Sequence', 'Total Blocktime (mins)']], width='stretch', hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- ANALYTICS VISUALIZATIONS ---
    st.markdown("### Operations Analytics")

    view_option = st.segmented_control(
        "Dashboard Timeframe", 
        options=["Year", "Month", "Week"], 
        default="Week"
    )
    if not view_option: 
        view_option = "Week"

    st.markdown("<br>", unsafe_allow_html=True)

    # ROW 2: FLIGHTS PER & TOP ROUTES
    chart_col1, chart_col2 = st.columns(2)

    # --- WIDGET 3: FLIGHTS PER PERIOD ---
    with chart_col1:
        with st.container(border=True):
            col_label, col_toggle = st.columns([1, 3], vertical_alignment="center")
            with col_label:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Flights per Period</div>", unsafe_allow_html=True)        
            with col_toggle:
                if df_merged.empty:
                    counts = pd.DataFrame()
                elif view_option == "Year":
                    raw_counts = df_merged.dropna(subset=['Year']).drop_duplicates(subset=['flight_number', 'Year'])['Year'].value_counts()
                    counts = pd.DataFrame({'Category': raw_counts.index, 'Flights': raw_counts.values})
                    counts = counts.sort_values('Category')
                elif view_option == "Month":
                    raw_counts = df_merged.dropna(subset=['Month']).drop_duplicates(subset=['flight_number', 'Month'])['Month'].value_counts()
                    counts = pd.DataFrame({'Category': raw_counts.index, 'Flights': raw_counts.values})
                        
                    month_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
                    counts['Category'] = pd.Categorical(counts['Category'], categories=month_order, ordered=True)
                    counts = counts.sort_values('Category')
                else: 
                    df_exploded = df_merged.copy()
                    df_exploded['Day of Week'] = df_exploded['Day of Week'].astype(str).str.split(r',\s*')
                    df_exploded = df_exploded.explode('Day of Week')
                        
                    raw_counts = df_exploded.dropna(subset=['Day of Week']).drop_duplicates(subset=['flight_number', 'Day of Week'])['Day of Week'].value_counts()
                    counts = pd.DataFrame({'Category': raw_counts.index, 'Flights': raw_counts.values})
                                
                    counts['Category'] = counts['Category'].astype(str).str.strip()
                    day_order = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
                    counts = counts[counts['Category'].isin(day_order)]
                    counts['Category'] = pd.Categorical(counts['Category'], categories=day_order, ordered=True)
                    counts = counts.sort_values('Category')

            if counts.empty:
                st.info("No data available.")
            else:
                fig_days = px.bar(counts, x='Category', y='Flights', color_discrete_sequence=['#8b5cf6'])
                fig_days.update_layout(margin=dict(l=0, r=0, t=15, b=0), xaxis_title=None, yaxis_title=None, xaxis_type='category')
                st.plotly_chart(fig_days, width='stretch')

    # --- WIDGET 4: ROUTES VOLUME ---
    with chart_col2:
        with st.container(border=True):
            col_label_rt, col_toggle_rt = st.columns([1.2, 2])
            with col_label_rt:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Routes Volume</div>", unsafe_allow_html=True)
            with col_toggle_rt:
                if df_merged.empty or 'R_Airport' not in df_merged.columns:
                    route_freq = pd.DataFrame(columns=['R_Airport', 'Flights'])
                    time_label = "--"
                else:
                    route_freq = df_merged.groupby('R_Airport')['weekly_freq'].sum().reset_index()

                    if view_option == "Year":
                        yearly_counts = df_merged.groupby(['R_Airport', 'Year']).size().reset_index(name='count')
                        route_freq = yearly_counts.groupby('R_Airport')['count'].mean().reset_index()
                        time_label = "avg flights/year"
                    elif view_option == "Month":
                        monthly_counts = df_merged.groupby(['R_Airport', 'Year', 'Month']).size().reset_index(name='count')
                        route_freq = monthly_counts.groupby('R_Airport')['count'].mean().reset_index()
                        time_label = "avg flights/month"
                    else: 
                        df_merged['Week'] = df_merged['actual_dep'].dt.isocalendar().week
                        weekly_counts = df_merged.groupby(['R_Airport', 'Year', 'Week']).size().reset_index(name='count')
                        route_freq = weekly_counts.groupby('R_Airport')['count'].mean().reset_index()
                        time_label = "avg flights/week"

            if route_freq.empty:
                st.info("No route data available.")
            else:
                route_freq.columns = ['R_Airport', 'Flights']
                route_freq = route_freq.sort_values('Flights', ascending=False)
                route_count = len(route_freq)

                st.markdown(f"<span style='font-size: 13px; font-weight: 600; color: #a1a1aa; text-transform: uppercase;'>{route_count} total routes ({time_label})</span>", unsafe_allow_html=True)
                    
                fig_routes = px.bar(
                    route_freq, 
                    x='Flights', 
                    y='R_Airport', 
                    orientation='h', 
                    color_discrete_sequence=['#8b5cf6'],
                    text_auto='.f'
                )
                fig_routes.update_traces(textposition='outside', cliponaxis=False)
                        
                fig_routes.update_layout(
                    xaxis=dict(showgrid=False, showticklabels=False, title=None), 
                    yaxis={'categoryorder':'total ascending', 'title': None}, 
                    margin=dict(l=20, r=40, t=15, b=0) 
                )
                st.plotly_chart(fig_routes, width='stretch')

    # ROW 3: AIRCRAFT TYPES & OTP
    chart_col3, chart_col4 = st.columns(2)

    # --- WIDGET 5: AIRCRAFT TYPES ---
    with chart_col3:
        with st.container(border=True):
            col_label_ac, col_toggle_ac = st.columns([1.2, 2])
            with col_label_ac:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Aircraft Types</div>", unsafe_allow_html=True)
            with col_toggle_ac:
                if df_merged.empty or 'type' not in df_merged.columns:
                    type_freq = pd.DataFrame()
                    time_label = "--"
                elif view_option == "Year":
                    yearly_counts = df_merged.groupby(['type', 'Year']).size().reset_index(name='count')
                    type_freq = yearly_counts.groupby('type')['count'].mean().reset_index()
                    time_label = "avg flights/year"
                elif view_option== "Month":
                    monthly_counts = df_merged.groupby(['type', 'Year', 'Month']).size().reset_index(name='count')
                    type_freq = monthly_counts.groupby('type')['count'].mean().reset_index()
                    time_label = "avg flights/month"
                else: 
                    weekly_counts = df_merged.groupby(['type', 'Year', 'Week']).size().reset_index(name='count')
                    type_freq = weekly_counts.groupby('type')['count'].mean().reset_index()
                    time_label = "avg flights/week"

            if type_freq.empty:
                st.info("No aircraft type data available.")
            else:
                type_freq.columns = ['Aircraft Type', 'Flights']
                type_freq = type_freq.sort_values('Flights', ascending=False)
                type_count = len(type_freq)

                aircraft_types_html = f"""
                    <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 10px;">
                        <div style="display: flex; align-items: baseline; gap: 8px;">
                            <span style="font-size: 46px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{type_count}</span>
                            <span style="font-size: 28px; color: #a1a1aa;"></span>
                        </div>
                    </div>
                """
                st.markdown(aircraft_types_html, unsafe_allow_html=True)

                fig_aircraft = px.bar(
                    type_freq, 
                    x='Flights', 
                    y='Aircraft Type', 
                    orientation='h', 
                    title="Most Flown Aircraft Types", 
                    color_discrete_sequence=['#3b82f6'],
                    text_auto='.f'
                )
                fig_aircraft.update_traces(textposition='outside', cliponaxis=False)
                fig_aircraft.update_layout(
                    xaxis=dict(showgrid=False, showticklabels=False, title=None),
                    yaxis={'categoryorder':'total ascending'}, 
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig_aircraft, width='stretch')

    # --- WIDGET 6: PERFORMANCE ---
    with chart_col4:
        with st.container(border=True):
            col_label_otp, col_toggle_otp = st.columns([1.2, 2])
            with col_label_otp:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Performance</div>", unsafe_allow_html=True)
            if df_merged.empty or 'arr_delay_mins' not in df_merged.columns:
                st.info("No performance data available.")
            else:
                with col_toggle_otp:
                    if view_option == "Year":
                        divisor = df_merged['Year'].nunique() if 'Year' in df_merged.columns else 1
                        time_label = "avg yearly arrival performance"
                    elif view_option == "Month":
                        divisor = df_merged.groupby(['Year', 'Month']).ngroups if 'Year' in df_merged.columns else 1
                        time_label = "avg monthly arrival performance"
                    else:                             
                        divisor = df_merged.groupby(['Year', 'Week']).ngroups if 'Year' in df_merged.columns else 1
                        time_label = "avg weekly arrival performance"

                # Calculate Delays & Performance
                divisor = max(divisor, 1)
                avg_delay_total = df_merged['arr_delay_mins'].sum(skipna=True) / divisor
                        
                # Convert to absolute hours and minutes
                delayhours = int(abs(avg_delay_total) // 60)
                delaymins = int(abs(avg_delay_total) % 60)

                # Determine if the overall fleet is running late or early
                status_text = "late" if avg_delay_total >= 0 else "early"
                subtitle_text = "average total time lost" if avg_delay_total >= 0 else "average total time gained"

                performance_html = f"""
                    <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 10px;">
                        <div style="display: flex; align-items: baseline; gap: 8px;">
                            <span style="font-size: 46px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{delayhours}h {delaymins}m</span>
                            <span style="font-size: 28px; color: #a1a1aa;">{status_text}</span>
                        </div>
                        <div style="font-size: 15px; color: #a1a1aa; margin-top: -4px;">{subtitle_text} per {view_option.lower()}</div>
                    </div>
                """
                st.markdown(performance_html, unsafe_allow_html=True)

                perf_counts = df_merged[df_merged['Performance_Status'] != 'No Data']['Performance_Status'].value_counts().reset_index()
                perf_counts.columns = ['Status', 'Count']
                        
                if not perf_counts.empty:
                    fig_otp = px.pie(perf_counts, values='Count', names='Status', hole=0.4, color='Status',
                        color_discrete_map={
                            "Early": "#059669",       # Darker emerald green
                            "On Time": "#00CC96",     # Your original light green
                            "15m Late": "#FFD700",    # Yellow
                            "30m Late": "#FFA500",    # Orange
                            "45m+ Late": "#FF4B4B",   # Red
                            "Cancelled": "#4B4B4B",   # Dark Grey
                            "Diverted": "#8A2BE2"     # Purple
                        },
                        category_orders={
                            "Status": ["Early", "On Time", "15m Late", "30m Late", "45m+ Late", "Diverted", "Cancelled"]
                        })
                    fig_otp.update_layout(margin=dict(l=0, r=0, t=10, b=10))
                    st.plotly_chart(fig_otp, width='stretch')

        st.markdown("<br>", unsafe_allow_html=True)

    # --- ROW 4: SCHEDULE TABLE ---
    st.markdown("### Operations Schedule")
    with st.container(border=True):
        processed_flight_rows = []
        for _, row in df_sched.iterrows():
            dep_time_local = convert_utc_to_local_2(row.get("scheduled_departure_time_utc"), get_airport_info(row['departure_airport'], "iana_tz"))
            arr_time_local = convert_utc_to_local_2(row.get("scheduled_arrival_time_utc"), get_airport_info(row['arrival_airport'], "iana_tz"))

            processed_flight_rows.append({
                "Flight": row.get("flight_number", "--"),
                "Day of Week": format_day_of_week(row.get("day_of_week")),
                "From": row.get("dep_iata", "--"),
                "To": row.get("arr_iata", "--"),
                "Time Dep (Local)": dep_time_local,
                "Time Arr (Local)": arr_time_local,
                "Type": row.get("route_type", "--"),
                "Route Category": row.get("route_category", "--"),
                "Variants": ", ".join(dict.fromkeys(filter(None, [row.get("used_variant_1"), row.get("used_variant_2"), row.get("used_variant_3")])))
            })
                        
        st.dataframe(pd.DataFrame(processed_flight_rows), width='stretch', hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- ROW 5: PERFORMANCE DETAIL ---
    st.markdown("### Performance Detail")
    chart_col7, chart_col8 = st.columns(2)

    # --- WIDGET 7: AIRPORT PERFORMANCE (Late Departures) ---
    with chart_col7:
        with st.container(border=True):
            if df_merged.empty or 'dep_delays_mins' not in df_merged.columns:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Airport Performance</div>", unsafe_allow_html=True)
                st.info("No departure delay data available.")
            else:
                # 1. Calculate Departure Performance
                df_dep = df_merged.dropna(subset=['dep_delays_mins', 'dep_iata']).copy()
                df_dep['is_late'] = df_dep['dep_delays_mins'] >= 15
                    
                total_deps = len(df_dep)
                total_late_deps = df_dep['is_late'].sum()
                overall_late_pct = int(round((total_late_deps / total_deps) * 100, 0)) if total_deps > 0 else 0
                    
                # Group by airport to get stats per airport
                ap_perf = df_dep.groupby('dep_iata').agg(
                    total_flights=('is_late', 'count'),
                    late_flights=('is_late', 'sum')
                ).reset_index()
                    
                # Calculate % late and filter to only show airports with at least 1 late flight
                ap_perf['late_pct'] = (ap_perf['late_flights'] / ap_perf['total_flights']) * 100
                ap_perf = ap_perf[ap_perf['late_flights'] > 0]
                # Sort highest % first, then highest volume
                ap_perf = ap_perf.sort_values(by=['late_pct', 'late_flights'], ascending=[False, False])

                # 2. Render Header
                perf_header = f"""
                    <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 20px;">
                        <div style="font-size: 18px; font-weight: 600;">Airport Performance</div>
                        <div style="display: flex; align-items: baseline; gap: 8px;">
                            <span style="font-size: 42px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{overall_late_pct}%</span>
                            <span style="font-size: 24px; color: #a1a1aa;">late departures</span>
                        </div>
                    </div>
                """
                st.markdown(perf_header, unsafe_allow_html=True)
                
                # 3. Render Progress Bar List (Top 5)
                if not ap_perf.empty:
                    html_bars = "<div style='display: flex; flex-direction: column; gap: 16px;'>"
                    for _, row in ap_perf.iterrows():
                        iata = row['dep_iata']
                        pct = int(row['late_pct'])
                        late_cnt = int(row['late_flights'])
                        tot_cnt = int(row['total_flights'])
                            
                        # Custom HTML for the label and red progress bar
                        html_bars += f"""<div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <div style="font-size: 16px; font-weight: 600; color: var(--text-color);">{iata}</div>
                            <div style="font-size: 15px;"><span style="font-weight: 700; color: var(--text-color);">{pct}%</span> <span style="color: #a1a1aa;">({late_cnt}/{tot_cnt})</span></div>
                        </div>
                        <div style="width: 100%; background-color: rgba(150, 150, 150, 0.2); border-radius: 6px; height: 8px; overflow: hidden;">
                            <div style="width: {pct}%; background-color: #FF4B4B; border-radius: 6px; height: 100%;"></div>
                        </div>
                        </div>"""
                    html_bars += "</div>"
                    st.markdown(html_bars, unsafe_allow_html=True)
                else:
                    st.info("No departure delay data available.")

    # --- WIDGET 8: AIRPORT PERFORMANCE (Late Arrival) ---
    with chart_col8:
        with st.container(border=True):
            if df_merged.empty or 'arr_delay_mins' not in df_merged.columns:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Airport Performance</div>", unsafe_allow_html=True)
                st.info("No arrival delay data available.")
            else:
                df_arr = df_merged.dropna(subset=['arr_delay_mins', 'arr_iata']).copy()
                df_arr['is_late'] = df_arr['arr_delay_mins'] >= 15
                    
                total_arrs = len(df_arr)
                total_late_arrs = df_arr['is_late'].sum()
                overall_late_pct_arr = int(round((total_late_arrs / total_arrs) * 100, 0)) if total_arrs > 0 else 0
                    
                # Group by airport to get stats per airport
                ap_perf_arr = df_arr.groupby('arr_iata').agg(
                    total_flights=('is_late', 'count'),
                    late_flights=('is_late', 'sum')
                ).reset_index()
                    
                # Calculate % late and filter to only show airports with at least 1 late flight
                ap_perf_arr['late_pct'] = (ap_perf_arr['late_flights'] / ap_perf_arr['total_flights']) * 100
                ap_perf_arr = ap_perf_arr[ap_perf_arr['late_flights'] > 0]
                # Sort highest % first, then highest volume
                ap_perf_arr = ap_perf_arr.sort_values(by=['late_pct', 'late_flights'], ascending=[False, False])

                # 2. Render Header
                perf_header = f"""
                    <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 20px;">
                        <div style="font-size: 18px; font-weight: 600;">Airport Performance</div>
                        <div style="display: flex; align-items: baseline; gap: 8px;">
                            <span style="font-size: 42px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{overall_late_pct_arr}%</span>
                            <span style="font-size: 24px; color: #a1a1aa;">late arrival</span>
                        </div>
                    </div>
                """
                st.markdown(perf_header, unsafe_allow_html=True)
                    
                # 3. Render Progress Bar List (Top 5)
                if not ap_perf_arr.empty:
                    html_bars = "<div style='display: flex; flex-direction: column; gap: 16px;'>"
                    for _, row in ap_perf_arr.iterrows():
                        iata = row['arr_iata']
                        pct = int(row['late_pct'])
                        late_cnt = int(row['late_flights'])
                        tot_cnt = int(row['total_flights'])
                            
                        # Custom HTML for the label and red progress bar
                        html_bars += f"""<div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <div style="font-size: 16px; font-weight: 600; color: var(--text-color);">{iata}</div>
                            <div style="font-size: 15px;"><span style="font-weight: 700; color: var(--text-color);">{pct}%</span> <span style="color: #a1a1aa;">({late_cnt}/{tot_cnt})</span></div>
                        </div>
                        <div style="width: 100%; background-color: rgba(150, 150, 150, 0.2); border-radius: 6px; height: 8px; overflow: hidden;">
                            <div style="width: {pct}%; background-color: #FF4B4B; border-radius: 6px; height: 100%;"></div>
                        </div>
                        </div>"""
                    html_bars += "</div>"
                    st.markdown(html_bars, unsafe_allow_html=True)
                else:
                    st.info("No departure delay data available.")

    chart_col9, chart_col10 = st.columns(2)
    # --- WIDGET 9: ARRIVAL DELAYS ---
    with chart_col9:
        with st.container(border=True):
            if df_merged.empty or 'arr_delay_mins' not in df_merged.columns:
                st.markdown("<div style='margin-top: 14px; font-size: 18px; font-weight: 600;'>Arrival Delays</div>", unsafe_allow_html=True)
                st.info("No arrival delay data available.")
            else:
                df_arr_delays = df_merged.dropna(subset=['arr_delay_mins', 'flight_number']).copy()
                df_arr_delays = df_arr_delays[df_arr_delays['arr_delay_mins'] > 0]
                total_delayed_flights = len(df_arr_delays)    
                # Sort worst delays to the top
                top_delays = df_arr_delays.sort_values(by='arr_delay_mins', ascending=False)

                # 2. Render Header
                delay_header = f"""
                    <div style="display: flex; flex-direction: column; gap: 0px; margin-bottom: 20px;">
                        <div style="font-size: 18px; font-weight: 600;">Arrival Delays</div>
                        <div style="display: flex; align-items: baseline; gap: 8px;">
                            <span style="font-size: 42px; font-weight: 700; color: var(--text-color); letter-spacing: -1.5px; line-height: 1.1;">{total_delayed_flights}</span>
                            <span style="font-size: 24px; color: #a1a1aa;">total</span>
                        </div>
                    </div>
                """
                st.markdown(delay_header, unsafe_allow_html=True)

                # 3. Render Flight List
                if not top_delays.empty:
                    html_list = "<div style='display: flex; flex-direction: column;'>"
                    for _, row in top_delays.head(20).iterrows():
                        flt_num = row['flight_number']
                        mins_late = int(row['arr_delay_mins'])
                            
                        # Format Hours/Mins
                        d_hrs = mins_late // 60
                        d_mins = mins_late % 60
                        delay_str = f"{d_hrs}h {d_mins}m" if d_hrs > 0 else f"{d_mins}m"
                            
                        # Format Route
                        dep = row['dep_iata'] 
                        arr = row['arr_iata']
                        route_str = f"{dep}-{arr}"
                            
                        # Format Date
                        date_str = "--"
                        if pd.notna(row.get('actual_dep')):
                            date_str = row['actual_dep'].strftime('%b %-d, %Y')
                                
                        # HTML Grid Layout for the row
                        html_list += f"""<div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid rgba(150, 150, 150, 0.2);">
                        <div style="width: 25%; font-size: 15px; font-weight: 600; color: var(--text-color);">{flt_num}</div>
                        <div style="width: 25%; font-size: 15px; font-weight: 600; color: #FF4B4B;">{delay_str}</div>
                        <div style="width: 25%; font-size: 14px; color: #a1a1aa;">{route_str}</div>
                        <div style="width: 25%; font-size: 14px; color: #a1a1aa; text-align: right;">{date_str}</div>
                        </div>"""
                    html_list += "</div>"
                    st.markdown(html_list, unsafe_allow_html=True)
                else:
                    st.info("No arrival delay data available.")

    # --- WIDGET 10: TOTAL TIME LOST FROM DELAYS ---

# --- 5. DETAIL SIDEBAR ---
with col_detail:
    if st.button("View Fleet Details", width='stretch'):
        st.session_state.selected_profile = current_profile
        st.switch_page("pages/fleet_details.py")
