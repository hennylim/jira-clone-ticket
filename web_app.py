from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import json
import os
from pathlib import Path
import uvicorn
from typing import List, Optional
from pydantic import BaseModel

# Import functions from the refactored script
import importlib.util
import sys

# Dynamic import to handle the script name with hyphens
script_path = Path(__file__).parent / "jira-clone-ticket-new.py"
spec = importlib.util.spec_from_file_location("jira_clone_tool", script_path)
jira_clone_tool = importlib.util.module_from_spec(spec)
sys.modules["jira_clone_tool"] = jira_clone_tool
spec.loader.exec_module(jira_clone_tool)

app = FastAPI(title="Jira Clone Ticket Web UI")

# Models for API
class SearchRequest(BaseModel):
    config: dict

class CloneRequest(BaseModel):
    config: dict
    selected_issue_keys: List[str]

class SaveConfigRequest(BaseModel):
    config: dict
    filename: Optional[str] = "config.json"

@app.post("/api/search")
async def search(request: SearchRequest):
    config = request.config
    jql = config.get("jql")
    issue_key = config.get("issue_key")
    env_path = config.get("env", ".env")
    
    if not (jql or issue_key):
        raise HTTPException(status_code=400, detail="jql or issue_key is required")
    
    try:
        jira_client = jira_clone_tool.get_jira_client(env_path)
        issues = jira_clone_tool.search_issues(jira_client, jql=jql, issue_key=issue_key)
        
        # Format issues for frontend
        formatted_issues = []
        for issue in issues:
            formatted_issues.append({
                "key": issue.get("key"),
                "summary": issue.get("fields", {}).get("summary"),
                "status": issue.get("fields", {}).get("status", {}).get("name")
            })
        return {"issues": formatted_issues, "base_url": jira_client.base_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clone")
async def clone(request: CloneRequest):
    config = request.config
    selected_issue_keys = request.selected_issue_keys
    
    env_path = config.get("env", ".env")
    clone_project_key = config.get("clone_project_key")
    issue_type = config.get("issue_type")
    due_date = config.get("due_date")
    clone_label = config.get("clone_label")
    clone_models = config.get("clone_models")
    parent_key = config.get("parent_key")

    if isinstance(clone_label, str):
        clone_label = [label for label in clone_label.split() if label]
    if isinstance(clone_models, str):
        clone_models = [label for label in clone_models.split() if label]

    due_date = jira_clone_tool.process_due_date_str(due_date)

    try:
        jira_client = jira_clone_tool.get_jira_client(env_path)
        
        # Get full issue objects for selected keys
        selected_issues = []
        for key in selected_issue_keys:
            issue = jira_client.get_issue(key)
            if issue:
                selected_issues.append(issue)
        
        results = jira_clone_tool.perform_clone(
            jira_client, 
            selected_issues, 
            clone_project_key, 
            issue_type, 
            due_date, 
            clone_label, 
            clone_models, 
            parent_key
        )
        return {"results": results, "base_url": jira_client.base_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/save")
async def save_config(request: SaveConfigRequest):
    config = request.config
    filename = request.filename or "config.json"
    
    # Security: ensure we are only writing to the current project directory and not escaping
    target_path = Path(__file__).parent / filename
    if not target_path.absolute().is_relative_to(Path(__file__).parent):
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return {"status": "success", "message": f"Configuration saved to {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Static files mapping
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return index_path.read_text()
    return "<h1>Jira Clone Tool Web UI</h1><p>Frontend files missing. Please create static/index.html</p>"

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
