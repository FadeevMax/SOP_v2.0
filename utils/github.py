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
def update_json_on_github(local_json_path, repo_json_path, commit_message, github_repo, github_token):
    """
    Uploads (or updates) the map.json file to a GitHub repo via the GitHub API.

    Args:
        local_json_path (str): Path to your local map.json file.
        repo_json_path (str): Path in the repo (e.g. "map.json" or "images/map.json").
        commit_message (str): Commit message for the update.
        github_repo (str): Full repo, e.g. "FadeevMax/SOP_sales_chatbot"
        github_token (str): Personal access token with repo write access.

    Returns:
        bool: True if upload succeeded, False otherwise.
    """
    url = f"https://api.github.com/repos/{github_repo}/contents/{repo_json_path}"
    headers = {"Authorization": f"token {github_token}"}

    # Get current file SHA (needed for overwrite)
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    # Read and encode the file
    with open(local_json_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    data = {
        "message": commit_message,
        "content": content,
    }
    if sha:
        data["sha"] = sha

    resp = requests.put(url, headers=headers, json=data)
    if resp.status_code in [200, 201]:
        print("✅ map.json updated successfully on GitHub!")
        return True
    else:
        print(f"❌ Failed to update map.json: {resp.text}")
        return False

# Example usage:
# update_json_on_github(
#     local_json_path="cache/images/map.json",
#     repo_json_path="map.json",
#     commit_message="Update map.json from SOP DOCX",
#     github_repo="FadeevMax/SOP_sales_chatbot",
#     github_token="YOUR_GITHUB_TOKEN"
# )

def load_map_from_github():
    """
    Downloads map.json directly from GitHub and returns as a Python dict.
    """
    GITHUB_MAP_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/map.json"
    try:
        resp = requests.get(GITHUB_MAP_URL)
        if resp.status_code == 200:
            return resp.json()
        else:
            st.warning("Could not fetch map.json from GitHub.")
            return {}
    except Exception as e:
        st.warning(f"Error loading image map from GitHub: {e}")
        return {}

