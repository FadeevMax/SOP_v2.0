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

def extract_images_and_labels_from_docx(docx_path, image_output_dir, mapping_output_path, debug=False):
    from docx.oxml.ns import qn
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    import unicodedata, re, os, json

    if not os.path.exists(image_output_dir):
        os.makedirs(image_output_dir)

    doc = Document(docx_path)
    image_map = {}
    items = []  # Ordered list of ("image", image_part), ("caption", text), etc.

    caption_pattern = re.compile(r"Image\s*(\d+)[\s\-–—:]*\s*(.*)", re.IGNORECASE)



