#!/usr/bin/env python3
"""
ARM API Documentation Generator

This script auto-generates API documentation from endpoint docstrings.
Run: python scripts/generate_api_docs.py

Output: docs/API.md or specified file
"""

import os
import sys
import inspect
from datetime import datetime

# Add arm to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import API modules
from arm.ui.api import api
from arm.ui.api import jobs, tracks, system, settings, metadata, notifications, logs, history, send, database, user


def get_blueprint_routes(blueprint):
    """Get all routes from a Flask blueprint."""
    routes = []
    for rule in blueprint.url_map.iter_rules():
        if rule.endpoint.startswith(blueprint.name):
            methods = [m for m in rule.methods if m not in ['HEAD', 'OPTIONS']]
            routes.append({
                'endpoint': rule.endpoint,
                'path': rule.rule,
                'methods': methods,
                'blueprint': blueprint.name
            })
    return routes


def get_docstring(func):
    """Extract cleaned docstring from function."""
    if func.__doc__:
        doc = inspect.cleandoc(func.__doc__)
        return doc
    return "No description available."


def get_blueprint_doc(blueprint):
    """Get blueprint module docstring."""
    module = sys.modules.get(f'arm.ui.api.{blueprint.name}')
    if module and module.__doc__:
        return inspect.cleandoc(module.__doc__)
    return f"{blueprint.name.capitalize()} API Endpoints"


def generate_endpoint_docs():
    """Generate markdown documentation from API endpoints."""
    
    modules = {
        'jobs': (jobs, 'Job Management', 'Manage ripping jobs, tracks, and metadata'),
        'tracks': (tracks, 'Track Management', 'Manage disc tracks'),
        'system': (system, 'System & Drives', 'System information, drive management, and status'),
        'settings': (settings, 'Settings', 'ARM configuration and settings'),
        'metadata': (metadata, 'Metadata', 'Search and retrieve metadata from OMDB/TMDB'),
        'notifications': (notifications, 'Notifications', 'View and manage notifications'),
        'logs': (logs, 'Logs', 'View and read log files'),
        'history': (history, 'History', 'View completed job history and statistics'),
        'send': (send, 'Send/Export', 'Send data to external APIs'),
        'database': (database, 'Database', 'Database operations and migrations'),
        'user': (user, 'User', 'User management and authentication'),
    }
    
    doc = f"""# ARM REST API Documentation

## Overview

The Automatic Ripping Machine (ARM) provides a comprehensive REST API that enables external applications—such as mobile apps, web UIs, and automation tools—to interact with ARM programmatically.

**Auto-generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

### Base URL

```
http://your-arm-server:8000/api/v1
```

---

## Authentication

ARM supports session-based and Bearer token authentication.

### Bearer Token

```http
Authorization: Bearer YOUR_API_KEY
```

Set `ARM_API_KEY` in your `arm.yaml` config file.

---

## Endpoints

"""
    for name, (module, title, desc) in modules.items():
        doc += f"\n### {title}\n\n{desc}\n\n"
        doc += "| Method | Endpoint | Description |\n"
        doc += "|--------|----------|-------------|\n"
        
        for route in get_blueprint_routes(module.api):
            func_name = route['endpoint'].split('.')[-1]
            endpoint_path = f"/{route['blueprint']}{route['path']}" if route['path'] != '/' else f"/{route['blueprint']}"
            doc += f"| {', '.join(route['methods']).upper()} | `{endpoint_path}` | {func_name} |\n"
        
        doc += "\n"
    
    doc += """
---

## Response Format

### Success

```json
{
    "success": true,
    "data": {...},
    "message": "Optional message"
}
```

### Error

```json
{
    "success": false,
    "error": "Error message",
    "message": "Error message"
}
```

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Internal Error |

---

*This documentation was auto-generated from endpoint docstrings.*
"""
    return doc


def main():
    """Main entry point."""
    # Generate docs
    docs = generate_endpoint_docs()
    
    # Output to file or stdout
    output_path = os.environ.get('API_DOC_OUTPUT', 'API.md')
    
    with open(output_path, 'w') as f:
        f.write(docs)
    
    print(f"API documentation generated: {output_path}")
    print(f"Size: {len(docs)} bytes")


if __name__ == '__main__':
    main()
