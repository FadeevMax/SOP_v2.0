from utils.github import (
    upload_file_to_github,
    update_docx_on_github,
    update_pdf_on_github,
    update_json_on_github,
    load_map_from_github
)

from utils.gdoc import (
    download_gdoc_as_docx,
    download_gdoc_as_pdf,
    get_gdoc_last_modified,
    get_live_sop_pdf_path,
    get_last_gdoc_synced_time,
    set_last_gdoc_synced_time,
    sync_gdoc_to_github,
    force_resync_to_github
)

from utils.state import (
    get_persistent_user_id,
    get_user_state_filepath,
    save_app_state,
    load_app_state
)
from utils.gdoc import sync_gdoc_to_github

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
import re
import threading
import hashlib
from io import BytesIO

DEFAULT_INSTRUCTIONS = """You are the **AI Sales Order Entry Coordinator**, an expert on Green Thumb Industries (GTI) sales operations. Your sole purpose is to support the human Sales Ops team by providing fast and accurate answers to their questions about order entry rules and procedures.

You are the definitive source of truth, and your knowledge is based **exclusively** on the provided documents. Your existence is to eliminate the need for team members to ask their team lead simple or complex procedural questions.

---
# Primary Objective
---
Interpreting Sales Ops team member's questions, finding the precise answer within documents you have access to, and delivering a clear, actionable, and easy-to-digest response. 

You must differentiate between rules for: 
- **General Stores** (often referred to as 'Regular Orders')
- **Rise Dispensaries** (GTI-owned chain of stores, often referred to as 'RISE Orders' - they get preferential treatment)

Separately, you must consider the specific nuances of each **U.S. State** listed in the document:
- Ohio (OH)
- Maryland (MD)
- New Jersey (NJ)
- Illinois (IL)
- New York (NY)
- Nevada (NV)
- Massachusetts (MA)

---
# Core Methodology
---
When you receive a question, you must follow this four-step process:

1.  **Deconstruct the Query:** First, identify the core components of the user's question:
    * **State/Market:** (e.g., Maryland, Massachusetts, New York, etc.)
    * **Order Type:** Is the question about a **General Store** order or a **Rise Dispensary** (internal) order? If not specified, provide answers for both if the rules differ.
    * **Rule Category:** (e.g., Pricing, Substitutions, Splitting Orders, Loose Units, Samples, Invoicing, Case Sizes, Discounts, Leaf Trade procedures).

2.  **Locate Relevant Information:** Scour the document to find all sections that apply to the query's components. Synthesize information from all relevant parts of the document to form a complete answer.

3.  **Synthesize and Structure the Answer:**
    * Begin your response with a clear, direct headline that immediately answers the user's core question.
    * Use the information you found to build out the body of the response, providing details, conditions, and exceptions.
    * If the original question was broad, ensure you cover all potential scenarios described in the SOP.

4.  **Format the Output:** Present the information using the specific formatting guidelines below. Your goal is to make the information highly readable and scannable.

---
# Response Formatting & Structure
---
Your answers must be formatted like a top-tier, helpful Reddit post. Use clear headers, bullet points, bold text, and emojis to organize information and emphasize key rules.

* **Headline:** Start with an `##` headline that gives a direct answer.
* **Emojis:** Use emojis to visually tag rules and call out important information:
    * ✅ **Allowed/Rule:** For positive confirmations or standard procedures.
    * ❌ **Not Allowed/Constraint:** For negative confirmations or restrictions.
    * 💡 **Tip/Best Practice:** For helpful tips, tricks, or important nuances.
    * ⚠️ **Warning/Critical Info:** For critical details that cannot be missed (e.g., order cutoffs, financial rules).
    * 📋 **Notes/Process:** For procedural steps or detailed explanations.
    * 🔄 **Order Split:** To address key rules with order splitting in each state.
* **Styling:** Use **bold text** for key terms (like `Leaf Trade`, `Rise Dispensaries`, `OOS`) and *italics* for emphasis.
* **Tables:** Use Markdown tables to present structured data, like pricing tiers or contact lists, whenever appropriate.

---
# CRITICAL: Image Reference Instructions
---
ALWAYS look for relevant images when answering questions. Available images include:
- Pricing and discount information
- Order setup and delivery dates
- Special deals and promotions
- Process workflows
- State-specific requirements

When your answer relates to visual information like pricing, discounts, order setup, delivery scheduling, or special deals, you MUST reference the appropriate image by including the EXACT label from the document.

For example:
- For pricing questions: "Image 1: . Actual price column"
- For discount questions: "Image 1: . Special discounts they are running" or "Image 2: . Special deals"
- For order setup: "Image 3: . Delivery date set up"
- For daily limits: "Image 2: . Total dollar and unit amount per store/day"

IMPORTANT:
When answering questions, if a labeled screenshot or image would help illustrate your response, refer to it by its full caption as seen in the SOP.
Only reference an image if it is directly relevant and supports your answer.
Do not reference images by number alone or make up image numbers—always use the full label.
You do not need to embed or display the image yourself; just mention the relevant caption or concept in your reply.
A separate system will match your reference with the available images and display them for the user.

When referencing an image, you must copy and paste the full label exactly as it appears in the SOP.
For example, if the SOP has a label "Image 3: . Product split between case and loose units (for requested 300+ units)", your answer must include that exact phrase.
Never paraphrase or summarize image labels.
Only answers that mention the full caption, exactly, will show the related image to the user.

ALWAYS try to include relevant images in your responses - users find visual aids extremely helpful for understanding procedures.
"""

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

