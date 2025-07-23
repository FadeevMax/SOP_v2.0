import streamlit as st
import json
import os
import re
import unicodedata
import numpy as np
from sentence_transformers import SentenceTransformer
from docx import Document
from datetime import datetime
from typing import List, Dict, Any

GitHub_API = "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"
openai_key = "REMOVED_SECRET"

[gcp_service_account]
type = "service_account"
project_id = "tribal-contact-465208-q3"
private_key_id = "27cc570ccecd77f28da23033dd026e331ffbe4e7" # <-- Replace with your NEW key ID
private_key = """-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCoE/lv90MTbRAw\nIG1LSnmugcQKScLTLvnMSPSEmWsQLqLlw2lwSvv+cYuALeRQ8UTRf+jOLMBXU2kl\nj4Qv/Z8Tn22PSOSx4/tym/r/BqRu9zsnCvCkZQNmtzcMP08rajv1VzJyir9gv+9G\naWnvm97BlBFOxMF/8Gb6QmQuinPQYxoJyIg6uTEQanZ1shts4C7la7Qh6ptQm6vm\nZJBhtQniQBRgh+hnIveb3NyDgosE2Kas6R0QD35/wYUM5bKrxt7YrsWl3zOSw2eb\ngugz90LZ5udcoAVLuCORsQ8V+UEU0utMNXuL8TB+VNOaseiQFvQtIvZpSmEBVBEa\nVeo2cKcJAgMBAAECggEAKu7jPfb+osUup+R4lo1hFLLgBTK/OdubglO2ZfKcdwc6\npA8s7TqyMNYHKMhQNF7U0eDm8ldbEFNlnesRfIK/8i68uSeJB2mxbp6qWB91vESZ\nzwjL3GpTGpc9T/sR+YiK5UoPQFPxu8B7WdSOc16w4Wi1nRXESa56V33DAmJqX/Wu\neX9MsDpNzfciopjzg801f5RCYVNScgYOGKHTnYjtjSawZFbd3BKwFOFmkh7Z7+jx\nSheXuNdzvRSAiRBZr23QYppzcOtkxamvQTt/BbJOWCVYFiV/UJEYoS+X0l/Ysrga\nRtBIqrjF1gtG3a2gWDBbCOf1iak3y9Jh5KXP2fh9MwKBgQDZE4Ofek0lhIQnDn26\naYEIUU+RluK53RkVHOcPs8VZcRptgSRPG0E7ObHHFmnObEcm5L6YCQQCRho6Oqno\n5CFDlCw/kWp1Wk1Lw6Nffp/aSfTBNY3BKVKoYFYPRou24G7ITdBQ9PTrENz5ayTH\nzVbPBe8okf7BZ70mkZNXPYTVywKBgQDGN0mjqSuYbBmu1qslAKN6xAJKqTjlVnpO\ncbbAyWSTAsWENGMZSS6VsWm8n6tXuWkKWiXT5+4bjA1X5xoA+RY2wL0vJTn8vfiX\nWENbo57Or0jUYpRzIGES9NscKaBubtNvDREyZ29h/RtKJhADl/Wz7N7Bzd0jNk85\nB2ZUzB/7+wKBgQDAG7v9lA/YJxmJMxLjuWEfCk6fqufF0zzSaXy3ccIycJ0R0htf\nAuDM2DdT2KsUqtChRAjEph3tITsu0yHxYItrsiMisr+DUcJcTaw04+v2FENOBeYI\nz1g+eNtQs38L/j0seWjlbJOfwJG/DipDxJ6Rok/QGLxbT0Kfcm/x4hi/1wKBgDfK\n8ihmAsZpjyUeeZf1wQ5aQ8beMQyktdKEwYssZOnYet5GnKpOZhVulbOpQeJ0ZvOq\nAkHOY8BPQKZAf5pMgosw30947ASPOHzpNDSELrxArIBTqzNopspeL5qSwPy0p0D3\n7aJBaSGsy9SoOBO630cg4mas2pUBwXTs90nhFxOnAoGBAIZblnJye8BWaEjzZLCk\ngGvy9jDH99qipECqcLxb2IVUiA5tZEHCGA1P/6t9A7KFDRfu8xf6jFTPMCdH+nQN\nWiySNDWMWoZldUZ8fDKQmaRNx7b97MQhjyNYk+xI0s04JeLpgJ7dYMkSgN1ch/rA\nFLXtqGotP4dsROXZeJiWa1Hu\n-----END PRIVATE KEY-----\n""" # <-- Replace with your NEW key
client_email = "sheets-access-bot@tribal-contact-465208-q3.iam.gserviceaccount.com" # <-- Replace with your NEW email
client_id = "108950941929980320908"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/sheets-access-bot%40tribal-contact-465208-q3.iam.gserviceaccount.com" # <-- Replace with your NEW URL
universe_domain = "googleapis.com"




