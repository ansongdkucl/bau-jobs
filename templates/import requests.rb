import requests
import base64

# Authentication using Basic Auth or Personal Access Token
username = os.environ['username']
password = 'yorWFi39qYau8xPPbHLNacpQMoKiQnjIQ9yao5PSdUDwKrPdDy'  # or Personal Access Token

# Base64 encode credentials
credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

headers = {
    'Authorization': f'Basic {credentials}',
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

# API endpoints - replace with your instance
base_url = "https://myservices-isd.uk.4me.com/v1"  # or your specific instance URL