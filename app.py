from flask import Flask, jsonify, request
from datetime import datetime
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
import os
import logging
import json
import time
import requests
from requests.auth import HTTPBasicAuth
from dateutil.parser import parse
import traceback
from azure_key_vault import AzureKeyVaultClient
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Handle reverse proxy headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configure logging for production
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d'
)
# Reduce Azure SDK logging in production
logging.getLogger('azure').setLevel(logging.WARNING)
# Reduce werkzeug logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Add request timeout
REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', 30))
MAX_RETRIES = int(os.environ.get('MAX_RETRIES', 3))
RETRY_DELAY = int(os.environ.get('RETRY_DELAY', 1))

def load_secrets():
    """Load secrets from environment variables first, then from Azure Key Vault if needed"""
    try:
        vault_name = os.environ.get('AZURE_VAULT_NAME')
        if not vault_name:
            raise ValueError("AZURE_VAULT_NAME environment variable is not set")
            
        vault_client = AzureKeyVaultClient(vault_name=vault_name)
        secrets = vault_client.get_required_secrets()
        
        # Load any missing secrets into environment variables
        for name, value in secrets.items():
            if not os.environ.get(name):
                os.environ[name] = value
        
        logger.info("Successfully loaded secrets")
        
    except ValueError as ve:
        logger.error(f"Configuration error: {str(ve)}")
        raise
    except Exception as e:
        logger.error(f"Failed to load secrets: {str(e)}")
        raise

# Initialize environment variables from Key Vault before using them
load_secrets()

# Now these variables will be populated from Key Vault
JIRA_TOKEN = os.environ.get('JIRA_TOKEN')
JIRA_EMAIL = os.environ.get('JIRA_EMAIL')
JIRA_URL = os.environ.get('JIRA_URL')
JIRA_PROJECT = os.environ.get('JIRA_PROJECT')
AZURE_CONNECTION_STRING = os.environ.get('AZURE_CONNECTION_STRING')
APPINSIGHTS_APP_ID = os.environ.get('APPINSIGHTS_APP_ID')
APPINSIGHTS_API_KEY = os.environ.get('APPINSIGHTS_API_KEY')

if not all([JIRA_TOKEN, JIRA_EMAIL, JIRA_URL, JIRA_PROJECT, 
           AZURE_CONNECTION_STRING, APPINSIGHTS_APP_ID, APPINSIGHTS_API_KEY]):
    raise ValueError("Missing required environment variables")

# Azure Table configuration
TABLE_NAME = "ExceptionTracking"

# Global table client with connection pooling
table_client = None

def get_table_client():
    """Get or create the table client using managed identity with retry logic"""
    global table_client
    
    for attempt in range(MAX_RETRIES):
        try:
            if table_client is not None:
                # Test if the client is still valid - fixed 'take' parameter issue
                list(table_client.list_entities(select=['PartitionKey']).take(1))
                return table_client

            # Create new client
            table_service = TableServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
            try:
                table_service.create_table(TABLE_NAME)
                logger.info(f"Created new table {TABLE_NAME}")
            except ResourceExistsError:
                logger.debug(f"Table {TABLE_NAME} already exists")
            
            table_client = table_service.get_table_client(TABLE_NAME)
            return table_client
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            table_client = None
    
    raise ConnectionError("Failed to establish table client connection after retries")

@app.before_request
def before_request():
    """Log incoming requests"""
    logger.info(f"Incoming {request.method} request to {request.path}")

@app.after_request
def after_request(response):
    """Add security headers"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({
        "error": "Internal server error",
        "timestamp": datetime.utcnow().isoformat()
    }), 500

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors explicitly"""
    return jsonify({
        "error": "Endpoint not found",
        "timestamp": datetime.utcnow().isoformat()
    }), 404

# Add a health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

