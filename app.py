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
# --- Constants & Configuration ---
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
    * �� **Tip/Best Practice:** For helpful tips, tricks, or important nuances.
    * ⚠️ **Warning/Critical Info:** For critical details that cannot be missed (e.g., order cutoffs, financial rules).
    * �� **Notes/Process:** For procedural steps or detailed explanations.
    * �� **Order Split:** To address key rules with order splitting in each state.
* **Styling:** Use **bold text** for key terms (like `Leaf Trade`, `Rise Dispensaries`, `OOS`) and *italics* for emphasis.
* **Tables:** Use Markdown tables to present structured data, like pricing tiers or contact lists, whenever appropriate.

---
# Example Implementations
---
**User Question Example 1:** "NV orders - batteries on the same order or not?"


**Your Ideal Response:**
## ⚠️ Batteries Must Be on a Separate Order for Nevada (NV) Rise Orders

### �� Note from Airion Quillin, Sales Rep @ GTI
*Separate order would be best, just to make sure it gets called out for an invoice considering batteries don't show up on the manifest or transfer.*

---
**User Question Example 2:** "NJ orders - do we split orders"


**Your Ideal Response:**
## ⚠️ New Jersey orders require splitting under certain conditions

### �� Batteries MUST go on a separate invoice.

### �� Unit total daily limit:
- The maximum total per order is 4,000 units. If there are more than 4,000 items, the order MUST BE SPLIT. The second order will be scheduled for the next day.
	- **Units total per day**: 4,000 units per store. For example, if we have an order for 1,500 units of edibles, another for 200 units of concentrates, and a third for 1,000 units of prerolls (that totals 2,700 units), that means we have 1,300 units of available space left for that delivery date. We should follow these daily limits whenever instructed to do so.
### ⚖️ Line item rule for large orders: If an order has more than 50 line items, it must be split accordingly.

---
### �� Example: A RISE order with 150 lines should be split into 3 orders of 50 lines each.

- **Sample order**: If a request for samples is received (rare), they should be placed as a new order.
- **Two menu formats**: If an NJ order email includes two Excel menus for the same store, combine them into one order in LT.
- **Notes format**:
	- 0/30 Animal Face 3.5g Rythm  
	- 25/50 Brownie Scout 7g Rythm

---
**User Question Example 3:** "IL orders - whats the order limit"


**Your Ideal Response:**

## �� For regular orders
 
- No set unit/dollar limit. Don't break cases.
- Batteries MUST go on separate invoices!

--- 
## �� For RISE stores

- If the order is above 150k or has more than 8k units, you need to split the order equally.

---
### �� **Best Practices & Reminders:**

| Limit Type        | Rule                                                |
| ----------------- | --------------------------------------------------- |
| General Stores    | No set unit/dollar limit. Don't break cases.        |
| Rise Dispensaries | 8,000 units **or** $150,000 per order (must split). |
| Batteries         | Always separate order for batteries.                |
IMPORTANT:
When answering questions, if a labeled screenshot or image would help illustrate your response, refer to it by its full caption as seen in the SOP (for example: Image 2: . Total dollar and unit amount per store / day).
Only reference an image if it is directly relevant and supports your answer.
Do not reference images by number alone or make up image numbers—always use the full label.
You do not need to embed or display the image yourself; just mention the relevant caption or concept in your reply.
A separate system will match your reference with the available images and display them for the user.

