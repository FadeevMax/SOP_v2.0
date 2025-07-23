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
import numpy as np
from sentence_transformers import SentenceTransformer
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
    os.makedirs(image_output_dir, exist_ok=True)
    doc = Document(docx_path)
    image_map = {}
    items = []
    
    # Collect all blocks in order
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, doc)
            # Check for images in paragraph
            has_image = False
            for run in para.runs:
                if 'graphic' in run._element.xml:
                    for drawing in run._element.findall(".//w:drawing", namespaces=run._element.nsmap):
                        for blip in drawing.findall(".//a:blip", namespaces=run._element.nsmap):
                            rel_id = blip.get(qn('r:embed'))
                            if rel_id and rel_id in doc.part.related_parts:
                                image_part = doc.part.related_parts[rel_id]
                                items.append(('image', image_part))
                                has_image = True
            
            # Add text if it exists
            if para.text.strip():
                items.append(('text', para.text.strip()))
                
        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        # Check for images in table cells
                        for run in para.runs:
                            if 'graphic' in run._element.xml:
                                for drawing in run._element.findall(".//w:drawing", namespaces=run._element.nsmap):
                                    for blip in drawing.findall(".//a:blip", namespaces=run._element.nsmap):
                                        rel_id = blip.get(qn('r:embed'))
                                        if rel_id and rel_id in doc.part.related_parts:
                                            image_part = doc.part.related_parts[rel_id]
                                            items.append(('image', image_part))
                        
                        if para.text.strip():
                            items.append(('text', para.text.strip()))

    # Associate images with their following captions
    image_counter = 1
    i = 0
    while i < len(items):
        if items[i][0] == 'image':
            image_part = items[i][1]
            
            # Look for the next text that might be a caption
            label = None
            for j in range(i + 1, min(i + 3, len(items))):  # Look ahead up to 2 items
                if items[j][0] == 'text':
                    potential_label = extract_label(items[j][1])
                    if potential_label:
                        label = potential_label
                        break
            
            if not label:
                label = f"Image {image_counter}"
            
            # Save image file
            image_extension = image_part.content_type.split('/')[-1]
            if image_extension == 'jpeg':
                image_extension = 'jpg'
            image_name = f"image_{image_counter}.{image_extension}"
            image_path = os.path.join(image_output_dir, image_name)
            
            with open(image_path, "wb") as f:
                f.write(image_part.blob)
            
            image_map[label] = image_name
            image_counter += 1
            
        i += 1

    # Save mapping
    with open(mapping_output_path, "w") as f:
        json.dump(image_map, f, indent=2)
    
    if debug:
        print("Final image_map:")
        for caption, img in image_map.items():
            print(f"{caption} => {img}")
    
    return image_map