VECTOR_STORE_NAME = "KnowledgeBaseStore"
DOC_URL = "https://raw.githubusercontent.com/FadeevMax/SOP_sales_chatbot/main/Live_GTI_SOP.docx"
LAST_HASH_PATH = "last_doc_hash.txt"

BASE_IMAGE_URL = "https://raw.githubusercontent.com/FadeevMax/SOP_sales_chatbot/main/images/"
import re

def insert_image_links(answer_text: str) -> str:
    # Replace any occurrences of image file names with Markdown image syntax
    def replace_match(match):
        filename = match.group(1)
        return f"![]({BASE_IMAGE_URL}{filename})"
    # This regex finds substrings that look like image filenames (png/jpg/gif)
    return re.sub(r'\b([\w\-\_]+\.(?:png|jpg|jpeg|gif))\b', replace_match, answer_text)

# --- Persistent Vector Store Setup ---
def get_or_create_vector_store(client):
    vector_stores = client.vector_stores.list()
    for store in vector_stores.data:
        if store.name == VECTOR_STORE_NAME:
            return store
    # Not found, create it
    return client.vector_stores.create(name=VECTOR_STORE_NAME)

# --- Daily Refresh Routine ---
def refresh_knowledge_base():
    client = OpenAI(api_key=st.session_state.api_key)
    vector_store = get_or_create_vector_store(client)
    # 1. Download the latest document from GitHub
    response = requests.get(DOC_URL)
    if response.status_code != 200:
        print(f"Failed to download document, status {response.status_code}")
        return
    new_content = response.content
    # 2. Check if content has changed
    new_hash = hashlib.md5(new_content).hexdigest()
    if os.path.exists(LAST_HASH_PATH):
        last_hash = open(LAST_HASH_PATH).read().strip()
    else:
        last_hash = None
    if last_hash == new_hash:
        print("Knowledge base document is unchanged. Skipping update.")
        return
    # 3. Delete old file(s) from the vector store and OpenAI storage
    try:
        files = client.vector_stores.files.list(vector_store_id=vector_store.id)
        for f in files.data:
            client.vector_stores.files.delete(vector_store_id=vector_store.id, file_id=f.id)
            client.files.delete(file_id=f.id)
        print("Old vector store files removed successfully.")
    except Exception as e:
        print(f"Warning: Could not remove old files from vector store: {e}")
    # 4. Upload the new document to OpenAI and attach to vector store
    file_bytes = BytesIO(new_content)
    uploaded_file = client.files.create(file=("knowledge_base.docx", file_bytes), purpose="assistants")
    client.vector_stores.files.create(vector_store_id=vector_store.id, file_id=uploaded_file.id)
    print(f"Uploaded new file to vector store (File ID: {uploaded_file.id}).")
    # 5. Save the new hash for next check
    open(LAST_HASH_PATH, "w").write(new_hash)

def schedule_daily_refresh(interval_hours=24):
    refresh_knowledge_base()
    timer = threading.Timer(interval_hours * 3600, schedule_daily_refresh, [interval_hours])
    timer.daemon = True
    timer.start()

