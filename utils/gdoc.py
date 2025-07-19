import streamlit as st
from openai import OpenAI
import time
import os
import uuid
from datetime import datetime
import json
from streamlit_local_storage import LocalStorage
import difflib
# Imports for Google Docs API
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import io # Needed for handling the in-memory file download
import requests
import base64
import unicodedata
from utils.config import GDOC_STATE_PATH, GOOGLE_DOC_NAME
def download_gdoc_as_docx(doc_id, creds, out_path):
   drive_service = build('drive', 'v3', credentials=creds)
   request = drive_service.files().export_media(fileId=doc_id, mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
   os.makedirs(os.path.dirname(out_path), exist_ok=True)
   with open(out_path, "wb") as f:
     f.write(request.execute())
   return True

def download_gdoc_as_pdf(doc_id, creds, out_path):
    drive_service = build('drive', 'v3', credentials=creds)
    request = drive_service.files().export_media(fileId=doc_id, mimeType='application/pdf')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(request.execute())
    return True

def get_gdoc_last_modified(creds, doc_name):
    drive_service = build('drive', 'v3', credentials=creds)
    query = f"name='{doc_name}' and mimeType='application/vnd.google-apps.document'"
    results = drive_service.files().list(q=query, fields="files(id, modifiedTime)").execute()
    files = results.get('files', [])
    if not files:
        return None, None
    doc_id = files[0]['id']
    modified_time = files[0]['modifiedTime']
    return doc_id, modified_time

def get_live_sop_pdf_path(doc_name: str) -> str:
    """
    Checks for a fresh cached PDF. If it's stale or missing, it downloads
    the live Google Doc as a PDF and saves it to the cache.
    Returns the file path to the fresh PDF.
    """
    try:
        st.info("Checking for SOP updates from Google Docs...")

        # Create cache directory if it doesn't exist
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

        scopes = ['https://www.googleapis.com/auth/drive.readonly']
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        drive_service = build('drive', 'v3', credentials=creds)

        query = f"name='{doc_name}' and mimeType='application/vnd.google-apps.document'"
        response = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = response.get('files', [])

        if not files:
            st.error(f"No Google Doc found with the name: '{doc_name}'.")
            return None

        doc_id = files[0]['id']

        # Export the document as PDF
        request = drive_service.files().export_media(fileId=doc_id, mimeType='application/pdf')

        # Download the file content into an in-memory buffer
        fh = io.BytesIO()
        downloader = io.BytesIO(request.execute())

        # Define the path for the cached file
        cached_file_path = os.path.join(CACHE_DIR, "cached_sop.pdf")

        # Write the downloaded content to the cached file
        with open(cached_file_path, "wb") as f:
            f.write(downloader.getbuffer())

        st.success(f"✅ SOP updated successfully from Google Docs!")
        return cached_file_path

    except Exception as e:
        st.error(f"❌ Failed to fetch and cache Google Doc: {e}")
        return None


def get_last_gdoc_synced_time():
    if os.path.exists(GDOC_STATE_PATH):
        with open(GDOC_STATE_PATH, "r") as f:
            state = json.load(f)
            return state.get("last_synced_modified_time")
    return None

def set_last_gdoc_synced_time(modified_time):
    with open(GDOC_STATE_PATH, "w") as f:
        json.dump({"last_synced_modified_time": modified_time}, f)

def sync_gdoc_to_github(force=False):
    # Only check if a day has passed or force=True
    last_synced = get_last_gdoc_synced_time()
    now = datetime.utcnow()
    last_checked_dt = datetime.fromisoformat(last_synced) if last_synced else None

    # Google API Auth
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    doc_id, modified_time = get_gdoc_last_modified(creds, GOOGLE_DOC_NAME)
    if not doc_id or not modified_time:
        st.warning("Google Doc not found or can't fetch modified time.")
        return False

    # Only update if new or forced or more than 1 day has passed
    need_update = (
        force or 
        not last_synced or 
        (now - last_checked_dt > timedelta(days=1)) or
        (modified_time != last_synced)
    )
    if not need_update:
        st.info("No update needed. Using existing GitHub PDF.")
        return True

    # Download latest Google Doc as PDF and DOCX
    pdf_success = download_gdoc_as_pdf(doc_id, creds, PDF_CACHE_PATH)
    docx_success = download_gdoc_as_docx(doc_id, creds, DOCX_LOCAL_PATH)

    if not (pdf_success and docx_success):
       st.error("Failed to download Google Doc as PDF or DOCX.")
       return False

    # Extract labeled images from DOCX
    extract_images_and_labels_from_docx(DOCX_LOCAL_PATH, IMAGE_DIR, IMAGE_MAP_PATH, debug=True)

    # Update map.json on GitHub
    success = update_json_on_github(
       IMAGE_MAP_PATH,
       "map.json",
       "Update map.json from SOP DOCX",
       GITHUB_REPO,
       GITHUB_TOKEN
   )
    if not success:
       st.error("❌ Failed to update map.json on GitHub!")

    # Upload images to GitHub
    for file in os.listdir(IMAGE_DIR):
       local_path = os.path.join(IMAGE_DIR, file)
       github_path = f"images/{file}"
       upload_file_to_github(
          local_path,
          github_path,
          f"Update {file} from SOP DOCX"
          )

    # Upload PDF and DOCX to GitHub
    pdf_uploaded = update_pdf_on_github(PDF_CACHE_PATH)
    docx_uploaded = update_docx_on_github(DOCX_LOCAL_PATH)
    upload_file_to_github(
    local_path=ENRICHED_CHUNKS_PATH,
    github_path="enriched_chunks.json",
    commit_message="Update enriched chunks"
)

    if pdf_uploaded and docx_uploaded:
        st.success("PDF and DOCX updated on GitHub with the latest from Google Doc!")
        set_last_gdoc_synced_time(modified_time)
        return True
    elif pdf_uploaded:
        st.error("PDF uploaded, but failed to update DOCX on GitHub.")
        return False
    elif docx_uploaded:
        st.error("DOCX uploaded, but failed to update PDF on GitHub.")
        return False
    else:
        st.error("Failed to update both PDF and DOCX on GitHub.")
        return False
