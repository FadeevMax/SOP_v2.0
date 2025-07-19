import os
import streamlit as st

# === Directories ===
CACHE_DIR = "cache"
STATE_DIR = "user_data"
IMAGE_DIR = os.path.join(CACHE_DIR, "images")

# === File Paths ===
PDF_CACHE_PATH = os.path.join(CACHE_DIR, "cached_sop.pdf")
DOCX_LOCAL_PATH = os.path.join(CACHE_DIR, "sop.docx")
GDOC_STATE_PATH = os.path.join(CACHE_DIR, "gdoc_state.json")
ENRICHED_CHUNKS_PATH = os.path.join(CACHE_DIR, "enriched_chunks.json")
IMAGE_MAP_PATH = os.path.join(CACHE_DIR, "image_map.json")

# === GitHub ===
GITHUB_REPO = "FadeevMax/SOP_sales_chatbot"
GITHUB_PDF_NAME = "Live_GTI_SOP.pdf"
GITHUB_TOKEN = st.secrets["GitHub_API"]

# === Google Docs ===
GOOGLE_DOC_NAME = "GTI Data Base and SOP"