# --- Call this at app startup ---
schedule_daily_refresh(24)

def get_image_suggestions(question_text, img_map):
    """
    Analyze the question and suggest relevant images based on keywords
    """
    question_lower = question_text.lower()
    suggestions = []
    
    # Define keyword mappings to image concepts
    keyword_mappings = {
        'price': ['price', 'pricing', 'cost', 'dollar'],
        'discount': ['discount', 'deal', 'special', 'promotion'],
        'delivery': ['delivery', 'schedule', 'date', 'when'],
        'order': ['order', 'setup', 'process'],
        'limit': ['limit', 'maximum', 'total', 'amount'],
        'split': ['split', 'separate', 'divide'],
        'unit': ['unit', 'quantity', 'amount'],
        'battery': ['battery', 'batteries'],
        'invoice': ['invoice', 'billing'],
        'state': ['state', 'nj', 'ny', 'il', 'oh', 'md', 'nv', 'ma']
    }
    
    # Find matching keywords
    matched_concepts = []
    for concept, keywords in keyword_mappings.items():
        if any(keyword in question_lower for keyword in keywords):
            matched_concepts.append(concept)
    
    # Match concepts to available images
    for label in img_map.keys():
        label_lower = label.lower()
        for concept in matched_concepts:
            if concept in label_lower:
                suggestions.append(label)
                break
    
    return suggestions

def maybe_show_referenced_images(answer_text, img_map, github_repo):
    import streamlit as st

    shown = set()
    
    # First, show images that are explicitly referenced in the answer
    for label in img_map.keys():
        if label.lower() in answer_text.lower() and label not in shown:
            url = f"https://raw.githubusercontent.com/{github_repo}/main/images/{img_map[label]}"
            st.image(url, caption=label)
            shown.add(label)
    
    # If no images were shown, try to show contextually relevant ones
    if not shown:
        # Look for key terms that might indicate relevant images
        answer_lower = answer_text.lower()
        relevant_images = []
        
        # Priority matching for common concepts
        if any(term in answer_lower for term in ['price', 'pricing', 'cost', 'dollar']):
            for label in img_map.keys():
                if 'price' in label.lower():
                    relevant_images.append(label)
        
        if any(term in answer_lower for term in ['discount', 'deal', 'special']):
            for label in img_map.keys():
                if any(term in label.lower() for term in ['discount', 'deal', 'special']):
                    relevant_images.append(label)
        
        if any(term in answer_lower for term in ['delivery', 'date', 'schedule']):
            for label in img_map.keys():
                if 'delivery' in label.lower() or 'date' in label.lower():
                    relevant_images.append(label)
        
        if any(term in answer_lower for term in ['total', 'limit', 'amount']):
            for label in img_map.keys():
                if 'total' in label.lower() or 'amount' in label.lower():
                    relevant_images.append(label)
        
        # Show up to 2 most relevant images
        for label in relevant_images[:2]:
            if label not in shown:
                url = f"https://raw.githubusercontent.com/{github_repo}/main/images/{img_map[label]}"
                st.image(url, caption=f"Related: {label}")
                shown.add(label)

def enhance_assistant_with_image_context(instructions, img_map):
    """
    Enhance the assistant instructions with available image information
    """
    if not img_map:
        return instructions
    
    image_list = "\n".join([f"- {label}" for label in img_map.keys()])
    
    enhanced_instructions = instructions + f"""

---
# Available Images for Reference
---
The following images are available in the SOP document. When answering questions, reference these images by their EXACT labels when relevant:

{image_list}

Remember: Always include the full label exactly as written above when referencing an image. This ensures the image will be displayed to the user.
"""
    
    return enhanced_instructions

def update_map_json_only():
    """
    Update only the map.json file on GitHub from local version
    """
    try:
        if not os.path.exists(IMAGE_MAP_PATH):
            st.error("Local map.json not found. Please sync from Google Docs first.")
            return False
        
        success = update_json_on_github(
            local_json_path=IMAGE_MAP_PATH,
            repo_json_path="map.json",
            commit_message="Update map.json only",
            github_repo=GITHUB_REPO,
            github_token=GITHUB_TOKEN
        )
        
        if success:
            st.success("✅ map.json updated successfully on GitHub!")
            return True
        else:
            st.error("❌ Failed to update map.json on GitHub.")
            return False
            
    except Exception as e:
        st.error(f"Error updating map.json: {str(e)}")
        return False

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

