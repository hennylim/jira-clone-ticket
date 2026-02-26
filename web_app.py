from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer
import json
import os
from pathlib import Path
import uvicorn
from typing import List, Optional
from pydantic import BaseModel, EmailStr, HttpUrl, ConfigDict
from sqlalchemy.orm import Session
import base64

# Import custom modules
import auth
import models
import crypto_utils

# Initialize database
models.init_db()

# In-memory session key storage (Username -> Derived Encryption Key)
# This is lost on server restart, forcing users to re-login to access Jira
USER_SESSION_KEYS = {}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def get_db():
    db = models.SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = auth.decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

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
class UserRegister(BaseModel):
    username: str
    password: str
    jira_base_url: str
    jira_email: str
    jira_api_token: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class SearchRequest(BaseModel):
    config: dict

class CloneRequest(BaseModel):
    config: dict
    selected_issue_keys: List[str]

class SaveConfigRequest(BaseModel):
    config: dict
    filename: Optional[str] = "config.json"

class ConfigSave(BaseModel):
    name: str
    content: dict

class ConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    content: dict

class UserResponse(BaseModel):
    username: str

class UserProfile(BaseModel):
    username: str
    jira_base_url: str
    jira_email: str

class ProfileUpdate(BaseModel):
    current_password: str
    new_password: Optional[str] = None
    jira_base_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None

