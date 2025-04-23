import logging
from typing import Dict
from azure.keyvault.secrets import SecretClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError
import os
import time
from random import uniform
from azure_identity import AzureIdentityManager  # Changed from relative to absolute import

class AzureKeyVaultClient:
    """Client for fetching secrets from Azure Key Vault using managed identity."""

    REQUIRED_SECRETS = [
        "APPINSIGHTS-APP-ID",
        "APPINSIGHTS-API-KEY",
        "JIRA-EMAIL",
        "JIRA-TOKEN",
        "JIRA-URL",
        "JIRA-PROJECT",
        "AZURE-CONNECTION-STRING"
    ]

    def __init__(self, vault_name: str):
        """
        Initialize the Azure Key Vault client using managed identity.
        Args:
            vault_name: Name of the Azure Key Vault
        """
        try:
            self.vault_url = f"https://{vault_name}.vault.azure.net/"
            
            # Initialize identity manager
            identity_manager = AzureIdentityManager()
            self.credential = identity_manager.credential

            # Create and test the secret client
            self.secret_client = SecretClient(vault_url=self.vault_url, credential=self.credential)
            logging.info(f"Attempting to access Key Vault: {self.vault_url}")

            # Test the credential with a simple operation
            try:
                next(self.secret_client.list_properties_of_secrets(max_page_size=1), None)
                logging.info(f"Successfully connected to Key Vault: {self.vault_url}")
            except Exception as access_error:
                logging.error(f"Access test failed: {str(access_error)}")
                raise

        except Exception as e:
            logging.error(f"Failed to initialize Key Vault client: {str(e)}")
            raise

    def _get_secret_with_retry(self, secret_name: str, max_retries: int = 5, initial_backoff: float = 1.0) -> str:
        """
        Get a secret from Key Vault with exponential backoff retry logic.

        Args:
            secret_name: Name of the secret to retrieve
            max_retries: Maximum number of retry attempts
            initial_backoff: Initial backoff time in seconds

        Returns:
            The secret value
        """
        for attempt in range(max_retries):
            try:
                secret = self.secret_client.get_secret(secret_name)
                return secret.value
            except HttpResponseError as e:
                if e.status_code == 429:  # Too Many Requests
                    if attempt == max_retries - 1:
                        raise

                    # Calculate backoff with jitter
                    backoff = initial_backoff * (2 ** attempt)
                    jitter = uniform(0, 0.1 * backoff)
                    sleep_time = backoff + jitter

                    logging.warning(
                        f"Rate limit hit when fetching secret '{secret_name}'. "
                        f"Retrying in {sleep_time:.2f} seconds (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(sleep_time)
                else:
                    raise

    def get_required_secrets(self) -> Dict[str, str]:
        """
        First check environment variables for required secrets,
        then fall back to Azure Key Vault for any missing ones.
        Returns:
            Dictionary of secret names to values
        """
        secrets = {}
        missing_secrets = []
        secrets_to_fetch = []

        # First check environment variables
        for secret_name in self.REQUIRED_SECRETS:
            env_name = secret_name.replace("-", "_")
            env_value = os.environ.get(env_name)

            if env_value:
                secrets[env_name] = env_value
                logging.info(f"Found secret in environment: {secret_name}")
            else:
                secrets_to_fetch.append(secret_name)

        # Only fetch from Key Vault if there are missing secrets
        if secrets_to_fetch:
            logging.info(f"Fetching {len(secrets_to_fetch)} missing secrets from Key Vault")
            for secret_name in secrets_to_fetch:
                try:
                    secret_value = self._get_secret_with_retry(secret_name)
                    env_name = secret_name.replace("-", "_")
                    secrets[env_name] = secret_value
                    logging.info(f"Successfully retrieved secret from Key Vault: {secret_name}")
                except ResourceNotFoundError:
                    missing_secrets.append(secret_name)
                    logging.error(f"Secret not found in Key Vault: {secret_name}")
                except Exception as e:
                    missing_secrets.append(secret_name)
                    logging.error(f"Error retrieving secret '{secret_name}': {str(e)}")

        if missing_secrets:
            raise ValueError(f"Missing required secrets: {', '.join(missing_secrets)}")

        return secrets
