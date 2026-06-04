import streamlit as st
from utils import setup_page

supabase = setup_page("Aviation Data Visualization & Predictive Scheduling System")

st.title("Home")
col1, col2 = st.columns([3, 1])
    
with col1:
    with st.container(border=True):
       st.markdown("""
            ### About

            Welcome to the **Aviation Data Visualization & Predictive Scheduling System**—a high-efficiency schedule modeling and logistical routing platform built for airline operators, schedulers, and aviation analysts. 

            By architecting a **4-phase data pipeline**: encompassing user-input extraction, route grouping, aircraft family prediction, and registration assignment, this platform is engineered to model and structure **50,000+ expected historical flight records**. It translates complex data sets into actionable operational insights, allowing for deep comparative analytics and proactive fleet management.

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