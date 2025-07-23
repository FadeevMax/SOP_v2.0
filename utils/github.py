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
from utils.config import (
    CACHE_DIR,
    PDF_CACHE_PATH,
    GDOC_STATE_PATH,
    GITHUB_PDF_NAME,
    GITHUB_REPO,
    GITHUB_TOKEN,
    GOOGLE_DOC_NAME,
    STATE_DIR,
    DOCX_LOCAL_PATH,
    IMAGE_DIR,
    IMAGE_MAP_PATH,
    ENRICHED_CHUNKS_PATH,
)

def upload_file_to_github(local_path, github_path, commit_message):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{github_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    # Get SHA for overwrite
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    # Encode file
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    data = {
        "message": commit_message,
        "content": content,
        "sha": sha
    }
    resp = requests.put(url, headers=headers, json=data)
    return resp.status_code in [200, 201]

def update_docx_on_github(local_docx_path):
    docx_name = "Live_GTI_SOP.docx"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{docx_name}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    # Get SHA for overwrite
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    # Encode file
    with open(local_docx_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    data = {
        "message": "Update SOP DOCX from Google Doc",
        "content": content,
        "sha": sha
    }
    resp = requests.put(url, headers=headers, json=data)
    return resp.status_code in [200, 201]

def update_pdf_on_github(local_pdf_path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PDF_NAME}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    # Get SHA for overwrite
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    # Encode file
    with open(local_pdf_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    data = {
        "message": "Update SOP PDF from Google Doc",
        "content": content,
        "sha": sha
    }
    resp = requests.put(url, headers=headers, json=data)
    return resp.status_code in [200, 201]

