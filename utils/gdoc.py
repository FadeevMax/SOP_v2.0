import streamlit as st
from openai import OpenAI
import time
import os
import uuid
from datetime import datetime, timedelta
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
from utils.config import GDOC_STATE_PATH, GOOGLE_DOC_NAME, CACHE_DIR, PDF_CACHE_PATH, DOCX_LOCAL_PATH, IMAGE_DIR, IMAGE_MAP_PATH, ENRICHED_CHUNKS_PATH, GITHUB_REPO, GITHUB_TOKEN
from utils.chunking import extract_images_and_labels_from_docx
from utils.github import update_pdf_on_github, update_docx_on_github, update_json_on_github, upload_file_to_github
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

def extract_images_and_labels_from_docx(docx_path, image_output_dir, mapping_output_path, debug=False):
    # ... (image extraction logic unchanged) ...
    # Save mapping
    if debug:
        print("Final image_map:", image_map)
    return image_map

def generate_enriched_chunks(docx_path, image_map):
    """
    Split DOCX content into semantic chunks and include nearby images.
    """
    from docx import Document
    import re
    doc = Document(docx_path)
    chunks = []
    current_text, current_images = "", []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # If this paragraph is an image caption, attach the corresponding image
        label = extract_label(text)
        if label and label in image_map:
            current_images.append(image_map[label])
            # Optionally include caption text in the chunk text
            current_text += text + "\n"
            continue
        # Start a new chunk at major section breaks (e.g., headings) or if length limit exceeded
        if re.match(r'^[A-Z].{3,}:$', text) or len(current_text) + len(text) > 1000:
            if current_text:
                chunks.append({"text": current_text.strip(), "images": current_images})
            current_text, current_images = "", []
        # Add this paragraph to the current chunk
        current_text += text + "\n"
    if current_text:
        chunks.append({"text": current_text.strip(), "images": current_images})
    return chunks

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

    image_map = extract_images_and_labels_from_docx(DOCX_LOCAL_PATH, IMAGE_DIR, IMAGE_MAP_PATH)
    enriched_chunks = generate_enriched_chunks(DOCX_LOCAL_PATH, image_map)
    # Save and upload enriched_chunks.json to GitHub
    with open(ENRICHED_CHUNKS_PATH, "w") as f:
        json.dump(enriched_chunks, f, indent=2)
    upload_file_to_github(local_path=ENRICHED_CHUNKS_PATH, github_path="enriched_chunks.json",
                           commit_message="Update enriched chunks")
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
    # Upload enriched_chunks.json if it exists
    if os.path.exists(ENRICHED_CHUNKS_PATH):
        upload_file_to_github(
            local_path=ENRICHED_CHUNKS_PATH,
            github_path="enriched_chunks.json",
            commit_message="Update enriched chunks"
        )
    else:
        st.warning(f"enriched_chunks.json not found at {ENRICHED_CHUNKS_PATH}, skipping upload.")

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