When referencing an image, you must copy and paste the full label exactly as it appears in the SOP.
For example, if the SOP has a label "Image 3: . Product split between case and loose units (for requested 300+ units)", your answer must include that exact phrase.
Never paraphrase or summarize image labels.
Only answers that mention the full caption, exactly, will show the related image to the user.
"""
CACHE_DIR = "cache"
PDF_CACHE_PATH = os.path.join(CACHE_DIR, "cached_sop.pdf")
GDOC_STATE_PATH = os.path.join(CACHE_DIR, "gdoc_state.json")
GITHUB_PDF_NAME = "Live_GTI_SOP.pdf"
GITHUB_REPO = "FadeevMax/SOP_sales_chatbot"
GITHUB_TOKEN = st.secrets["GitHub_API"]
GOOGLE_DOC_NAME = "GTI Data Base and SOP"
STATE_DIR = "user_data"
DOCX_LOCAL_PATH = os.path.join(CACHE_DIR, "sop.docx")
IMAGE_DIR = os.path.join(CACHE_DIR, "images")
IMAGE_MAP_PATH = os.path.join(CACHE_DIR, "image_map.json")

from docx import Document
import os
import re
import json

ENRICHED_CHUNKS_PATH = os.path.join(CACHE_DIR, "enriched_chunks.json")

def get_file_modified_time(filepath):
    if os.path.exists(filepath):
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    return None


    def clean_caption(text):
        cleaned = unicodedata.normalize('NFKC', text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = cleaned.replace("–", "-").replace("—", "-").replace("“", '"').replace("”", '"')
        cleaned = cleaned.replace("‘", "'").replace("’", "'")
        return cleaned

    def extract_label(text):
        text = clean_caption(text)
        m = caption_pattern.match(text)
        if m:
            idx = int(m.group(1))
            desc = m.group(2).strip().rstrip(".")
            return f"Image {idx}: {desc}" if desc else f"Image {idx}"
        return None

    # Collect all blocks in order
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, doc)
            # Add images in paragraph as separate items
            for run in para.runs:
                if 'graphic' in run._element.xml:
                    for drawing in run._element.findall(".//w:drawing", namespaces=run._element.nsmap):
                        for blip in drawing.findall(".//a:blip", namespaces=run._element.nsmap):
                            rel_id = blip.get(qn('r:embed'))
                            if rel_id:
                                image_part = doc.part.related_parts[rel_id]
                                items.append(('image', image_part))
            # Always add the text (could be caption or not)
            items.append(('caption', para.text))
        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        # Same as above
                        for run in para.runs:
                            if 'graphic' in run._element.xml:
                                for drawing in run._element.findall(".//w:drawing", namespaces=run._element.nsmap):
                                    for blip in drawing.findall(".//a:blip", namespaces=run._element.nsmap):
                                        rel_id = blip.get(qn('r:embed'))
                                        if rel_id:
                                            image_part = doc.part.related_parts[rel_id]
                                            items.append(('image', image_part))
                        items.append(('caption', para.text))

    # Now, associate images with captions by looking at the NEXT caption after the image
    image_counter = 1
    i = 0
    while i < len(items):
        if items[i][0] == 'image':
            image_part = items[i][1]
            # Look for caption in next item(s)
            label = None
            lookahead = 1
            while i + lookahead < len(items):
                if items[i + lookahead][0] == 'caption':
                    label_candidate = extract_label(items[i + lookahead][1])
                    if label_candidate:
                        label = label_candidate
                        break
                lookahead += 1
            if not label:
                label = f"Image {image_counter}"
            image_name = f"image_{image_counter}.png"
            image_path = os.path.join(image_output_dir, image_name)
            with open(image_path, "wb") as f:
                f.write(image_part.blob)
            image_map[label] = image_name
            image_counter += 1
        i += 1

    with open(mapping_output_path, "w") as f:
        json.dump(image_map, f, indent=2)
    if debug:
        print("Final image_map:")
        for caption, img in image_map.items():
            print(f"{caption} => {img}")
    return image_map

def maybe_show_referenced_images(answer_text, img_map, github_repo):
    import streamlit as st

    shown = set()
    for label in img_map.keys():
        # If the exact label is in the answer text (case-insensitive)
        if label.lower() in answer_text.lower() and label not in shown:
            url = f"https://raw.githubusercontent.com/{github_repo}/main/images/{img_map[label]}"
            st.image(url, caption=label)
            shown.add(label)



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




@st.cache_data(ttl=600) # Cache the result for 10 minutes (600 seconds)

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
        st.subheader("📄 View Live SOP Document")

        if st.button("Check for Updates from Google Doc"):
            success = sync_gdoc_to_github(force=True)
            if success:
                st.success("✅ Checked Google Doc: GitHub PDF is now up to date!")
            else:
                st.error("❌ Update failed or no change detected.")

        github_pdf_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_PDF_NAME}"
        try:
            response = requests.get(github_pdf_url)
            if response.status_code == 200:
                with open(PDF_CACHE_PATH, "wb") as f:
                    f.write(response.content)
                last_modified_time = os.path.getmtime(PDF_CACHE_PATH)
                last_modified_dt = datetime.fromtimestamp(last_modified_time)
                st.write(f"SOP last updated locally: **{last_modified_dt.strftime('%Y-%m-%d %H:%M:%S')}**")
                with open(PDF_CACHE_PATH, "rb") as pdf_file:
                    st.download_button(
                        label="⬇️ Download Live SOP as PDF",
                        data=pdf_file,
                        file_name=GITHUB_PDF_NAME,
                        mime="application/pdf"
                    )
            else:
                st.warning("Could not retrieve the SOP PDF from GitHub.")
        except Exception as e:
            st.error(f"Error fetching PDF from GitHub: {e}")

        st.markdown("---")

    elif page == "🤖 Chatbot":
       st.title("🤖 GTI SOP Sales Coordinator")
       col1, col2 = st.columns(2)
       with col1:
           models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4.1"]
           old_model = st.session_state.model
           new_model = st.selectbox("Choose model:", models, index=models.index(old_model))
       with col2:
           instruction_names = list(st.session_state.custom_instructions.keys())
           old_instruction = st.session_state.current_instruction_name
           new_instruction = st.selectbox("Choose instructions:", instruction_names, index=instruction_names.index(old_instruction))

       settings_changed = (old_model != new_model) or (old_instruction != new_instruction)
       if settings_changed:
           st.warning("⚠️ Settings changed. You need to start a new thread to apply these changes.")
           if st.button("🆕 Start New Thread with New Settings"):
               st.session_state.model = new_model
               st.session_state.current_instruction_name = new_instruction
               st.session_state.instructions = st.session_state.custom_instructions[new_instruction]
               st.session_state.assistant_setup_complete = False
               client = OpenAI(api_key=st.session_state.api_key)
               thread = client.beta.threads.create()
               new_thread_obj = {"thread_id": thread.id, "messages": [], "start_time": datetime.now().isoformat(), "model": new_model, "instruction_name": new_instruction}
               st.session_state.threads.append(new_thread_obj)
               st.session_state.thread_id = thread.id
               save_app_state(st.session_state.user_id)
               st.success("✅ New thread created with updated settings!")
               st.rerun()
       else:
           st.session_state.model = new_model
           st.session_state.current_instruction_name = new_instruction
           st.session_state.instructions = st.session_state.custom_instructions[new_instruction]

       if not st.session_state.get('assistant_setup_complete', False):
           try:
               if PDF_CACHE_PATH and os.path.exists(PDF_CACHE_PATH):
                   st.session_state.file_path = PDF_CACHE_PATH
               else:
                   st.error("Could not retrieve the SOP PDF. Assistant setup failed.")
                   st.stop()

               with st.spinner("Setting up AI assistant with the latest data..."):
                   client = OpenAI(api_key=st.session_state.api_key)
		   # Step 1: Chunk DOCX with image labels
		   enriched_chunks = load_or_generate_enriched_chunks()
		
		   # Step 3: Create embeddings for enriched_chunks
		   # This replaces file upload for assistant context
		   vector_store = client.vector_stores.create(name=f"SOP Vector Store - {st.session_state.user_id[:8]}")
		   for chunk in enriched_chunks:
			vector_store.embeddings.create(
			input=chunk["chunk_text"],
			metadata={"image_labels": chunk["image_labels"], "image_files": chunk["image_files"]}
		    )

                   assistant = client.beta.assistants.create(
                       name=f"SOP Sales Coordinator - {st.session_state.user_id[:8]}",
                       instructions=st.session_state.instructions,
                       model=st.session_state.model,
                       tools=[{"type": "file_search"}],
                       tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}}
                   )
                   st.session_state.assistant_id = assistant.id

                   if not st.session_state.threads:
                       thread = client.beta.threads.create()
                       st.session_state.threads.append({
                           "thread_id": thread.id,
                           "messages": [],
                           "start_time": datetime.now().isoformat(),
                           "model": st.session_state.model,
                           "instruction_name": st.session_state.current_instruction_name
                       })
                       st.session_state.thread_id = thread.id
                       save_app_state(st.session_state.user_id)

                   st.session_state.assistant_setup_complete = True
                   st.success("✅ Assistant is ready with the latest information!")
           except Exception as e:
               st.error(f"❌ Error setting up assistant: {str(e)}")
               st.stop()

       client = OpenAI(api_key=st.session_state.api_key)
       st.sidebar.subheader("🧵 Your Threads")
       thread_options = [f"{i+1}: {t['start_time'].split('T')[0]} | {t.get('model', 'N/A')} | {t.get('instruction_name', 'N/A')}" for i, t in enumerate(st.session_state.threads)]
       thread_ids = [t['thread_id'] for t in st.session_state.threads]
       selected_thread_info = None
       if thread_options:
           current_idx = thread_ids.index(st.session_state.thread_id) if 'thread_id' in st.session_state and st.session_state.thread_id in thread_ids else 0
           selected_idx = st.sidebar.selectbox("Select Thread", range(len(thread_options)), format_func=lambda x: thread_options[x], index=current_idx)
           selected_thread_info = st.session_state.threads[selected_idx]
           st.session_state.thread_id = selected_thread_info['thread_id']

       if st.sidebar.button("➕ Start New Thread"):
           thread = client.beta.threads.create()
           new_thread_obj = {
               "thread_id": thread.id,
               "messages": [],
               "start_time": datetime.now().isoformat(),
               "model": st.session_state.model,
               "instruction_name": st.session_state.current_instruction_name
           }
           st.session_state.threads.append(new_thread_obj)
           st.session_state.thread_id = thread.id
           save_app_state(st.session_state.user_id)
           st.rerun()

       st.subheader("💬 Ask your question about the GTI SOP")

       if selected_thread_info:
           st.info(f"🔧 Current: {selected_thread_info.get('model', 'unknown')} | {selected_thread_info.get('instruction_name', 'unknown')}")

           for msg in selected_thread_info['messages']:
               with st.chat_message("user"):
                   st.markdown(msg["user"])
               with st.chat_message("assistant"):
                   st.markdown(msg["assistant"])

           user_input = st.chat_input("Ask your question here...")

           if user_input:
               try:
                   selected_thread_info["messages"].append({"user": user_input, "assistant": ""})
                   with st.chat_message("user"):
                       st.markdown(user_input)

                   client.beta.threads.messages.create(
                       thread_id=selected_thread_info["thread_id"],
                       role="user",
                       content=user_input
                   )

                   run = client.beta.threads.runs.create_and_poll(
                       thread_id=selected_thread_info["thread_id"],
                       assistant_id=st.session_state.assistant_id
                   )

                   if run.status == 'completed':
                       messages = client.beta.threads.messages.list(thread_id=selected_thread_info["thread_id"])
                       assistant_reply = next(
                           (m.content[0].text.value for m in messages.data if m.role == "assistant"),
                           "Sorry, I couldn't get a response."
                       )
                       selected_thread_info["messages"][-1]["assistant"] = assistant_reply
                       with st.chat_message("assistant"):
                           st.markdown(assistant_reply)
                           img_map = load_map_from_github()
                           maybe_show_referenced_images(assistant_reply, img_map, GITHUB_REPO)

                       save_app_state(st.session_state.user_id)

                   else:
                       st.error(f"❌ Run failed with status: {run.status}")
                       selected_thread_info["messages"].pop()

               except Exception as e:
                   st.error(f"❌ Error processing your request: {str(e)}")
                   st.session_state.assistant_setup_complete = False
                   if selected_thread_info["messages"]:
                       selected_thread_info["messages"].pop()
       else:
           st.info("Start a new thread to begin chatting.")



# ======================================================================
# --- SCRIPT EXECUTION STARTS HERE ---
# ======================================================================

localS = LocalStorage()
user_id = get_persistent_user_id(localS)
st.session_state.user_id = user_id

initialize_session_state()

if not st.session_state.authenticated:
    st.title("🔐 GTI SOP Sales Coordinator Login")
    pwd = st.text_input("Enter password or full API key:", type="password")
    if st.button("Submit"):
        if pwd == "111":
            try:
                st.session_state.api_key = st.secrets["openai_key"]
                st.session_state.authenticated = True
                st.success("✅ Correct password—welcome!")
                time.sleep(1)
                st.rerun()
            except (KeyError, FileNotFoundError):
                st.error("OpenAI key not found in Streamlit Secrets. Please add it to your deployment.")
        elif pwd.startswith("sk-"):
            st.session_state.api_key = pwd
            st.session_state.authenticated = True
            st.success("✅ API key accepted!")
            time.sleep(1)
            st.rerun()
        else:
            st.error("❌ Incorrect password or API key.")
    st.stop()
else:
    run_main_app()