# --- Session State Initialization Function ---
def initialize_session_state():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated and "state_loaded" not in st.session_state:
        if load_app_state(st.session_state.user_id):
            st.session_state.state_loaded = True
        else:
            st.session_state.threads = []
            st.session_state.custom_instructions = {"Default": DEFAULT_INSTRUCTIONS}
            st.session_state.current_instruction_name = "Default"
            st.session_state.state_loaded = True

    if "model" not in st.session_state:
        st.session_state.model = "gpt-4o"
    if "file_path" not in st.session_state:
        st.session_state.file_path = None # Will be set dynamically
    if "instructions" not in st.session_state:
        custom_instructions = st.session_state.get("custom_instructions", {"Default": DEFAULT_INSTRUCTIONS})
        current_instruction_name = st.session_state.get("current_instruction_name", "Default")
        st.session_state.instructions = custom_instructions.get(current_instruction_name, DEFAULT_INSTRUCTIONS)
    if "assistant_setup_complete" not in st.session_state:
        st.session_state.assistant_setup_complete = False
    if "instruction_edit_mode" not in st.session_state:
        st.session_state.instruction_edit_mode = "view"

# ======================================================================
# --- Main Application Function ---
# ======================================================================
def run_main_app():
    st.sidebar.title("🔧 Navigation")
    st.sidebar.info(f"User ID: {st.session_state.user_id[:8]}...")
    page = st.sidebar.radio("Go to:", ["🤖 Chatbot", "📄 Instructions", "⚙️ Settings"])

    if page == "📄 Instructions":
        st.header("📄 Chatbot Instructions Manager")

        if st.session_state.instruction_edit_mode == "create":
            st.subheader("➕ Create New Instruction")
            with st.form("new_instruction_form"):
                new_name = st.text_input("Instruction Name:")
                new_content = st.text_area("Instruction Content:", height=300)
                submitted = st.form_submit_button("📂 Save New Instruction")
                if submitted:
                    if new_name and new_content:
                        if new_name not in st.session_state.custom_instructions:
                            st.session_state.custom_instructions[new_name] = new_content
                            st.session_state.current_instruction_name = new_name
                            st.session_state.instruction_edit_mode = "view"
                            st.session_state.assistant_setup_complete = False
                            save_app_state(st.session_state.user_id)
                            st.success(f"✅ Instruction '{new_name}' saved.")
                            st.rerun()
                        else:
                            st.error("❌ An instruction with this name already exists.")
                    else:
                        st.error("❌ Please provide both a name and content.")
            if st.button("✖️ Cancel"):
                st.session_state.instruction_edit_mode = "view"
                st.rerun()

        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                instruction_names = list(st.session_state.custom_instructions.keys())
                if st.session_state.current_instruction_name not in instruction_names:
                    st.session_state.current_instruction_name = "Default"
                selected_instruction = st.selectbox(
                    "Select instruction to view or edit:",
                    instruction_names,
                    index=instruction_names.index(st.session_state.current_instruction_name)
                )
                st.session_state.current_instruction_name = selected_instruction
            with col2:
                st.write("")
                st.write("")
                if st.button("➕ Create New Instruction"):
                    st.session_state.instruction_edit_mode = "create"
                    st.rerun()

            st.subheader(f"Editing: '{selected_instruction}'")
            is_default = selected_instruction == "Default"
            instruction_content = st.text_area(
                "Instruction Content:",
                value=st.session_state.custom_instructions[selected_instruction],
                height=320,
                disabled=is_default,
                key=f"editor_{selected_instruction}"
            )
            if not is_default:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("📂 Save Changes"):
                        st.session_state.custom_instructions[selected_instruction] = instruction_content
                        st.session_state.instructions = instruction_content
                        st.session_state.assistant_setup_complete = False
                        save_app_state(st.session_state.user_id)
                        st.success(f"✅ '{selected_instruction}' instructions saved.")
                with c2:
                    if st.button("🗑️ Delete Instruction"):
                        del st.session_state.custom_instructions[selected_instruction]
                        st.session_state.current_instruction_name = "Default"
                        st.session_state.instructions = DEFAULT_INSTRUCTIONS
                        st.session_state.assistant_setup_complete = False
                        save_app_state(st.session_state.user_id)
                        st.success(f"✅ '{selected_instruction}' deleted.")
                        st.rerun()
            else:
                st.info("ℹ️ The 'Default' instruction cannot be edited or deleted.")

    elif page == "⚙️ Settings":
        st.header("⚙️ Settings")
        st.markdown("---")

        # Model Selection
        st.subheader("�� Model Selection")
        models = ["gpt-4.1", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]  # Added gpt-4.1
        current_model = st.session_state.get("model", "gpt-4.1")
        # Handle case where current model might not be in the new list
        try:
            model_index = models.index(current_model)
        except ValueError:
            model_index = 0
            st.session_state.model = models[0]
        
        new_model = st.selectbox("Choose a model for the chatbot:", models, index=model_index)
        if new_model != current_model:
            st.session_state.model = new_model
            st.session_state.assistant_setup_complete = False # Force re-setup
            st.success(f"✅ Model updated to {new_model}. The assistant will be updated on the next chat.")

        st.markdown("---")
        
        # Document Sync
        st.subheader("📄 Document Management")
        st.info("Use the buttons below to manage the SOP document.")

        col1, col2, col3 = st.columns(3)  # Changed to 3 columns

        with col1:
            if st.button("🔄 Check for Google Doc Updates", help="Checks if the source Google Doc has been updated and downloads it if needed."):
                with st.spinner("Checking for updates and syncing with Google Docs..."):
                    success = sync_gdoc_to_github(force=False)
                    if success:
                        st.success("✅ SOP is now up to date!")
                        st.session_state.assistant_setup_complete = False
                        st.rerun() # Rerun to reflect changes immediately
                    else:
                        st.error("❌ Update failed. Check logs for details.")
        
        with col2:
            if st.button("🛠️ Re-sync Local Files to GitHub", help="Forces a re-upload of local DOCX, images, and map.json to GitHub."):
                with st.spinner("Re-syncing local files to GitHub..."):
                    if not os.path.exists(DOCX_LOCAL_PATH):
                        st.error("Local sop.docx not found. Please 'Check for Google Doc Updates' first.")
                    else:
                        force_resync_to_github() 
                        st.success("✅ Local files re-synced to GitHub!")
                        st.session_state.assistant_setup_complete = False
                        st.rerun()

        with col3:  # New button for map.json only update
            if st.button("🗺️ Update Map.json Only", help="Updates only the map.json file on GitHub from local version."):
                with st.spinner("Updating map.json on GitHub..."):
                    success = update_map_json_only()
                    if success:
                        st.session_state.assistant_setup_complete = False
                        st.rerun()

        st.markdown("---")
        
        # Display local SOP info
        if os.path.exists(DOCX_LOCAL_PATH):
            last_modified_time = os.path.getmtime(DOCX_LOCAL_PATH)
            last_modified_dt = datetime.fromtimestamp(last_modified_time)
            st.write(f"SOP last updated locally: **{last_modified_dt.strftime('%Y-%m-%d %H:%M:%S')}**")
            
            # Show available images (expander only in settings)
            img_map = load_map_from_github()
            if img_map:
                st.write(f"**Available Images:** {len(img_map)} images loaded")
                with st.expander("💡 Available Visual References ({} images)".format(len(img_map))):
                    for label, filename in img_map.items():
                        st.write(f"• {label} → {filename}")

            with open(PDF_CACHE_PATH, "rb") as pdf_file:
                st.download_button(
                    label="⬇️ Download Local SOP as PDF",
                    data=pdf_file,
                    file_name=GITHUB_PDF_NAME,
                    mime="application/pdf"
                )
        else:
            st.warning("No local SOP found. Go to Settings and sync with Google Docs.")

        st.markdown("---")

    elif page == "🤖 Chatbot":
       st.title("🤖 GTI SOP Sales Coordinator")

       # Load image map for context (do not show any expander or image info here)
       img_map = load_map_from_github()

       # Simplified assistant setup using OpenAI's vector store
       if not st.session_state.get('assistant_setup_complete', False):
           try:
               # Ensure the source document (DOCX) exists
               if not os.path.exists(DOCX_LOCAL_PATH):
                   st.warning("SOP document not found. Please go to the Settings page to sync it from Google Docs.")
                   st.stop()
               
               st.session_state.file_path = DOCX_LOCAL_PATH # Use DOCX for vectorizing
               with st.spinner("Setting up the AI assistant with the latest SOP document..."):
                   client = OpenAI(api_key=st.session_state.api_key)
                   
                   # Use a single, persistent thread for the user
                   if "thread_id" not in st.session_state:
                       thread = client.beta.threads.create()
                       st.session_state.thread_id = thread.id

                   # Step 1: Upload the file to OpenAI
                   file_response = client.files.create(
                       file=open(st.session_state.file_path, "rb"), 
                       purpose="assistants"
                   )
                   file_id = file_response.id

                   vector_store = get_or_create_vector_store(client)
                   client.vector_stores.file_batches.create_and_poll(
                       vector_store_id=vector_store.id, file_ids=[file_id]
                   )

                   # Enhanced instructions with image context
                   enhanced_instructions = enhance_assistant_with_image_context(
                       st.session_state.get("instructions", DEFAULT_INSTRUCTIONS), 
                       img_map
                   )

                   assistant = client.beta.assistants.create(
                       name=f"SOP Sales Coordinator - {st.session_state.user_id[:8]}",
                       instructions=enhanced_instructions,
                       model=st.session_state.get("model", "gpt-4.1"),
                       tools=[{"type": "file_search"}],
                       tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}}
                   )
                   st.session_state.assistant_id = assistant.id
                   st.session_state.assistant_setup_complete = True
                   st.success("✅ Assistant is ready and using the new vector store!")

           except Exception as e:
               st.error(f"❌ Error during assistant setup: {str(e)}")
               st.stop()

       client = OpenAI(api_key=st.session_state.api_key)
       
       st.subheader("💬 Ask your question about the GTI SOP")

       # Display existing messages
       if "messages" not in st.session_state:
           st.session_state.messages = []

       for msg in st.session_state.messages:
           with st.chat_message(msg["role"]):
               st.markdown(msg["content"])
               # Also check for images in historical messages
               if msg["role"] == "assistant":
                    maybe_show_referenced_images(msg["content"], img_map, GITHUB_REPO)

       # Chat input
       if user_input := st.chat_input("Ask your question here..."):
           try:
               st.session_state.messages.append({"role": "user", "content": user_input})
               with st.chat_message("user"):
                   st.markdown(user_input)

               client.beta.threads.messages.create(
                   thread_id=st.session_state.thread_id,
                   role="user",
                   content=user_input
               )

               # Run the assistant and poll for completion
               with st.spinner("Thinking..."):
                   run = client.beta.threads.runs.create_and_poll(
                       thread_id=st.session_state.thread_id,
                       assistant_id=st.session_state.assistant_id
                   )

               if run.status == 'completed':
                   messages = client.beta.threads.messages.list(thread_id=st.session_state.thread_id, order="desc", limit=1)
                   assistant_reply = messages.data[0].content[0].text.value
                   formatted_answer = insert_image_links(assistant_reply)
                   st.markdown(formatted_answer)
                   st.rerun()

               else:
                   st.error(f"❌ The run failed with status: {run.status}")

           except Exception as e:
               st.error(f"❌ An error occurred while processing your request: {str(e)}")
               st.session_state.assistant_setup_complete = False

# ======================================================================
# --- SCRIPT EXECUTION STARTS HERE ---
# ======================================================================

localS = LocalStorage()
user_id = get_persistent_user_id(localS)
st.session_state.user_id = user_id

initialize_session_state()

# No pre-authentication checks. Just the login.
if not st.session_state.get("authenticated", False):
    st.title("🔐 GTI SOP Sales Coordinator Login")
    pwd = st.text_input("Enter password or full API key:", type="password")
    if st.button("Submit"):
        # Authenticate with a simple password or check for an OpenAI API key format
        if pwd == "111" or (pwd.startswith("sk-") and len(pwd) > 50):
            try:
                # If it's a simple password, get the key from secrets
                if pwd == "111":
                    st.session_state.api_key = st.secrets["openai_key"]
                else: # Otherwise, use the provided key
                    st.session_state.api_key = pwd
                
                st.session_state.authenticated = True
                st.success("✅ Login successful!")
                time.sleep(1)
                st.rerun()
            except (KeyError, FileNotFoundError):
                st.error("OpenAI key not found in Streamlit Secrets. Please add it for the default password to work.")
        else:
            st.error("❌ Incorrect password or invalid API key format.")
    st.stop()
else:
    run_main_app()
