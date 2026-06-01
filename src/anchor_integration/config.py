"""
Configuration for Anchor Memory Distillation Integration
"""

# Memory distillation settings
MEMORY_DISTILLATION_CONFIG = {
    "enabled": True,
    "max_candidates": 8,
    "confidence_threshold": 0.8,
    "importance_threshold": 0.7,
    "auto_process_episodes": True,
    "vector_index": {
        "enabled": True,
        "distance_metric": "cosine",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
    },
    "quality_filters": {
        "min_content_length": 50,
        "max_content_length": 10000,
        "required_keywords": ["remember", "note", "memorize", "save"],
        "excluded_patterns": ["[system]", "[debug]", "[internal]"]
    }
}

# Integration settings
INTEGRATION_CONFIG = {
    "auto_distill_on_save": True,
    "distill_on_conversation_end": True,
    "maintain_memory_history": True,
    "cross_reference_memories": True
}