def get_safe_key(key):
    """
    Ensure the key meets Azure Table Storage requirements
    - Cannot contain forward slash (/)
    - Cannot begin with dot (.) or forward slash (/)
    - Must be less than 1024 bytes
    """
    if not key:
        return "unknown"
    
    # Replace invalid characters
    safe_key = key.replace('/', '_').replace('\\', '_')
    
    # Remove leading dots
    while safe_key.startswith('.'):
        safe_key = safe_key[1:]
        
    # Ensure we have a valid key
    if not safe_key:
        return "unknown"
        
    # Truncate if too long (leaving room for UTF-8 encoding)
    if len(safe_key.encode('utf-8')) > 1000:
        safe_key = safe_key[:250]  # Conservative truncation
        
    return safe_key

def is_exception_processed(problem_id, timestamp):
    """
    Check if an exception has already been processed based on timestamp
    """
    try:
        client = get_table_client()
        if not client:
            print("Table client not available - treating as not processed")
            return False

        # Parse the incoming timestamp and create the RowKey
        current_timestamp = parse(timestamp)
        row_key = current_timestamp.strftime("%Y%m%d%H%M%S")
        
        try:
            # Query for exact timestamp match using RowKey
            filter_query = f"RowKey eq '{row_key}'"
            entities = client.query_entities(filter_query)
            
            # If any matching entry exists, it's a duplicate
            if next(entities, None) is not None:
                print(f"Found existing entry for timestamp {timestamp}")
                return True
                
            print(f"No existing entry found for timestamp {timestamp}")
            return False
            
        except azure.core.exceptions.ResourceNotFoundError:
            # Table doesn't exist, ensure it's created
            client = ensure_table_exists()
            return False
        except Exception as e:
            print(f"Error querying table: {str(e)}")
            return False
            
    except Exception as e:
        print(f"Error checking exception status: {str(e)}")
        traceback.print_exc()
        return False

def mark_exception_processed(problem_id, timestamp, jira_key):
    """
    Mark an exception as processed in Azure Table
    """
    try:
        client = get_table_client()
        if not client:
            print("Failed to mark exception as processed - table client not available")
            return

        # Use timestamp as the primary key
        parsed_time = parse(timestamp)
        row_key = parsed_time.strftime("%Y%m%d%H%M%S")
        
        entity = {
            'PartitionKey': 'exceptions',
            'RowKey': row_key,
            'JiraKey': jira_key,
            'ProcessedTime': datetime.utcnow().isoformat(),
            'OriginalProblemId': problem_id,
            'OriginalTimestamp': timestamp
        }
        
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                client.upsert_entity(entity=entity)
                print(f"Successfully marked exception at {timestamp} as processed")
                return
            except azure.core.exceptions.ResourceNotFoundError:
                # Table doesn't exist, create it and retry
                print("Table not found, recreating...")
                client = ensure_table_exists()
                retry_count += 1
            except Exception as e:
                print(f"Error upserting entity (attempt {retry_count + 1}): {str(e)}")
                retry_count += 1
                
        print("Failed to mark exception as processed after all retries")
        
    except Exception as e:
        print(f"Error marking exception as processed: {str(e)}")
        traceback.print_exc()

def query_app_insights():
    """
    Query Azure Application Insights for exception data from the last 24 hours.
    Returns a list of exceptions with their details.
    """
    try:
        # Check for required App Insights credentials
        app_id = os.environ.get('APPINSIGHTS_APP_ID')
        api_key = os.environ.get('APPINSIGHTS_API_KEY')
        
        if not app_id or not api_key:
            print("ERROR: App Insights credentials not set")
            return []

        # Query to fetch exceptions with relevant fields
        query = """
        exceptions
        | where timestamp >= ago(1h)
        | project 
            timestamp,              // When the exception occurred
            problemId,             // Unique identifier for the exception
            type,                  // Exception type (e.g., NullReferenceException)
            outerMessage,          // The exception message
            customDimensions       // Additional context (environment, version, etc.)
        | order by timestamp desc  // Most recent first
        """
        
        # Make API request to App Insights
        url = f"https://api.applicationinsights.io/v1/apps/{app_id}/query"
        headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }
        
        print("\nQuerying App Insights...")
        response = requests.post(
            url,
            headers=headers,
            json={"query": query},
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"API Error: {response.text}")
            return []
            
        # Process the response
        data = response.json()
        if 'tables' not in data or not data['tables']:
            return []
            
        # Transform the data into a more usable format
        table = data['tables'][0]
        columns = [col['name'] for col in table['columns']]
        formatted_rows = []
        
        for row in table['rows']:
            row_dict = dict(zip(columns, row))
            formatted_row = [
                row_dict['timestamp'],
                row_dict['problemId'],
                {
                    'type': row_dict['type'],
                    'message': row_dict['outerMessage'],
                    'customDimensions': row_dict['customDimensions']
                }
            ]
            formatted_rows.append(formatted_row)
        
        print(f"Found {len(formatted_rows)} exceptions")
        return formatted_rows
        
    except Exception as e:
        logger.error(f"Query error: {str(e)}", exc_info=True)
        return []

