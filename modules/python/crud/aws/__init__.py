"""
AWS CRUD Operations Module

This module provides CRUD operations for AWS resources, specifically EKS node groups.
"""

from .node_pool_crud import NodePoolCRUD

__all__ = ["NodePoolCRUD"]
