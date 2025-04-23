import logging
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
import os

class AzureIdentityManager:
    """Manages Azure authentication using user-assigned or system-assigned managed identities."""
    
    def __init__(self):
        """Initialize the identity manager with the appropriate credential."""
        self.client_id = os.environ.get('AZURE_CLIENT_ID')
        
        if self.client_id:
            logging.info(f"Using user-assigned managed identity with client ID: {self.client_id}")
            self.credential = ManagedIdentityCredential(client_id=self.client_id)
        else:
            logging.info("Using system-assigned managed identity")
            self.credential = DefaultAzureCredential(
                exclude_shared_token_cache_credential=True,
                exclude_visual_studio_credential=True,
                exclude_interactive_browser_credential=True,
                exclude_cli_credential=True
            )

    def get_token(self, scope: str) -> str:
        """
        Get an authentication token for the specified scope.
        
        Args:
            scope: The scope for which to request the token
            
        Returns:
            The authentication token
        """
        try:
            token = self.credential.get_token(scope)
            return token.token
        except Exception as e:
            logging.error(f"Failed to get token for scope {scope}: {str(e)}")
            raise