def normalize_text(text: str) -> str:
    """Normalize text for consistent comparison"""
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r"\s+", " ", text).strip()
    # Normalize punctuation
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace(""", '"').replace(""", '"')
    text = text.replace("'", "'").replace("'", "'")
    # Normalize image caption format
    text = re.sub(r"Image\s*(\d+)[\s\-–—:\.]*\s*(.*)", r"Image \1: \2", text, flags=re.IGNORECASE)
    return text.strip()

def is_image_caption(text: str) -> bool:
    """Check if text is an image caption"""
    normalized = normalize_text(text)
    return bool(re.match(r"^Image\s+\d+:", normalized, re.IGNORECASE))

def extract_sentences_from_docx(docx_path: str) -> List[Dict[str, Any]]:
    """Extract sentences from DOCX with metadata"""
    doc = Document(docx_path)
    sentences = []
    
    for para_idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
            
        normalized_text = normalize_text(text)
        
        # Split into sentences (basic splitting)
        if is_image_caption(normalized_text):
            # Keep image captions as single units
            sentences.append({
                'text': normalized_text,
                'paragraph_idx': para_idx,
                'is_image_caption': True,
                'sentence_idx': len(sentences)
            })
        else:
            # Split regular text into sentences
            sent_list = re.split(r'[.!?]+\s+', text)
            for sent in sent_list:
                sent = sent.strip()
                if sent:
                    sentences.append({
                        'text': sent,
                        'paragraph_idx': para_idx,
                        'is_image_caption': False,
                        'sentence_idx': len(sentences)
                    })
    
    return sentences

def create_contextual_windows(sentences: List[Dict], window_size: int = 2) -> List[Dict]:
    """Create contextual windows around each sentence"""
    for i, sentence in enumerate(sentences):
        context_sentences = []
        for j in range(max(0, i - window_size), min(len(sentences), i + window_size + 1)):
            context_sentences.append(sentences[j]['text'])
        sentence['context'] = ' '.join(context_sentences)
    return sentences

def compute_semantic_similarities(sentences: List[Dict], model_name: str = 'all-MiniLM-L6-v2') -> List[Dict]:
    """Compute semantic similarities between consecutive sentences"""
    if not sentences:
        return sentences
    
    # Load embedding model
    model = SentenceTransformer(model_name)
    
    # Get embeddings for contexts
    contexts = [s['context'] for s in sentences]
    embeddings = model.encode(contexts, convert_to_tensor=False)
    
    # Add embeddings to sentences
    for i, embedding in enumerate(embeddings):
        sentences[i]['embedding'] = embedding
    
    # Compute similarities between consecutive sentences
    similarities = []
    for i in range(len(sentences) - 1):
        emb1 = sentences[i]['embedding']
        emb2 = sentences[i + 1]['embedding']
        
        # Cosine similarity
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        distance = 1 - similarity
        
        similarities.append(distance)
        sentences[i]['distance_to_next'] = distance
    
    return sentences, similarities

