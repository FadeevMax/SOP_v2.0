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
# --- Functions for User and State Management (No changes here) ---
def get_persistent_user_id(local_storage: LocalStorage) -> str:
    user_id = local_storage.getItem("user_id")
    if user_id is None:
        user_id = str(uuid.uuid4())
        local_storage.setItem("user_id", user_id)
    return user_id

def get_user_state_filepath(user_id: str) -> str:
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)
    return os.path.join(STATE_DIR, f"state_{user_id}.json")

def save_app_state(user_id: str):
    if "user_id" not in st.session_state:
        return
    state_to_save = {
        "user_id": user_id,
        "custom_instructions": st.session_state.custom_instructions,
        "current_instruction_name": st.session_state.current_instruction_name,
        "threads": st.session_state.threads
    }
    filepath = get_user_state_filepath(user_id)
    with open(filepath, "w") as f:
        json.dump(state_to_save, f, indent=4)

def load_app_state(user_id: str):
    filepath = get_user_state_filepath(user_id)
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            try:
                state = json.load(f)
                st.session_state.custom_instructions = state.get("custom_instructions", {"Default": DEFAULT_INSTRUCTIONS})
                st.session_state.current_instruction_name = state.get("current_instruction_name", "Default")
                st.session_state.threads = state.get("threads", [])
                st.session_state.custom_instructions["Default"] = DEFAULT_INSTRUCTIONS
                return True
            except (json.JSONDecodeError, KeyError):
                return False
    return False
