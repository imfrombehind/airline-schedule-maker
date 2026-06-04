import time
import streamlit as st
import pycountry
from utils import setup_page
from api_flight_handler import run_historical_ingestion

supabase = setup_page("Add/Edit Operators")

# --- DETERMINE MODE (CREATE OR EDIT) ---
is_edit_mode = "edit_profile_name" in st.session_state
current_profile = st.session_state.get("edit_profile_name", "")

# --- DELETE CALLBACKS ---
def delete_subsidiary(icao):
    try:
        supabase.table("operators").delete().eq("icao_designator", icao).execute()
        st.rerun()
    except Exception as e:
        st.error(f"Error deleting subsidiary: {e}")

def delete_entire_profile(icao):
    try:
        supabase.table("operators").delete().eq("subsidiary_of", icao).execute()
        supabase.table("operators").delete().eq("icao_designator", icao).execute()

        del st.session_state["edit_profile_name"]
        st.switch_page("pages/operators.py")
    except Exception as e:
        st.error(f"Cannot delete profile. Error: {e}")

# --- FETCH DATA IF IN EDIT MODE ---
primary_data = {"icao_designator": "", "name": "", "iata_designator": "", "country": ""}
existing_subs = []

if is_edit_mode:
    try:
        prim_res = supabase.table("operators").select("*").eq("name", current_profile).execute()
        if prim_res.data:
            primary_data = prim_res.data[0]
            
            sub_res = supabase.table("operators").select("*").eq("subsidiary_of", primary_data["icao_designator"]).execute()
            existing_subs = sub_res.data
    except Exception as e:
        st.error(f"Error fetching existing profile: {e}")

# --- NAVIGATION & TITLE ---
col1, col2, col3 = st.columns([5, 1.5, 1], vertical_alignment="bottom")
with col1:
    st.title(f"Edit {current_profile}'s profile" if is_edit_mode else "Add Profile")

with col2:
    if is_edit_mode:
        if st.button("Resume / Sync Flight Data", width='stretch', type="secondary"):
            operator_icaos = [primary_data["icao_designator"]]
            for sub in existing_subs:
                operator_icaos.append(sub["icao_designator"])
                
            with st.status(f"Synchronizing data for {current_profile}...", expanded=True) as status:
                success, result = run_historical_ingestion(operator_icaos, days_back=7)
                
                if success and result > 0:
                    st.success(f"Successfully synced {result} new flights!")
                    time.sleep(2)
                    st.rerun()
                elif success and result == 0:
                    st.info("Database is already up to date. No new flights found.")
                else:
                    st.error("Failed to synchronize flights. Please try again.")

with col3:
    if st.button("Back", width='stretch'):
        if "edit_profile_name" in st.session_state:
            del st.session_state["edit_profile_name"]
        st.switch_page("pages/operators.py")

st.markdown("""
        1. When a new operator profile is created, the system will automatically attempt to backfill the database with the past 7 days of flight data for that carrier. This ensures that all analytics and visualizations across the platform are immediately populated with relevant data for the new profile.
        2. If the operator already exists and you are in edit mode, you can click the "Resume / Sync Flight Data" button to fetch any new flights that have occurred since the last update. This allows you to keep the database current without having to re-enter all the profile information.       
        """)
st.markdown("---")

# --- STATE MANAGEMENT FOR NEW SUBSIDIARIES ---
if "subsidiary_rows" not in st.session_state:
    st.session_state.subsidiary_rows = []
if "next_sub_id" not in st.session_state:
    st.session_state.next_sub_id = 0

def add_subsidiary_row():
    st.session_state.subsidiary_rows.append(st.session_state.next_sub_id)
    st.session_state.next_sub_id += 1

def remove_subsidiary_row(row_id):
    st.session_state.subsidiary_rows.remove(row_id)

# --- MAIN OPERATOR ROW ---
st.markdown("##### Primary Operator")
col1, col2, col3, col4 = st.columns(4, vertical_alignment="bottom")

with col1:
    name = st.text_input("Operator", value=primary_data["name"], key="main_name").upper()
