import streamlit as st
from utils import setup_page

supabase = setup_page("Operators List")

# --- HEADER ---
col1, col2, col3 = st.columns([5, 1, 1], vertical_alignment="bottom")
with col1:
    st.title("Operators")

with col2:
    if st.button("Aircraft Type", width='stretch'):
            st.switch_page("pages/aircraft_type.py")

with col3:
    if st.button("Back", width='stretch'):
        st.switch_page("app.py")

st.write("")

# --- FETCH DATA FROM SUPABASE ---
try:
    response = supabase.table("operators").select("name").is_("subsidiary_of", "null").execute()
    saved_profiles = response.data
except Exception as e:
    st.error(f"Error fetching data: {e}")
    saved_profiles = []
    
# --- DYNAMIC PROFILE BUTTONS ---
col_left, col_center, col_right = st.columns([1, 2, 1])

with col_center:
    if len(saved_profiles) == 0:
        st.info("No operator profiles created yet. Click 'Add Profile' below.")
    else:
        # Loop through the database records and build a button for each one
        for row in saved_profiles:
            profile_name = row["name"]
            
            if st.button(f"{profile_name}", width='stretch', key=f"btn_{profile_name}"):
                # Save the exact profile name to session state and navigate
                st.session_state.selected_profile = profile_name
                st.switch_page("pages/dashboard_sub.py")
                
            st.write("")     
st.write("") 
    
# --- ADD PROFILE BUTTON ---
col4, col5, col6 = st.columns([2, 1, 2])
with col5:
    if st.button("Add Profile", width='stretch'):
        # Wipe the edit memory so the dashboard opens clean!
        if "edit_profile_name" in st.session_state:
            del st.session_state["edit_profile_name"]
        st.switch_page("pages/operator_profiles.py")