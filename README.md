# JiraBug - Application Insights to Jira Integration

JiraBug is a Flask-based service that bridges Azure Application Insights with Jira, automatically creating Jira tickets based on application exceptions.

## Features

- Automatic Jira ticket creation from App Insights exceptions
- Exception querying from Application Insights
- Manual trigger support for exception processing
- Real-time exception monitoring

## Configuration

### Required Environment Variables

```env
APPINSIGHTS_APP_ID=your_app_insights_id
APPINSIGHTS_API_KEY=your_api_key
JIRA_TOKEN=your_jira_api_token
JIRA_EMAIL=your_jira_email
JIRA_URL=your_jira_instance_url
JIRA_PROJECT=your_project_key
AZURE_CONNECTION_STRING=your_azure_storage_connection_string
```

## API Endpoints

### 1. Query App Insights Exceptions (GET `/appget`)

Retrieves exceptions from the last 24 hours:

```bash
GET http://your-server:5000/appget
```

Response format:
```json
{
    "count": 10,
    "exceptions": [
        {
            "timestamp": "2024-01-20T10:30:00Z",
            "problemId": "PROB123",
            "details": {
                "type": "NullReferenceException",
                "message": "Object reference not set",
                "customDimensions": {}
            }
        }
    ],
    "query_time": "2024-01-20T15:30:00Z"
}
```

### 2. Manual Exception Processing (POST `/trigger`)

Manually triggers exception processing from App Insights to Jira:

```bash
POST http://your-server:5000/trigger
```

Response format:
```json
{
    "status": "completed",
    "summary": {
        "total_exceptions": 10,
        "tickets_created": 3,
        "errors": 0
    },
    "error_details": null,
    "timestamp": "2024-01-20T15:30:00Z"
}
```

## Usage Examples

### 1. Checking recent exceptions:
```bash
curl http://your-server:5000/appget
```

### 2. Manually triggering exception processing:
```bash
curl -X POST http://your-server:5000/trigger
```

## Installation

1. Clone the repository
2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   .\venv\Scripts\activate   # Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set environment variables
5. Run the application:
   ```bash
   python app.py
   ```

## Docker Deployment

1. Build the image:
   ```bash
   docker build -t jirabug .
   ```

2. Run the container:
   ```bash
   docker run -p 5000:5000 \
     -e APPINSIGHTS_APP_ID=your_id \
     -e APPINSIGHTS_API_KEY=your_key \
     -e JIRA_TOKEN=your_token \
     -e JIRA_EMAIL=your_email \
     -e JIRA_URL=your_url \
     -e JIRA_PROJECT=your_project \
     -e AZURE_CONNECTION_STRING=your_storage_connection_string \
     jirabug
   ```

## Error Handling

### Common Issues:

1. Jira Connection Issues:
   - Verify JIRA_EMAIL and JIRA_TOKEN are correct
   - Check Jira API permissions

2. App Insights Issues:
   - Verify APPINSIGHTS_APP_ID and APPINSIGHTS_API_KEY
   - Test using `/appget` endpoint
   - Check query timeframe

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request with detailed description
