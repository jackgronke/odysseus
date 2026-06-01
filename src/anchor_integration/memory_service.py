"""
Memory Service Integration for Odysseus
This service provides integration points for Anchor's memory distillation system
into Odysseus' existing memory infrastructure.
"""

import logging
from typing import Dict, Any, Optional
from services.memory.memory import MemoryManager
from services.memory.memory_vector import VectorMemoryManager
from .memory_distillation_integration import AnchorMemoryDistillation

logger = logging.getLogger(__name__)

class MemoryDistillationService:
    """
    Service that integrates Anchor's memory distillation with Odysseus' memory system.
    """
    
    def __init__(self, memory_manager: MemoryManager, vector_memory_manager: VectorMemoryManager):
        self.memory_manager = memory_manager
        self.vector_memory_manager = vector_memory_manager
        self.distillation_system = AnchorMemoryDistillation(memory_manager, vector_memory_manager)
        
    def process_conversation_episode(self, episode_content: str, source_episode_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Process a conversation episode through the memory distillation pipeline.
        
        Args:
            episode_content: The content of the conversation episode
            source_episode_id: The ID of the source episode (if any)
            
        Returns:
            Dictionary with processing results
        """
        try:
            # Process the episode through memory distillation
            result = self.distillation_system.process_episode(episode_content, source_episode_id)
            
            return {
                "success": True,
                "created_count": result.created_count,
                "indexed_count": result.indexed_count,
                "created_memory_ids": result.created_memory_item_ids,
                "rejected_count": len(result.rejected),
                "message": f"Processed episode with {result.created_count} memories created"
            }
            
        except Exception as e:
            logger.error(f"Error processing conversation episode: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to process conversation episode"
            }
    
    def extract_and_store_memory(self, content: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Extract and store memory from content using Anchor's distillation approach.
        
        Args:
            content: Content to extract memory from
            metadata: Additional metadata for the memory
            
        Returns:
            Dictionary with extraction results
        """
        try:
            # This would normally use LLM to extract candidates
            # For now, we'll use a simplified approach
            logger.info(f"Extracting memory from content: {len(content)} characters")
            
            # In a real implementation, this would call the LLM-based extraction
            # For now, we'll just add the content as a memory
            memory_entry = {
                "text": content,
                "timestamp": int(time.time()),
                "type": "conversation",
                "status": "processed",
                "confidence": 0.9,
                "importance": 0.8,
                "metadata": metadata or {}
            }
            
            memory_id = self.memory_manager.add(memory_entry)
            
            # Add to vector store if healthy
            if self.vector_memory_manager.healthy:
                self.vector_memory_manager.add(memory_id, content)
                indexed = True
            else:
                indexed = False
                
            return {
                "success": True,
                "memory_id": memory_id,
                "indexed": indexed,
                "message": "Memory extracted and stored successfully"
            }
            
        except Exception as e:
            logger.error(f"Error extracting and storing memory: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to extract and store memory"
            }

# Global instance for easy access
memory_distillation_service: Optional[MemoryDistillationService] = None

def get_memory_distillation_service() -> MemoryDistillationService:
    """
    Get the global memory distillation service instance.
    """
    global memory_distillation_service
    if memory_distillation_service is None:
        # This would normally be initialized with proper managers
        # For now, we'll return None to indicate it needs to be initialized
        logger.warning("Memory distillation service not initialized")
        return None
    return memory_distillation_service

def initialize_memory_distillation_service(memory_manager: MemoryManager, vector_memory_manager: VectorMemoryManager) -> MemoryDistillationService:
    """
    Initialize the memory distillation service with the given managers.
    """
    global memory_distillation_service
    memory_distillation_service = MemoryDistillationService(memory_manager, vector_memory_manager)
    return memory_distillation_service