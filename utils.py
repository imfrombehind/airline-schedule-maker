import streamlit as st
from supabase import create_client, Client
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
import urllib.parse

@st.cache_resource(ttl=600)
def init_connection_1() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

@st.cache_resource(ttl=600)
def init_connection_2():
    user = st.secrets["user"]
    password = st.secrets["password"]
    host = st.secrets["host"]
    port = st.secrets["port"]
    dbname = st.secrets["dbname"]

    encoded_password = urllib.parse.quote_plus(password)
    db_url = f"postgresql+psycopg2://{user}:{encoded_password}@{host}:{port}/{dbname}?sslmode=require"

    return create_engine(db_url, poolclass=NullPool)

def inject_global_css():
    st.markdown(
        """
        <style>
        /* Force all text inputs to visually capitalize */
        input[type="text"] {
            text-transform: uppercase;
        }
        
        /* FORCE FULL SCREEN WIDTH */
        .block-container {
            max-width: 98vw !important; /* Forces the app to use 98% of your screen */
            padding-top: 2rem !important; 
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

def setup_page(title, layout="wide"):
    st.set_page_config(page_title=title, layout=layout)
    inject_global_css()
    return init_connection_1()
