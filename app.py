import streamlit as st
from utils import setup_page

supabase = setup_page("Aviation Data Visualization & Predictive Scheduling System")

st.title("Homepage")
col1, col2 = st.columns([3, 1])
    
with col1:
    with st.container(border=True):
        st.markdown("""
        ### About

        Welcome to the **Aviation Data Visualization & Predictive Scheduling System**, a high-efficiency schedule modeling and logistical routing platform engineered for airline operators, dispatchers, and aviation analysts. 

        The ultimate objective of this system is to leverage machine learning to automate daily tail assignments, dynamically mapping specific aircraft registrations to complex flight schedules. Unlike static scheduling tools, this platform is designed to "grow" alongside an airline's operations by learning operational nuances, maintenance behaviors, and turnaround patterns through continuous historical analysis and “real” feedback loops.

        ---

        #### Project Roadmap & Current Status

        To ensure robust development, the system is structured into three distinct phases: 
        * **Phase 1:** Interface Development, Data Processing & Advanced Visualization *(Current Phase)*  
        * **Phase 2:** Machine Learning Model Training & Predictive Engineering  
        * **Phase 3:** Automated Daily Schedule Suggestions & Corrections  

        As training production-ready ML models requires extensive historical benchmarks, therefore, during the wait, a dedicated operational branch has been introduced in the interim. This branch allows users to seamlessly ingest, structure, and contrast operational metrics across different selected airliners.

        ---

        #### Core Capabilities & Data Architecture

        The platform is engineered to ingest and model 50,000+ historical flight records, transforming raw data from the [Flightradar24 API ("Flight Summary Light")](https://fr24api.flightradar24.com/docs/endpoints/flight-summary) into actionable operational insights. The system maps and validates the following core telemetry and schedule fields for every flight leg:
                    
        * `fr24_id`: Unique identifier assigned by Flightradar24 to each flight leg
        * `flight`: Commercial flight number, interpreted from the callsign.
        * `callsign`: Up to 8 characters as sent from the aircraft’s transponder.
        * `operating_as`: ICAO code for the carrier operating the flight.
        * `painted_as`: ICAO code for the carrier marketing the flight.
        * `type`: ICAO aircraft type designator.
        * `reg`: Aircraft registration number (tail number).
        * `orig_icao`: ICAO code for the origin airport.
        * `datetime_takeoff`: Datetime of takeoff in UTC (YYYY-MM-DDTHH:MM:SS).
        * `dest_icao`: ICAO code for the intended destination airport.
        * `dest_icao_actual`: ICAO code for the actual destination airport (if diverted).
        * `datetime_landed`: Datetime of landing in UTC (YYYY-MM-DDTHH:MM:SS).
        * `hex`: 24-bit Mode-S identifier in hexadecimal format.
        * `first_seen`: Datetime when the aircraft was first detected for this flight leg (UTC).
        * `last_seen`: Datetime when the aircraft was last detected for this flight leg (UTC).
        * `flight_ended`: Boolean flag indicating if the flight is historical (`true`) or currently tracked (`false`).

        ---

        #### How to Interact

        1. **Project Overview:** This dashboard provides a macro-level comparative view across input carriers. Use this section to dynamically filter and compare multiple airline operators side-by-side, evaluating differences in turnaround rules and fleet utilization constraints within a single unified view to quickly identify operational bottlenecks.

        2. **Admin:** This is where operator profiles are securely configured and managed. Serving as the initial phase of the data pipeline, this section handles user-input extraction to establish baseline parameters for each carrier. You can view operation data in granular detail or onboard new operators, and the data will be automatically integrated to update the analytics across the entire platform.
        """)
    st.markdown("<br><br>", unsafe_allow_html=True)
            
with col2:
    if st.button("Project Overview", width='stretch'):
        st.switch_page("pages/dashboard_overall.py")
    st.write("") 
    if st.button("Admin", width='stretch'):
        st.switch_page("pages/operators.py")
    st.write("")