with col2:
    icao = st.text_input("ICAO Designator (3-letter code)", value=primary_data["icao_designator"], key="main_icao", disabled=is_edit_mode).upper()
with col3:
    iata = st.text_input("IATA Designator (2-letter code)", value=primary_data["iata_designator"], key="main_iata").upper()
with col4:
    country_list = sorted([country.name for country in pycountry.countries])
    existing_country = primary_data.get("country", "")
    try:
        default_idx = country_list.index(existing_country) if existing_country else 0
    except ValueError:
        default_idx = 0
    country = st.selectbox("Base Country", options=country_list, index=default_idx, key="base_country")

# --- EXISTING SUBSIDIARIES (EDIT MODE ONLY) ---
if is_edit_mode and existing_subs:
    st.markdown("---")
    st.markdown("##### Existing Subsidiaries")
    for sub in existing_subs:
        sc1, sc2, sc3, sc4, sc5, sc6 = st.columns([2, 2, 2, 2, 2, 1], vertical_alignment="center")
        sc1.write(sub["name"])
        sc2.write(f"Subs. of: {sub['subsidiary_of']}")
        sc3.write(sub["icao_designator"])
        sc4.write(sub["iata_designator"])
        sc5.write(sub["country"])
        with sc6:
            with st.popover("Remove", width='stretch'):
                st.write(f"Delete **{sub['icao_designator']}**?")
                entered_sub_pin = st.text_input("Enter Admin PIN", type="password", key=f"del_sub_pin_{sub['icao_designator']}")
                
                if st.button("Confirm", key=f"conf_del_sub_{sub['icao_designator']}", type="primary", width='stretch'):
                    if entered_sub_pin == st.secrets["ADMIN_PIN"]:
                        delete_subsidiary(sub["icao_designator"])
                    else:
                        st.error("Incorrect PIN")

# --- DYNAMIC SUBSIDIARY ROWS (FOR ADDING NEW ONES) ---
if len(st.session_state.subsidiary_rows) > 0:
    st.markdown("---")
    st.markdown("##### Add New Subsidiaries")

    sub_layout = [3, 3, 3, 3, 3, 2]
    
    for sub_id in st.session_state.subsidiary_rows:
        s_col1, s_col2, s_col3, s_col4, s_col5, s_col6 = st.columns(sub_layout, vertical_alignment="bottom")
        
        with s_col1:
            st.text_input("Input Operator's name", key=f"sub_name_{sub_id}").upper()
        with s_col2:
            st.text_input("Is a subsidiary of:", value=icao, disabled=True, key=f"sub_sub_of_{sub_id}")
        with s_col3:
            st.text_input("Input ICAO Designator (3-letter code)", key=f"sub_icao_{sub_id}").upper()
        with s_col4:
            st.text_input("Input IATA Designator (2-letter code)", key=f"sub_iata_{sub_id}").upper()
        with s_col5:
            st.selectbox("Base Country", options=country_list, index=default_idx, key=f"sub_country_{sub_id}")
        with s_col6:
            st.button("Remove", key=f"remove_btn_{sub_id}", on_click=remove_subsidiary_row, args=(sub_id,), width='stretch')

st.markdown("<br><br>", unsafe_allow_html=True)

# --- BUTTONS ---
spacer_left, btn_col1, btn_col2, spacer_right = st.columns([1, 1.5, 1.5, 1])

with btn_col1:
    st.button("Add subsidiary", width='stretch', on_click=add_subsidiary_row)
        
