import os
import glob
import json
import uuid
from typing import List, Dict, Any
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models

# -----------------------------------------------------------------------------
# 1. ARCHITECTURE SETUP & QDRANT CONNECTION
# -----------------------------------------------------------------------------
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
CLIENT = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

COLLECTION_NAME = "enterprise_knowledge"

# The user requested to separate skills and data into 3 equally sized shards
# but "connect them all". We achieve this by using a single Qdrant Collection 
# (connecting them all for hybrid search) but explicitly setting 3 shards.
SHARD_COUNT = 3 

# -----------------------------------------------------------------------------
# 2. HYBRID SEARCH & METADATA CONFIGURATION
# -----------------------------------------------------------------------------
def initialize_enterprise_collection():
    """
    Implements Step 1: Hybrid Vector-Keyword Search
    Sets up Qdrant for both dense (concept) and sparse (keyword/BM25) search.
    """
    if CLIENT.collection_exists(collection_name=COLLECTION_NAME):
        CLIENT.delete_collection(collection_name=COLLECTION_NAME)

    CLIENT.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": models.VectorParams(
                size=384,  # e.g., for all-MiniLM-L6-v2
                distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams() # SPLADE / BM25 keyword equivalent
        },
        shard_number=SHARD_COUNT  # Distributing across 3 shards as requested
    )

    # Implements Step 2: Metadata Filtering (Hard Constraints)
    # We create payload indexes so Qdrant can instantly filter out data 
    # before performing heavy vector math.
    payload_indexes = ["source_type", "author", "date_created", "security_clearance"]
    for field in payload_indexes:
        CLIENT.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD
        )
    print(f"Collection '{COLLECTION_NAME}' created with {SHARD_COUNT} shards and payload indices.")

# -----------------------------------------------------------------------------
# 3. SMART DATA CHUNKING & METADATA LAYERING
# -----------------------------------------------------------------------------
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Implements Step 1 of Accuracy: Smart Data Chunking
    Breaks massive PDFs/MDs into 500-token logical chunks.
    (Simplified word-based chunker for demonstration)
    """
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunks.append(" ".join(words[i:i + chunk_size]))
    return chunks

def extract_metadata_layer(filepath: str, source_type: str) -> Dict[str, Any]:
    """
    Implements Step 1 of Accuracy: Metadata Layering
    Tags each chunk with strict metadata for hard constraints later.
    """
    stat = os.stat(filepath)
    return {
        "file_path": filepath,
        "file_name": os.path.basename(filepath),
        "source_type": source_type, # e.g., '05_AI' or 'skills'
        "date_created": stat.st_ctime,
        "security_clearance": "standard", # Hard constraint tag
        "author": "NEXEN_SYSTEM"
    }

# -----------------------------------------------------------------------------
# 4. INGESTION PIPELINE (05_AI & SKILLS)
# -----------------------------------------------------------------------------
def fake_embed(text: str) -> List[float]:
    # Placeholder for actual Dense Embedding model (e.g., SentenceTransformers)
    return [0.0] * 384

def fake_sparse_embed(text: str) -> models.SparseVector:
    # Placeholder for actual Sparse Embedding (e.g., SPLADE)
    return models.SparseVector(indices=[1, 2], values=[0.5, 0.5])

def ingest_directory(directory_path: str, source_type: str):
    points = []
    
    # Recursively find all files
    for root, _, files in os.walk(directory_path):
        for file in files:
            if not file.endswith(('.md', '.txt', '.json')):
                continue
            
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                continue
            
            # Step 1: Chunk
            chunks = chunk_text(content)
            
            # Step 2: Metadata Layering
            metadata = extract_metadata_layer(filepath, source_type)
            
            # Step 3: Embed & Prepare Qdrant Point
            for i, chunk in enumerate(chunks):
                chunk_meta = metadata.copy()
                chunk_meta["chunk_index"] = i
                chunk_meta["text_content"] = chunk
                
                point = models.PointStruct(
                    id=str(uuid.uuid4()),
                    payload=chunk_meta,
                    vector={
                        "dense": fake_embed(chunk),
                        "sparse": fake_sparse_embed(chunk)
                    }
                )
                points.append(point)
                
                # Batch upload every 100 points
                if len(points) >= 100:
                    CLIENT.upsert(collection_name=COLLECTION_NAME, points=points)
                    print(f"Upserted 100 points from {source_type}...")
                    points = []
                    
    # Upload remainder
    if points:
        CLIENT.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"Upserted final {len(points)} points from {source_type}.")

def main():
    print("1. Initializing Enterprise Qdrant Architecture...")
    initialize_enterprise_collection()
    
    print("\n2. Ingesting '05_AI' Data...")
    ai_dir = r"H:\FROM_F\05_AI"
    if os.path.exists(ai_dir):
        ingest_directory(ai_dir, source_type="05_AI_data")
    
    print("\n3. Ingesting 'Skills' Data...")
    skills_dir = r"H:\NEXEN\skills"
    if os.path.exists(skills_dir):
        ingest_directory(skills_dir, source_type="skills")
        
    print("\nIngestion Complete. Data is sharded across 3 nodes but connected under one hybrid-search collection.")

if __name__ == "__main__":
    # main() # Disabled execution in artifact, run manually when Qdrant is live
    pass