def create_jira_issue(summary, description, issue_type="Bug"):
    """
    Create a Jira ticket with the given details.
    
    Args:
        summary (str): Title of the Jira ticket
        description (str): Detailed description of the issue
        issue_type (str): Type of issue (default: Bug)
    
    Returns:
        dict: Jira API response containing the created ticket details
    """
    url = f"{JIRA_URL}/rest/api/2/issue"
    
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type}
        }
    }
    
    try:
        response = requests.post(
            url,
            json=payload,
            auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN),
            headers={"Content-Type": "application/json"}
        )
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error creating Jira ticket: {str(e)}")
        if hasattr(e.response, 'text'):
            print(f"Jira API Response: {e.response.text}")
        raise

@app.route('/appget', methods=['GET'])
def get_app_insights_data():
    """
    Endpoint to fetch exception data from App Insights.
    Returns a JSON response with exception details.
    """
    print("\n=== Starting /appget request ===")
    
    try:
        exceptions = query_app_insights()
        
        response_data = {
            "count": len(exceptions),
            "exceptions": [
                {
                    "timestamp": row[0],
                    "problemId": row[1],
                    "details": row[2]
                }
                for row in exceptions
            ],
            "query_time": datetime.utcnow().isoformat()
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in endpoint: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "count": 0,
            "exceptions": [],
            "query_time": datetime.utcnow().isoformat()
        }), 500

@app.route('/trigger', methods=['POST'])
def manual_trigger():
    """
    Simple endpoint to check for new exceptions and create Jira tickets.
    No authentication or payload required.
    """
    try:
        print("\n=== Starting trigger ===")
        
        # Fetch exceptions from App Insights
        exceptions = query_app_insights()
        print(f"Number of exceptions returned: {len(exceptions)}")
        
        if not exceptions:
            return jsonify({
                "status": "completed",
                "summary": {
                    "total_exceptions": 0,
                    "tickets_created": 0,
                    "skipped": 0
                }
            })
        
        created = 0
        skipped = 0
        
        # Process each exception and create Jira tickets
        for row in exceptions:
            try:
                timestamp = row[0]
                problem_id = row[1]
                details = row[2]
                
                # Skip if already processed
                if is_exception_processed(problem_id, timestamp):
                    print(f"Skipping already processed exception {problem_id}")
                    skipped += 1
                    continue
                
                # Create Jira ticket
                description = f"""Exception Details:
-----------------
Problem ID: {problem_id}
Timestamp: {timestamp}
Type: {details['type']}

Message:
{details['message']}

Custom Dimensions:
{json.dumps(details['customDimensions'], indent=2)}

*Created by automatic exception tracking*"""

                summary = f"Exception {problem_id} at {timestamp}"
                
                # Create the Jira ticket
                jira_response = create_jira_issue(
                    summary=summary,
                    description=description
                )
                
                if jira_response and 'key' in jira_response:
                    mark_exception_processed(problem_id, timestamp, jira_response['key'])
                    created += 1
                    print(f"Created Jira ticket {jira_response['key']} for {problem_id}")
                    
            except Exception as e:
                print(f"Error processing exception: {str(e)}")
                continue

        return jsonify({
            "status": "completed",
            "summary": {
                "total_exceptions": len(exceptions),
                "tickets_created": created,
                "skipped": skipped
            }
        })
        
    except Exception as e:
        print(f"Error in trigger: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

if __name__ == '__main__':
    # Production server configuration
    from waitress import serve
    port = int(os.environ.get('PORT', 5000))
    serve(app, host='0.0.0.0', port=port, threads=4)