def find_semantic_breakpoints(similarities: List[float], percentile: float = 85) -> List[int]:
    """Find breakpoints based on semantic distance"""
    if not similarities:
        return []
    
    threshold = np.percentile(similarities, percentile)
    breakpoints = []
    
    for i, distance in enumerate(similarities):
        if distance > threshold:
            breakpoints.append(i)
    
    return breakpoints

def create_semantic_chunks(sentences: List[Dict], breakpoints: List[int]) -> List[Dict]:
    """Create chunks based on semantic breakpoints while preserving image associations"""
    if not sentences:
        return []
    
    chunks = []
    start_idx = 0
    
    # Add breakpoints and ensure we end at the last sentence
    all_breakpoints = sorted(breakpoints + [len(sentences) - 1])
    
    for breakpoint in all_breakpoints:
        end_idx = breakpoint + 1
        chunk_sentences = sentences[start_idx:end_idx]
        
        if chunk_sentences:
            # Combine text from all sentences in chunk
            chunk_text_parts = []
            image_labels = []
            
            for sent in chunk_sentences:
                chunk_text_parts.append(sent['text'])
                if sent['is_image_caption']:
                    image_labels.append(sent['text'])
            
            chunk = {
                'chunk_text': '\n'.join(chunk_text_parts),
                'image_labels': image_labels,
                'sentence_count': len(chunk_sentences),
                'start_sentence_idx': chunk_sentences[0]['sentence_idx'],
                'end_sentence_idx': chunk_sentences[-1]['sentence_idx']
            }
            chunks.append(chunk)
        
        start_idx = end_idx
    
    return [c for c in chunks if c['chunk_text'].strip()]

def fuzzy_match_labels(chunk_label: str, map_labels: List[str], threshold: float = 0.8) -> str:
    """Find the best matching label from image map using fuzzy matching"""
    from difflib import SequenceMatcher
    
    best_match = None
    best_score = 0
    
    normalized_chunk = normalize_text(chunk_label).lower()
    
    for map_label in map_labels:
        normalized_map = normalize_text(map_label).lower()
        
        # Try exact match first
        if normalized_chunk == normalized_map:
            return map_label
        
        # Try fuzzy matching
        score = SequenceMatcher(None, normalized_chunk, normalized_map).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = map_label
    
    return best_match

def enrich_chunks_with_images(chunks: List[Dict], image_map_path: str) -> List[Dict]:
    """Enrich chunks with image file information"""
    if not os.path.exists(image_map_path):
        print(f"Warning: Image map file not found: {image_map_path}")
        for chunk in chunks:
            chunk['image_files'] = []
        return chunks
    
    with open(image_map_path, 'r', encoding='utf-8') as f:
        image_map = json.load(f)
    
    map_labels = list(image_map.keys())
    
    for chunk in chunks:
        image_files = []
        
        for chunk_label in chunk['image_labels']:
            # Try to find matching label in image map
            matched_label = fuzzy_match_labels(chunk_label, map_labels)
            
            if matched_label and matched_label in image_map:
                image_files.append({
                    'label': chunk_label,
                    'matched_label': matched_label,
                    'file': image_map[matched_label]
                })
            else:
                print(f"Warning: No image found for label: '{chunk_label}'")
                # Still add it but without file
                image_files.append({
                    'label': chunk_label,
                    'matched_label': None,
                    'file': None
                })
        
        chunk['image_files'] = image_files
    
    return chunks

