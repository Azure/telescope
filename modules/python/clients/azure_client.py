#!/usr/bin/env python3
"""
Azure Client Module

This module provides clients for interacting with Azure services:
1. AzureClient - General Azure resource management operations
2. AKSClient - Specific to Azure Kubernetes Service (AKS) node pool operations

Both clients handle authentication with Azure services using Managed Identity
or other authentication methods provided by DefaultAzureCredential.
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union

# Azure SDK imports
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from aks_client import AKSClient

# Configure logging if logger_config is available
setup_logging()
logger = get_logger(__name__)

# Suppress noisy Azure SDK logs
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
logging.getLogger("azure.identity").setLevel(logging.ERROR)
logging.getLogger("azure.core.pipeline").setLevel(logging.ERROR)
logging.getLogger("msal").setLevel(logging.ERROR)


class AzureClient:
    """
    Client for Azure services.
    
    This client handles authentication with Azure services and provides
    methods for managing Azure resources.
    """
    
    def __init__(
        self, 
        subscription_id: Optional[str] = None, 
        resource_group: Optional[str] = None,
        use_managed_identity: bool = True,
        managed_identity_client_id: Optional[str] = None
    ):
        """
        Initialize the Azure client.
        
        Args:
            subscription_id: The Azure subscription ID. If not provided, 
                             will try to get it from AZURE_MI_SUBSCRIPTION_ID env var.
            resource_group: The default Azure resource group.
            use_managed_identity: Whether to use managed identity for authentication.
                                 If False, will fall back to DefaultAzureCredential.
            managed_identity_client_id: The client ID for the managed identity.
                                       If not provided, will try to get it from 
                                       AZURE_MI_ID env var.
        """
        # Get subscription ID from environment if not provided
        self.subscription_id = subscription_id or os.getenv("AZURE_MI_SUBSCRIPTION_ID")
        if not self.subscription_id:
            raise ValueError("Subscription ID is required. Provide it directly or set AZURE_MI_SUBSCRIPTION_ID environment variable.")
            
        self.resource_group = resource_group
        
        # Set up authentication
        if use_managed_identity:
            mi_client_id = managed_identity_client_id or os.getenv("AZURE_MI_ID")
            if mi_client_id:
                logger.info(f"Using Managed Identity with client ID for authentication")
                self.credential = ManagedIdentityCredential(client_id=mi_client_id)
            else:
                logger.info(f"Using default Managed Identity for authentication")
                self.credential = ManagedIdentityCredential()
        else:
            logger.info(f"Using DefaultAzureCredential for authentication")
            self.credential = DefaultAzureCredential()
            
        # Initialize clients
        self._init_clients()
    
    def _init_clients(self):
        """Initialize the Azure service clients"""
        self.resource_client = ResourceManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id
        )
        
        self.monitor_client = MonitorManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id
        )

        # Initialize AKS client
        self.aks_client = ContainerServiceClient(
            credential=self.credential,
            subscription_id=self.subscription_id
        )

    
