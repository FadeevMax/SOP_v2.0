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
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn
# Add these patterns and functions at the top
caption_pattern = re.compile(r"^Image\s+(\d+):?\s*(.*)", re.IGNORECASE)

def clean_caption(text):
    cleaned = unicodedata.normalize('NFKC', text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("–", "-").replace("—", "-").replace(""", '"').replace(""", '"')
    cleaned = cleaned.replace("'", "'").replace("'", "'")
    return cleaned

def extract_label(text):
    text = clean_caption(text)
    m = caption_pattern.match(text)
    if m:
        idx = int(m.group(1))
        desc = m.group(2).strip().rstrip(".")
        return f"Image {idx}: {desc}" if desc else f"Image {idx}"
    return None

def extract_images_and_labels_from_docx(docx_path, image_output_dir, mapping_output_path, debug=False):
    """Extract images and their labels from a DOCX file"""
    # Ensure output directory exists
    os.makedirs(image_output_dir, exist_ok=True)
    doc = Document(docx_path)
    image_map = {}
    items = []
    
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


def chunk_docx_with_images(docx_path):
    """
    Chunks a DOCX so that image captions (e.g., 'Image 3: ...') stay with surrounding text.
    Returns: List of dicts: [{'chunk_text': ..., 'image_labels': [...]}, ...]
    """
    doc = Document(docx_path)
    caption_pattern = re.compile(r"Image\s*\d+[\s\-–—:]*.*", re.IGNORECASE)
    def clean(text):
        return unicodedata.normalize('NFKC', text).strip()

    chunks = []
    buffer = []
    current_images = []

    for para in doc.paragraphs:
        text = clean(para.text)
        if not text:
            continue
        # Detect image caption
        if caption_pattern.match(text):
            # If buffer has text, flush as its own chunk (if not already an image chunk)
            if buffer:
                chunks.append({
                    "chunk_text": "\n".join(buffer).strip(),
                    "image_labels": current_images.copy()
                })
                buffer.clear()
                current_images.clear()
            # Start new chunk with the image caption
            buffer.append(text)
            current_images.append(text)
            # Optionally, also flush image captions as their own chunk
            chunks.append({
                "chunk_text": text,
                "image_labels": [text]
            })
            buffer.clear()
            current_images.clear()
        else:
            buffer.append(text)
    # Flush remaining
    if buffer:
        chunks.append({
            "chunk_text": "\n".join(buffer).strip(),
            "image_labels": current_images.copy()
        })
    return [c for c in chunks if c["chunk_text"].strip()]

def enrich_chunks_with_images(chunks, image_map_path):
    """
    Attach image file names to each chunk if its label appears in the map.
    Returns: list of dicts with chunk_text, image_labels, image_files
    """
    with open(image_map_path, "r") as f:
        image_map = json.load(f)
    for chunk in chunks:
        image_files = []
        for label in chunk["image_labels"]:
            imgfile = image_map.get(label)
            if imgfile:
                image_files.append({"label": label, "file": imgfile})
        chunk["image_files"] = image_files
    return chunks

def load_or_generate_enriched_chunks():
    """
    Returns enriched_chunks either from cache or reprocesses the DOCX and image_map.
    Skips reprocessing if enriched_chunks is newer than DOCX and image_map.
    """
    docx_mtime = get_file_modified_time(DOCX_LOCAL_PATH)
    map_mtime = get_file_modified_time(IMAGE_MAP_PATH)
    chunks_mtime = get_file_modified_time(ENRICHED_CHUNKS_PATH)

    if (
        chunks_mtime and
        docx_mtime and
        map_mtime and
        chunks_mtime > docx_mtime and
        chunks_mtime > map_mtime
    ):
        # Use cached version
        with open(ENRICHED_CHUNKS_PATH, "r") as f:
            return json.load(f)

    # Reprocess everything
    chunks = chunk_docx_with_images(DOCX_LOCAL_PATH)
    enriched_chunks = enrich_chunks_with_images(chunks, IMAGE_MAP_PATH)

    # Save to disk
    with open(ENRICHED_CHUNKS_PATH, "w") as f:
        json.dump(enriched_chunks, f, indent=2)

    return enriched_chunks



