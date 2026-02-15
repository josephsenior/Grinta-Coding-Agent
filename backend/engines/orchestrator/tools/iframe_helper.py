"""Helper functions for making web applications iframe-friendly.

This module provides utilities for configuring web applications created by agents
to work better within iframes, particularly in the Forge interactive browser.
"""

from __future__ import annotations

from typing import Any


def add_iframe_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Add headers that make a web application more iframe-friendly.

    Args:
        headers: Existing headers dictionary to update, or None for new dict

    Returns:
        Updated headers dictionary with iframe-friendly headers

    """
    if headers is None:
        headers = {}

    # Allow the application to be embedded in iframes from localhost
    headers["X-Frame-Options"] = "SAMEORIGIN"
    headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' localhost:* 127.0.0.1:*"
    )

    # Remove any existing X-Frame-Options that might block iframe embedding
    headers.pop("X-Frame-Options", None)

    return headers


def get_flask_iframe_config() -> dict[str, Any]:
    """Get Flask configuration for iframe-friendly applications.

    Returns:
        Dictionary of Flask configuration options

    """
    return {
        "SEND_FILE_MAX_AGE_DEFAULT": 0,  # Disable caching for development
        "TEMPLATES_AUTO_RELOAD": True,  # Auto-reload templates
        "EXPLAIN_TEMPLATE_LOADING": False,
    }


def get_fastapi_iframe_config() -> dict[str, Any]:
    """Get FastAPI configuration for iframe-friendly applications.

    Returns:
        Dictionary of FastAPI configuration options

    """
    return {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


def create_iframe_friendly_app(app_type: str = "flask", port: int = 8000) -> str:
    """Generate code for an iframe-friendly web application.

    Args:
        app_type: Type of application ("flask" or "fastapi")
        port: Port number for the application

    Returns:
        Python code string for the iframe-friendly application

    """
    if app_type.lower() == "flask":
        config_dict = get_flask_iframe_config()
        return f"""from flask import Flask, render_template_string, request, jsonify
import os

app = Flask(__name__)

# Configure for iframe embedding
app.config.update({config_dict})

@app.after_request
def after_request(response):
    \"\"\"Add security headers to allow iframe embedding from localhost.

    Args:
        response: The Flask response object to modify.

    Returns:
        Response: The modified response with iframe-friendly headers.
    \"\"\"
    # Add headers to allow iframe embedding from localhost
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'self' localhost:* 127.0.0.1:*"
    return response

@app.route('/')
def home():
    \"\"\"Render the main application homepage.

    Returns:
        str: HTML content for the application homepage with iframe-friendly styling.
    \"\"\"
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent App</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            text-align: center;
        }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }}
        p {{
            font-size: 1.2rem;
            margin-bottom: 2rem;
            opacity: 0.9;
        }}
        .status {{
            background: rgba(255, 255, 255, 0.1);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Agent Application</h1>
        <p>This application was created by the Forge agent and is designed to work in iframes.</p>
        <div class="status">
            <h3>Status: Running</h3>
            <p>Port: {port}</p>
            <p>Iframe-friendly: ✅ Yes</p>
        </div>
    </div>
</body>
</html>
    '''

@app.route('/api/status')
def status():
    \"\"\"Return the application status information.

    Returns:
        Response: JSON response containing application status, port, and iframe compatibility.
    \"\"\"
    return jsonify({{
        'status': 'running',
        'port': {port},
        'iframe_friendly': True
    }})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port={port}, debug=True)
"""

    if app_type.lower() == "fastapi":
        fastapi_config = get_fastapi_iframe_config()
        return f"""from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(**{fastapi_config})

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_iframe_headers(request: Request, call_next):
    response = await call_next(request)
    # Add headers to allow iframe embedding from localhost
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self' localhost:* 127.0.0.1:*"
    return response

@app.get("/", response_class=HTMLResponse)
async def home():
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent App</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            text-align: center;
        }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }}
        p {{
            font-size: 1.2rem;
            margin-bottom: 2rem;
            opacity: 0.9;
        }}
        .status {{
            background: rgba(255, 255, 255, 0.1);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Agent Application</h1>
        <p>This application was created by the Forge agent and is designed to work in iframes.</p>
        <div class="status">
            <h3>Status: Running</h3>
            <p>Port: {port}</p>
            <p>Iframe-friendly: ✅ Yes</p>
        </div>
    </div>
</body>
</html>
    '''

@app.get("/api/status")
async def status():
    return {{
        "status": "running",
        "port": {port},
        "iframe_friendly": True
    }}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port={port})
"""

    msg = f"Unsupported app_type: {app_type}. Use 'flask' or 'fastapi'."
    raise ValueError(msg)


def get_iframe_tips() -> str:
    """Get tips for making web applications iframe-friendly.

    Returns:
        String with tips and best practices

    """
    return """
Tips for making web applications iframe-friendly:

1. Headers to set:
   - X-Frame-Options: SAMEORIGIN (allows same-origin embedding)
   - Content-Security-Policy: frame-ancestors 'self' localhost:* 127.0.0.1:*

2. For Flask applications:
   - Use @app.after_request decorator to add headers
   - Configure app.config for development

3. For FastAPI applications:
   - Use middleware to add headers
   - Add CORS middleware for cross-origin requests

4. Common issues:
   - Some sites block iframe embedding by default
   - CORS policies may restrict access
    - JavaScript may not work properly in restricted iframes

5. Testing:
   - Test in the Forge interactive browser
   - Use "Open in new tab" if iframe fails
   - Check browser console for errors
"""