@app.post("/api/auth/register")
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    # Check if user exists
    db_user = db.query(models.User).filter(models.User.username == user_data.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Hash password
    hashed_pwd = auth.get_password_hash(user_data.password)
    
    # Encrypt Jira info
    salt = crypto_utils.generate_salt()
    jira_info = {
        "base_url": user_data.jira_base_url,
        "email": user_data.jira_email,
        "api_token": user_data.jira_api_token
    }
    # Derive key for initial encryption
    derived_key_for_storage = crypto_utils.derive_key(user_data.password, base64.b64decode(salt))
    encrypted_info = crypto_utils.encrypt_with_key(derived_key_for_storage, jira_info)
    
    # Create user
    new_user = models.User(
        username=user_data.username,
        hashed_password=hashed_pwd,
        encrypted_jira_info=encrypted_info,
        crypto_salt=salt
    )
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/api/auth/login", response_model=Token)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == user_data.username).first()
    if not user or not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    # Securely derive and cache the encryption key for this session
    # This prevents storing the plain-text password or encryption key in the database
    derived_key = crypto_utils.derive_key(user_data.password, base64.b64decode(user.crypto_salt))
    USER_SESSION_KEYS[user.username] = derived_key
    
    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/profile", response_model=UserProfile)
async def get_profile(current_user: models.User = Depends(get_current_user)):
    # Decrypt jira info to show base_url and email
    # We use the session key cached during login
    if current_user.username not in USER_SESSION_KEYS:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    
    derived_key = USER_SESSION_KEYS[current_user.username]
    try:
        jira_info = crypto_utils.decrypt_with_key(derived_key, current_user.encrypted_jira_info)
        return {
            "username": current_user.username,
            "jira_base_url": jira_info.get("base_url", ""),
            "jira_email": jira_info.get("email", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt profile: {str(e)}")

@app.put("/api/auth/profile")
async def update_profile(user_data: ProfileUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 1. Verify current password
    if not auth.verify_password(user_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect current password")
    
    # 2. Get current jira info (decrypt with old key/password)
    derived_key = crypto_utils.derive_key(user_data.current_password, base64.b64decode(current_user.crypto_salt))
    try:
        jira_info = crypto_utils.decrypt_with_key(derived_key, current_user.encrypted_jira_info)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt existing Jira credentials")
    
    # 3. Update jira info fields
    if user_data.jira_base_url:
        jira_info["base_url"] = user_data.jira_base_url
    if user_data.jira_email:
        jira_info["email"] = user_data.jira_email
    if user_data.jira_api_token:
        jira_info["api_token"] = user_data.jira_api_token
    
    # 4. Handle password change and re-encryption
    new_password = user_data.new_password if user_data.new_password else user_data.current_password
    
    if user_data.new_password:
        # Update hashed password
        current_user.hashed_password = auth.get_password_hash(user_data.new_password)
        # Generate new salt for extra security on password change
        new_salt = crypto_utils.generate_salt()
        current_user.crypto_salt = new_salt
        # Derived new key
        new_key = crypto_utils.derive_key(new_password, base64.b64decode(new_salt))
    else:
        # Keep same salt and derive key
        new_key = crypto_utils.derive_key(new_password, base64.b64decode(current_user.crypto_salt))
    
    # 5. Encrypt with "new" key (which might be the same if password didn't change)
    encrypted_info = crypto_utils.encrypt_with_key(new_key, jira_info)
    current_user.encrypted_jira_info = encrypted_info
    
    # 6. Update session key
    USER_SESSION_KEYS[current_user.username] = new_key
    
    db.commit()
    return {"message": "Profile updated successfully"}

@app.get("/api/auth/me", response_model=UserResponse)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return {"username": current_user.username}

def get_jira_client_for_user(user: models.User, derived_key: bytes):
    """Function to decrypt credentials and get client using a derived key."""
    try:
        jira_info = crypto_utils.decrypt_data(derived_key, user.encrypted_jira_info)
        return jira_clone_tool.JiraClient.JiraClient(
            jira_info['base_url'],
            jira_info['email'],
            jira_info['api_token']
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Failed to decrypt Jira credentials: {str(e)}")

@app.post("/api/search")
async def search(request: SearchRequest, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    derived_key = USER_SESSION_KEYS.get(current_user.username)
    if not derived_key:
        raise HTTPException(status_code=401, detail="Session expired or Jira access not initialized. Please re-login.")

    config = request.config
    jql = config.get("jql")
    issue_key = config.get("issue_key")
    
    if not (jql or issue_key):
        raise HTTPException(status_code=400, detail="jql or issue_key is required")
    
    try:
        jira_client = get_jira_client_for_user(current_user, derived_key)
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
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clone")
async def clone(request: CloneRequest, current_user: models.User = Depends(get_current_user)):
    derived_key = USER_SESSION_KEYS.get(current_user.username)
    if not derived_key:
        raise HTTPException(status_code=401, detail="Session expired or Jira access not initialized. Please re-login.")

    config = request.config
    selected_issue_keys = request.selected_issue_keys
    
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
        jira_client = get_jira_client_for_user(current_user, derived_key)
        
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

# Configuration Management Endpoints
@app.post("/api/configs", response_model=ConfigResponse)
async def save_db_config(config_data: ConfigSave, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        new_config = models.Configuration(
            user_id=current_user.id,
            name=config_data.name,
            content=json.dumps(config_data.content)
        )
        db.add(new_config)
        db.commit()
        db.refresh(new_config)
        return {
            "id": new_config.id,
            "name": new_config.name,
            "content": json.loads(new_config.content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/configs", response_model=List[ConfigResponse])
async def list_db_configs(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    configs = db.query(models.Configuration).filter(models.Configuration.user_id == current_user.id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "content": json.loads(c.content)
        } for c in configs
    ]

@app.get("/api/configs/{config_id}", response_model=ConfigResponse)
async def get_db_config(config_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = db.query(models.Configuration).filter(
        models.Configuration.id == config_id,
        models.Configuration.user_id == current_user.id
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return {
        "id": config.id,
        "name": config.name,
        "content": json.loads(config.content)
    }

@app.delete("/api/configs/{config_id}")
async def delete_db_config(config_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = db.query(models.Configuration).filter(
        models.Configuration.id == config_id,
        models.Configuration.user_id == current_user.id
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    db.delete(config)
    db.commit()
    return {"message": "Configuration deleted"}

@app.put("/api/configs/{config_id}", response_model=ConfigResponse)
async def update_db_config(config_id: int, config_data: ConfigSave, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = db.query(models.Configuration).filter(
        models.Configuration.id == config_id,
        models.Configuration.user_id == current_user.id
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    config.name = config_data.name
    config.content = json.dumps(config_data.content)
    db.commit()
    db.refresh(config)
    return {
        "id": config.id,
        "name": config.name,
        "content": json.loads(config.content)
    }

# Note: This endpoint is deprecated as "Save Config" is now handled client-side via browser download.
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

@app.get("/login", response_class=HTMLResponse)
async def get_login():
    login_path = static_dir / "login.html"
    if login_path.exists():
        return login_path.read_text()
    return "<h1>Jira Clone Tool Login</h1><p>Frontend files missing. Please create static/login.html</p>"

@app.get("/profile.html", response_class=HTMLResponse)
async def get_profile_page():
    profile_path = static_dir / "profile.html"
    if profile_path.exists():
        return profile_path.read_text()
    return "<h1>User Profile</h1><p>Frontend files missing. Please create static/profile.html</p>"

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
