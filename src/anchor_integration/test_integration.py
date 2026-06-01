"""
Test script for Anchor Memory Distillation Integration
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from anchor_integration.memory_distillation_integration import AnchorMemoryDistillation
from services.memory.memory import MemoryManager
from services.memory.memory_vector import VectorMemoryManager

def test_integration():
    """Test that the Anchor integration can be initialized."""
    print("Testing Anchor Memory Distillation Integration...")
    
    # Create test managers
    memory_manager = MemoryManager("/tmp/test_data")
    vector_manager = VectorMemoryManager("/tmp/test_data")
    
    # Initialize the distillation system
    distillation_system = AnchorMemoryDistillation(memory_manager, vector_manager)
    
    print("✓ AnchorMemoryDistillation initialized successfully")
    
    # Test candidate extraction
    test_content = "This is a test conversation about memory management and AI systems."
    result = distillation_system.extract_candidates_from_episode(test_content)
    
    print(f"✓ Candidate extraction completed: {result.valid_count} valid candidates")
    
    # Test storage
    store_result = distillation_system.store_candidates([])
    
    print(f"✓ Storage completed: {store_result.created_count} created, {store_result.indexed_count} indexed")
    
    print("All tests passed!")

if __name__ == "__main__":
    test_integration()