# --- Semantic Chunking and Enrichment ---
def semantic_chunking_docx(docx_path, model_name='all-MiniLM-L6-v2', buffer_size=1, percentile=90, min_chunk_size=50):
    """
    Semantic chunking of DOCX content with image association.
    Image captions are always grouped with the text above.
    """
    doc = Document(docx_path)
    model = SentenceTransformer(model_name)

    # Extract all content with metadata
    content_items = []
    image_counter = 1
    prev_text_idx = None

    for para in doc.paragraphs:
        text = clean_caption(para.text.strip())
        if not text:
            continue

        is_caption = bool(caption_pattern.match(text))
        if is_caption and prev_text_idx is not None:
            # Group caption with previous text
            content_items[prev_text_idx]['text'] += f"\n{text}"
            content_items[prev_text_idx]['is_caption'] = True  # Mark chunk as having a caption
            continue
        else:
            content_items.append({
                'text': text,
                'is_caption': is_caption,
                'paragraph_index': len(content_items)
            })
            prev_text_idx = len(content_items) - 1

    # Filter out very short items and group sentences
    sentences = []
    for i, item in enumerate(content_items):
        if len(item['text']) >= min_chunk_size or item['is_caption']:
            sentences.append({
                'sentence': item['text'],
                'is_caption': item['is_caption'],
                'original_index': i
            })

    if not sentences:
        return []

    # Create contextual buffers
    for i in range(len(sentences)):
        combo = []
        for j in range(i - buffer_size, i + buffer_size + 1):
            if 0 <= j < len(sentences):
                combo.append(sentences[j]['sentence'])
        sentences[i]['combined'] = ' '.join(combo)

    # Generate embeddings
    if len(sentences) > 1:
        combined_texts = [s['combined'] for s in sentences]
        embeddings = model.encode(combined_texts, convert_to_numpy=True)

        for i, emb in enumerate(embeddings):
            sentences[i]['embedding'] = emb

        # Compute cosine distances
        distances = []
        for i in range(len(sentences) - 1):
            a = sentences[i]['embedding']
            b = sentences[i + 1]['embedding']
            dist = 1 - (np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
            distances.append(dist)
            sentences[i]['distance_to_next'] = dist

        # Find breakpoints
        if distances:
            threshold = np.percentile(distances, percentile)
            breakpoints = [i for i, d in enumerate(distances) if d > threshold]
        else:
            breakpoints = []
    else:
        breakpoints = []

    # Create chunks
    chunks = []
    start = 0

    for bp in breakpoints:
        end = bp + 1
        chunk_sentences = sentences[start:end]
        if chunk_sentences:
            chunks.append(chunk_sentences)
        start = end

    # Add final chunk
    if start < len(sentences):
        final_chunk = sentences[start:]
        if final_chunk:
            chunks.append(final_chunk)

    # If no semantic breaks found, create reasonable sized chunks
    if not chunks and sentences:
        chunk_size = max(3, len(sentences) // 5)  # Aim for ~5 chunks minimum
        chunks = [sentences[i:i + chunk_size] for i in range(0, len(sentences), chunk_size)]

    return chunks

def enrich_chunks_with_images_semantic(chunks, image_map_path):
    """
    Improved version - attach image information to semantically chunked content.
    Only include image labels/files that exist in map.json, and vice versa.
    """
    import re
    from difflib import SequenceMatcher

    try:
        with open(image_map_path, "r") as f:
            image_map = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        image_map = {}

    def extract_image_numbers(text):
        """Extract image numbers from text"""
        patterns = [
            r"Image\s+(\d+)",
            r"Figure\s+(\d+)",
        ]
        numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            numbers.extend([int(n) for n in matches])
        return list(set(numbers))  # Remove duplicates

    def find_best_match(image_num, image_map):
        """Find best matching image for a number"""
        best_match = None
        best_score = 0

        for image_key, image_file in image_map.items():
            key_numbers = re.findall(r"Image\s+(\d+)", image_key, re.IGNORECASE)
            if key_numbers and int(key_numbers[0]) == image_num:
                score = 1.0
                if best_score < score:
                    best_score = score
                    best_match = (image_key, image_file)

        return best_match

    enriched_chunks = []
    used_labels = set()
    used_files = set()

    for chunk_idx, chunk in enumerate(chunks):
        chunk_text = '\n'.join([s['sentence'] for s in chunk])
        image_numbers = extract_image_numbers(chunk_text)
        image_labels = []
        image_files = []

        for img_num in image_numbers:
            match = find_best_match(img_num, image_map)
            if match:
                label, filename = match
                if label not in image_labels and label in image_map:  # Only if label exists in map
                    image_labels.append(label)
                    image_files.append({"label": label, "file": filename})
                    used_labels.add(label)
                    used_files.add(filename)

        enriched_chunks.append({
            "chunk_id": chunk_idx,
            "chunk_text": chunk_text,
            "sentence_count": len(chunk),
            "image_labels": image_labels,
            "image_files": image_files,
            "has_images": len(image_files) > 0
        })

    # Optionally: log or warn about orphaned labels/files
    orphaned_labels = set(image_map.keys()) - used_labels
    orphaned_files = set(image_map.values()) - used_files
    if orphaned_labels or orphaned_files:
        print(f"Orphaned image labels not used in any chunk: {orphaned_labels}")
        print(f"Orphaned image files not used in any chunk: {orphaned_files}")

    return enriched_chunks

def load_or_generate_enriched_chunks_semantic():
    """
    Load or generate semantically chunked content with images
    """
    docx_mtime = get_file_modified_time(DOCX_LOCAL_PATH)
    map_mtime = get_file_modified_time(IMAGE_MAP_PATH)
    chunks_mtime = get_file_modified_time(ENRICHED_CHUNKS_PATH)

    if (chunks_mtime and docx_mtime and map_mtime and 
        chunks_mtime > docx_mtime and chunks_mtime > map_mtime):
        # Use cached version
        try:
            with open(ENRICHED_CHUNKS_PATH, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    
    # Ensure image extraction is done first
    if not os.path.exists(IMAGE_MAP_PATH):
        print("Extracting images from DOCX...")
        extract_images_and_labels_from_docx(DOCX_LOCAL_PATH, IMAGE_DIR, IMAGE_MAP_PATH, debug=True)
    
    # Generate semantic chunks
    print("Creating semantic chunks...")
    chunks = semantic_chunking_docx(DOCX_LOCAL_PATH)
    
    # Enrich with image information
    print("Enriching chunks with images...")
    enriched_chunks = enrich_chunks_with_images_semantic(chunks, IMAGE_MAP_PATH)
    
    # Save to disk
    os.makedirs(os.path.dirname(ENRICHED_CHUNKS_PATH), exist_ok=True)
    with open(ENRICHED_CHUNKS_PATH, "w") as f:
        json.dump(enriched_chunks, f, indent=2)
    
    print(f"Generated {len(enriched_chunks)} semantic chunks")
    return enriched_chunks

def get_file_modified_time(filepath):
    if os.path.exists(filepath):
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    return None

# Debug function to analyze chunking results
def analyze_chunks(chunks):
    """Analyze the quality of generated chunks"""
    print(f"\n=== CHUNK ANALYSIS ===")
    print(f"Total chunks: {len(chunks)}")
    
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i+1}:")
        print(f"  - Length: {len(chunk['chunk_text'])} chars")
        print(f"  - Sentences: {chunk['sentence_count']}")
        print(f"  - Images: {len(chunk['image_files'])}")
        if chunk['image_files']:
            for img in chunk['image_files']:
                print(f"    * {img['file']} ({img['label']})")
        print(f"  - Preview: {chunk['chunk_text'][:100]}...") 