def process_document_with_semantic_chunking(
    docx_path: str, 
    image_map_path: str, 
    output_path: str,
    window_size: int = 2,
    similarity_percentile: float = 85,
    model_name: str = 'all-MiniLM-L6-v2'
) -> List[Dict]:
    """
    Complete pipeline for semantic chunking with image integration
    """
    print("🔄 Extracting sentences from DOCX...")
    sentences = extract_sentences_from_docx(docx_path)
    print(f"   Found {len(sentences)} sentences")
    
    if not sentences:
        print("❌ No sentences found in document")
        return []
    
    print("🔄 Creating contextual windows...")
    sentences = create_contextual_windows(sentences, window_size)
    
    print("🔄 Computing semantic similarities...")
    sentences, similarities = compute_semantic_similarities(sentences, model_name)
    
    print("🔄 Finding semantic breakpoints...")
    breakpoints = find_semantic_breakpoints(similarities, similarity_percentile)
    print(f"   Found {len(breakpoints)} breakpoints")
    
    print("🔄 Creating semantic chunks...")
    chunks = create_semantic_chunks(sentences, breakpoints)
    print(f"   Created {len(chunks)} chunks")
    
    print("🔄 Enriching chunks with image information...")
    enriched_chunks = enrich_chunks_with_images(chunks, image_map_path)
    
    # Save enriched chunks
    print("🔄 Saving enriched chunks...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(enriched_chunks, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Semantic chunking complete! Saved to {output_path}")
    
    # Print summary
    chunks_with_images = sum(1 for c in enriched_chunks if c['image_files'])
    total_images = sum(len(c['image_files']) for c in enriched_chunks)
    
    print(f"📊 Summary:")
    print(f"   - Total chunks: {len(enriched_chunks)}")
    print(f"   - Chunks with images: {chunks_with_images}")
    print(f"   - Total images: {total_images}")
    
    return enriched_chunks

# Streamlit integration functions
def display_chunk_with_images(chunk: Dict, image_dir: str):
    """Display a chunk with its associated images in Streamlit"""
    # Display the text content
    st.write(chunk['chunk_text'])
    
    # Display associated images
    if chunk['image_files']:
        st.write("**Associated Images:**")
        
        for img_info in chunk['image_files']:
            if img_info['file']:
                image_path = os.path.join(image_dir, img_info['file'])
                if os.path.exists(image_path):
                    st.image(image_path, caption=img_info['label'], use_column_width=True)
                else:
                    st.warning(f"Image file not found: {img_info['file']}")
            else:
                st.warning(f"No image file found for: {img_info['label']}")

def search_chunks_for_query(chunks: List[Dict], query: str, model_name: str = 'all-MiniLM-L6-v2', top_k: int = 3) -> List[Dict]:
    """Search chunks for relevant content based on query"""
    if not chunks:
        return []
    
    model = SentenceTransformer(model_name)
    
    # Embed the query
    query_embedding = model.encode([query])[0]
    
    # Embed all chunks
    chunk_texts = [chunk['chunk_text'] for chunk in chunks]
    chunk_embeddings = model.encode(chunk_texts)
    
    # Compute similarities
    similarities = []
    for i, chunk_emb in enumerate(chunk_embeddings):
        similarity = np.dot(query_embedding, chunk_emb) / (
            np.linalg.norm(query_embedding) * np.linalg.norm(chunk_emb)
        )
        similarities.append((i, similarity))
    
    # Sort by similarity and return top k
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    results = []
    for i, score in similarities[:top_k]:
        chunk_copy = chunks[i].copy()
        chunk_copy['similarity_score'] = score
        results.append(chunk_copy)
    
    return results

# Example usage for your specific case
def load_or_generate_enriched_chunks(
    docx_path: str,
    image_map_path: str, 
    enriched_chunks_path: str,
    force_regenerate: bool = False
) -> List[Dict]:
    """
    Load enriched chunks from cache or regenerate if needed
    """
    def get_file_mtime(path):
        return os.path.getmtime(path) if os.path.exists(path) else 0
    
    docx_mtime = get_file_mtime(docx_path)
    map_mtime = get_file_mtime(image_map_path)
    chunks_mtime = get_file_mtime(enriched_chunks_path)
    
    # Check if we need to regenerate
    need_regenerate = (
        force_regenerate or
        not os.path.exists(enriched_chunks_path) or
        chunks_mtime < docx_mtime or
        chunks_mtime < map_mtime
    )
    
    if not need_regenerate:
        print("📁 Loading cached enriched chunks...")
        with open(enriched_chunks_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # Regenerate chunks
    return process_document_with_semantic_chunking(
        docx_path=docx_path,
        image_map_path=image_map_path,
        output_path=enriched_chunks_path
    )