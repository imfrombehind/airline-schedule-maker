import streamlit as st
import pandas as pd
from utils import setup_page

supabase = setup_page("Add Aircraft Types")

# --- NAVIGATION ---
col1, col2 = st.columns([5, 1], vertical_alignment="bottom")
with col1:
    st.title("Aircraft Type") 
    st.write("Populate the aircraft reference table here.")

with col2:
    if st.button("Back", width="stretch"):
        st.switch_page("pages/operators.py")

st.write("")
st.write("")

# --- DELETE LOGIC ---
def delete_aircraft(variant):
    """Deletes the row from Supabase and forces a page refresh."""
    try:
        supabase.table("aircraft_type").delete().eq("variant", variant).execute()
        st.rerun() 
    except Exception as e:
        st.error(f"Error deleting {variant}: {e}")

# --- FETCH EXISTING MANUFACTURERS ---
default_mfrs = ["AIRBUS", "ATR", "BOEING", "BOMBARDIER", "DE HAVILLAND", "EMBRAER", "MITSUBISHI", "LOCKHEED MARTIN"]

try:
    mfr_res = supabase.table("aircraft_type").select("manufacturer").execute()
    
    if mfr_res.data:
        db_mfrs = [row["manufacturer"] for row in mfr_res.data if row["manufacturer"]]
        dynamic_mfrs = sorted(list(set(default_mfrs + db_mfrs)))
    else:
        dynamic_mfrs = sorted(default_mfrs)
        
except Exception as e:
    st.error(f"Error fetching manufacturers: {e}")
    dynamic_mfrs = sorted(default_mfrs)

# --- INPUT SECTION ---
with st.form("aircraft_type_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        variant = st.text_input("Variant").upper()
        type_code = st.text_input("Aircraft Type Code").upper()
        body_type = st.selectbox("Body Type", ["NARROW BODY", "WIDE BODY"])
    with col2:
        # THE HYBRID INPUT
        selected_mfr = st.selectbox("Manufacturer", options=dynamic_mfrs)
        body_category = st.selectbox("Body Category", ["PASSENGER", "CARGO", "MILITARY"])

        range_category = st.selectbox("Range Category", ["SHORT HAUL", "MEDIUM HAUL", "LONG HAUL"])

    submit = st.form_submit_button("Add Aircraft", width='stretch')

# --- DATABASE INSERTION LOGIC ---
if submit:
    if type_code:
        try:
            aircraft_data = {
                "variant": variant,
                "type_code": type_code,
                "manufacturer": selected_mfr,
                "body_type": body_type,
                "range_category": range_category,
                "body_category": body_category
            }
            supabase.table("aircraft_type").insert(aircraft_data).execute()
            st.success(f"Variant {variant} saved to reference table.")
        except Exception as e:
            st.error(f"Database Error: {e}")
    else:
        st.warning("Please enter a variant.")

st.markdown("---")
st.markdown("### Saved Aircraft Types")

# --- FETCH AND DISPLAY EXISTING DATA (CUSTOM GRID) ---
try:
    response = supabase.table("aircraft_type").select("*").execute()
    
    if len(response.data) > 0:
        sorted_data = sorted(response.data, key=lambda x: x["variant"])
        h_col = [2, 2, 1.5, 1.5, 2, 2, 1]
        
        hc1, hc2, hc3, hc4, hc5, hc6, hc7 = st.columns(h_col)
        hc1.markdown("**Variant**")
        hc2.markdown("**Manufacturer**")
        hc3.markdown("**Type Code**")
        hc4.markdown("**Body Type**")
        hc5.markdown("**Range Category**")
        hc6.markdown("**Body Category**")
        hc7.markdown("") 
        
        st.markdown("<hr style='margin-top: 0; margin-bottom: 1rem;'>", unsafe_allow_html=True)

        for row in sorted_data:
            c1, c2, c3, c4, c5, c6, c7 = st.columns(h_col, vertical_alignment="center")
            c1.write(row["variant"])
            c2.write(row["manufacturer"])
            c3.write(row["type_code"])
            c4.write(row["body_type"])
            c5.write(row["range_category"])
            c6.write(row["body_category"])
            
            with c7:
                with st.popover("Remove", width='stretch'):
                    st.write(f"Delete **{row['variant']}**?")

                    entered_pin = st.text_input("Enter PIN", type="password", key=f"pin_{row['variant']}")

                    if st.button("Confirm", key=f"conf_{row['variant']}", width='stretch'):
                        if entered_pin == st.secrets["ADMIN_PIN"]:
                            delete_aircraft(row["variant"])
                        else:
                            st.error("Incorrect PIN")
    else:
        st.info("No aircraft types have been added yet.")
        
except Exception as e:
    st.error(f"Error fetching data: {e}")