with btn_col2:
    if st.button("Submit", width='stretch'):
        if name and icao:
            op_payload = {
                "icao_designator": icao,
                "name": name,
                "iata_designator": iata,
                "country": country
            }
                
            # --- EDIT MODE BEHAVIOR ---
            if is_edit_mode:
                try:
                    supabase.table("operators").update(op_payload).eq("icao_designator", icao).execute()

                    if len(st.session_state.subsidiary_rows) > 0:
                        for sub_id in st.session_state.subsidiary_rows:
                            sub_data = {
                                "icao_designator": str(st.session_state[f"sub_icao_{sub_id}"]).upper(),
                                "name": str(st.session_state[f"sub_name_{sub_id}"]).upper(),
                                "subsidiary_of": icao, 
                                "is_subsidiary": True,
                                "iata_designator": str(st.session_state[f"sub_iata_{sub_id}"]).upper(),
                                "country": str(st.session_state[f"sub_country_{sub_id}"])
                            }
                            supabase.table("operators").insert(sub_data).execute()

                    st.success(f"Profile for {name} permanently updated.")
                    st.session_state.subsidiary_rows = []
                    time.sleep(1.5)
                    st.switch_page("pages/operators.py")
                except Exception as e:
                    st.error(f"Database Error: {e}")
                
            # --- CREATE MODE BEHAVIOR (WITH ROLLBACK) ---
            else:
                operator_icaos = [icao]
                subsidiary_payloads = []

                # Gather subsidiary data BEFORE clearing the UI state
                if len(st.session_state.subsidiary_rows) > 0:
                    for sub_id in st.session_state.subsidiary_rows:
                        sub_icao = str(st.session_state[f"sub_icao_{sub_id}"]).upper()
                        operator_icaos.append(sub_icao)
                        subsidiary_payloads.append({
                            "icao_designator": sub_icao,
                            "name": str(st.session_state[f"sub_name_{sub_id}"]).upper(),
                            "subsidiary_of": icao, 
                            "is_subsidiary": True,
                            "iata_designator": str(st.session_state[f"sub_iata_{sub_id}"]).upper(),
                            "country": str(st.session_state[f"sub_country_{sub_id}"])
                        })

                with st.status(f"Validating {icao} and fetching 7-day history...", expanded=True) as status:
                    try:
                        # STEP A: Insert Database Records (Required so API flights have valid foreign keys)
                        status.write("Creating temporary database relations...")
                        supabase.table("operators").insert(op_payload).execute()
                        if subsidiary_payloads:
                            supabase.table("operators").insert(subsidiary_payloads).execute()

                        # STEP B: Run the API Flight Ingestion
                        success, result = run_historical_ingestion(operator_icaos, days_back=7)

                        # STEP C: Evaluate Results
                        if success and isinstance(result, int) and result > 0:
                            # ALL GOOD! Keep the records.
                            status.update(label=f"Success! {result} historical flights ingested.", state="complete", expanded=False)
                            st.success(f"Profile for {name} permanently saved.")
                            st.session_state.subsidiary_rows = [] 
                            time.sleep(1.5) 
                            st.session_state.selected_profile = name
                            st.switch_page("pages/flight_input_handler.py")
                                
                        else:
                            # FAILED! Run the Database Rollback
                            status.update(label=f"Ingestion Failed: {result if not success else '0 flights found'}.", state="error", expanded=True)
                            st.error("Profile creation aborted. Rolling back database changes...")
                                
                            # Delete the records we just inserted to keep the database clean
                            if subsidiary_payloads:
                                supabase.table("operators").delete().eq("subsidiary_of", icao).execute()
                            supabase.table("operators").delete().eq("icao_designator", icao).execute()
                            st.stop()

                    except Exception as e:
                    # EMERGENCY ROLLBACK (In case the database crashes halfway through)
                        try:
                            supabase.table("operators").delete().eq("subsidiary_of", icao).execute()
                            supabase.table("operators").delete().eq("icao_designator", icao).execute()
                        except: pass
                            
                        status.update(label=f"System Error: {e}", state="error", expanded=True)
                        st.stop()
        else:
            st.warning("Please enter a primary operator's ICAO and name.")

# --- DANGER ZONE ---
if is_edit_mode:
    with st.popover("Delete Entire Profile", width='stretch'):
        st.write(f"Are you absolutely sure you want to delete **{current_profile}** and all its subsidiaries?")
        entered_pin = st.text_input("Enter Admin PIN to confirm", type="password", key="del_profile_pin")
        
        if st.button("Confirm Deletion", width='stretch', type="primary"):
            if entered_pin == st.secrets["ADMIN_PIN"]:
                delete_entire_profile(primary_data["icao_designator"])
            else:
                st.error("Incorrect PIN")