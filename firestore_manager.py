# firestore_manager.py
"""
Firestore/Storage integration for persisting projects.
- No per-user filtering.
- Debounced saves.
- Offloads 'products_data' AND 'filter_options' to JSON in Storage.
- OPTIMIZED: Assumes Public Bucket (allUsers=Viewer).
- NEW: AUTO-REPAIR feature fixes broken 'gs://' links from old uploads on the fly.
"""

from __future__ import annotations

import os
import time
import json
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st
from google.cloud import firestore, storage
from google.oauth2 import service_account

# =========================
# Small utilities
# =========================

def _blob_path_from_url(url: str, bucket_name: str) -> Optional[str]:
    if not isinstance(url, str): return None
    u = url.strip().split('?')[0]
    if not u: return None
    
    # Handle gs:// format
    if u.startswith("gs://"):
        rest = u[len("gs://"):]
        if "/" in rest and rest.split("/", 1)[0] == bucket_name:
            return rest.split("/", 1)[1]
            
    # Handle https:// format
    if "storage.googleapis.com" in u:
        try:
            decoded = urllib.parse.unquote(u)
            after = decoded.split("storage.googleapis.com/", 1)[1]
            parts = after.split("/", 1)
            if parts[0] == bucket_name:
                return parts[1]
        except: pass
    return None

def _normalize_pem(pem: str) -> str:
    pem = (pem or "").replace("\r", "")
    if "\\n" in pem and "\n" not in pem: pem = pem.replace("\\n", "\n")
    return pem.strip()


# =========================
# Core Manager
# =========================

class ProjectFirestoreManager:
    def __init__(self, *, firebase_config_json_path=None, creds=None, project_id=None, bucket_name=None):
        if firebase_config_json_path:
            self.db = firestore.Client.from_service_account_json(firebase_config_json_path)
            self.storage_client = storage.Client.from_service_account_json(firebase_config_json_path)
        elif creds and project_id:
            self.db = firestore.Client(credentials=creds, project=project_id)
            self.storage_client = storage.Client(credentials=creds, project=project_id)
        else:
            raise ValueError("Invalid Firebase Config")
        
        if not bucket_name: raise ValueError("bucket_name is required")
        self.bucket_name = bucket_name
        self.collection_name = "projects"
        self._saving_in_progress = False

    def _bucket(self): return self.storage_client.bucket(self.bucket_name)
    def _image_blob_path(self, pid, name): return f"projects/{pid}/images/{name}"
    def _excel_blob_path(self, pid, name): return f"projects/{pid}/{name}"

    def _upload_bytes(self, blob_path, data, content_type):
        """Uploads bytes and returns a valid HTTPS URL. assumes bucket is public."""
        blob = self._bucket().blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        return f"https://storage.googleapis.com/{self.bucket_name}/{urllib.parse.quote(blob_path)}"

    def _download_blob_bytes(self, blob_path):
        try: return self._bucket().blob(blob_path).download_as_bytes()
        except: return None

    # ---------- CRUD ----------

def save_project(self, project_id: str, project_data: Dict) -> bool | Dict:
        if self._saving_in_progress: return False
        self._saving_in_progress = True

        try:
            # 1. Prepare Base Data
            firestore_data = {
                "id": project_id,
                "name": project_data.get("name", ""),
                "description": project_data.get("description", ""),
                "created_date": project_data.get("created_date", datetime.now().isoformat()),
                "last_modified": datetime.now().isoformat(),
                "attributes": project_data.get("attributes", []),
                "distributions": project_data.get("distributions", []),
                "filter_options": {}, 
                "pending_changes": project_data.get("pending_changes", {}),
                "excel_filename": project_data.get("excel_filename"),
            }

            # 2. Get Old Mappings (To identify what needs deletion)
            old_mappings_raw = project_data.get("image_mappings", {})
            old_mappings = {}
            for k, v in old_mappings_raw.items():
                key = str(k).lower().strip()
                if isinstance(v, dict): old_mappings[key] = v
                elif isinstance(v, str): old_mappings[key] = {"public_url": v}

            # 3. Process Current Products & Build New Mappings
            new_mappings = {}
            products_for_storage = []
            
            for product in project_data.get("products_data", []):
                pcopy = dict(product)
                img_info = pcopy.pop("image_data", None)
                pid_lower = str(pcopy.get("product_id", "")).lower().strip()

                # A. Handle New Uploads (Bytes)
                if img_info and (isinstance(img_info, bytes) or isinstance(img_info, tuple)):
                    if isinstance(img_info, tuple): image_name, img_bytes = img_info
                    else: img_bytes = img_info; image_name = f"{pcopy.get('product_id', 'unnamed')}.png"
                    
                    blob_path = self._image_blob_path(project_id, image_name)
                    content_type = "image/png" if image_name.lower().endswith(".png") else "image/jpeg"
                    base_url = self._upload_bytes(blob_path, img_bytes, content_type)
                    
                    pcopy["image_url"] = f"{base_url}?t={int(time.time())}"
                    new_mappings[pid_lower] = {"blob_path": blob_path, "public_url": pcopy["image_url"]}

                # B. Handle Existing URLs (Preserve mapping)
                elif pid_lower in old_mappings:
                    # If the product still exists and has no new upload, keep the old mapping
                    new_mappings[pid_lower] = old_mappings[pid_lower]
                    # Ensure the product URL matches the mapping
                    if "public_url" in new_mappings[pid_lower]:
                        pcopy["image_url"] = new_mappings[pid_lower]["public_url"]

                products_for_storage.append(pcopy)

            # 4. Garbage Collection (Delete Orphaned Images)
            # Compare Old vs New. If it was in Old but NOT in New, delete it.
            for pid, old_meta in old_mappings.items():
                # Case 1: Product completely deleted
                if pid not in new_mappings:
                    path = old_meta.get("blob_path")
                    if path:
                        try: self._bucket().blob(path).delete()
                        except: pass
                
                # Case 2: Product exists, but image was replaced (Blob path changed)
                elif pid in new_mappings:
                    old_path = old_meta.get("blob_path")
                    new_path = new_mappings[pid].get("blob_path")
                    if old_path and new_path and old_path != new_path:
                        try: self._bucket().blob(old_path).delete()
                        except: pass

            # 5. Offload Large Data
            try:
                large_data_payload = {
                    "products": products_for_storage,
                    "filter_options": project_data.get("filter_options", {})
                }
                products_json = json.dumps(large_data_payload)
                json_path = f"projects/{project_id}/products_data.json"
                self._upload_bytes(json_path, products_json.encode('utf-8'), "application/json")
                
                firestore_data["products_blob_path"] = json_path
                firestore_data["products_data"] = [] 
                firestore_data["product_count"] = len(products_for_storage) 
            except Exception as e:
                st.error(f"Failed to upload data file: {e}")
                return False

            firestore_data["image_mappings"] = new_mappings

            # 6. Excel
            excel_bytes = project_data.get("excel_file_data")
            if excel_bytes:
                name = project_data.get("excel_filename") or "grid.xlsx"
                path = self._excel_blob_path(project_id, name)
                url = self._upload_bytes(path, excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                firestore_data["excel_blob_path"] = path
                firestore_data["excel_url"] = url

            self.db.collection(self.collection_name).document(project_id).set(firestore_data)
            return new_mappings

        except Exception as e:
            st.error(f"Error saving: {e}")
            return False
        finally:
            self._saving_in_progress = False

    def load_project(self, project_id: str) -> Optional[Dict]:
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if not doc.exists: return None
            data = doc.to_dict() or {}

            # 1. Load Offloaded Data
            blob_path = data.get("products_blob_path")
            if blob_path:
                json_bytes = self._download_blob_bytes(blob_path)
                if json_bytes:
                    loaded_json = json.loads(json_bytes.decode('utf-8'))
                    if isinstance(loaded_json, dict) and "products" in loaded_json:
                        data["products_data"] = loaded_json["products"]
                        if "filter_options" in loaded_json:
                            data["filter_options"] = loaded_json["filter_options"]
                    elif isinstance(loaded_json, list):
                        data["products_data"] = loaded_json
                else:
                    data["products_data"] = []
            else:
                if "products_data" not in data: data["products_data"] = []

            # 2. Restore URLs
            img_map = data.get("image_mappings", {})
            url_lookup = {}
            for k, v in img_map.items():
                if isinstance(v, dict) and "public_url" in v: url_lookup[k] = v["public_url"]
                elif isinstance(v, str): url_lookup[k] = v

            # 3. SELF-HEALING & AUTO-REPAIR
            # This loops through every product. If the URL is missing OR looks like "gs://", 
            # it reconstructs a valid https URL on the fly.
            for p in data["products_data"]:
                pid = str(p.get("product_id", "")).lower().strip()
                
                # Check mapping first
                mapped_url = url_lookup.get(pid)
                
                # If no mapping, check the product's saved URL
                if not mapped_url:
                    mapped_url = p.get("image_url")
                
                # --- THE REPAIR LOGIC ---
                if mapped_url:
                    # If it's a gs:// link (broken for browsers), fix it to https
                    if mapped_url.startswith("gs://"):
                        # Extract the path part: gs://bucket-name/projects/... -> projects/...
                        try:
                            clean_path = mapped_url.replace(f"gs://{self.bucket_name}/", "")
                            mapped_url = f"https://storage.googleapis.com/{self.bucket_name}/{urllib.parse.quote(clean_path)}"
                        except:
                            pass # Keep original if parse fails

                    # Save the fixed URL to the product object for display
                    p["image_url"] = mapped_url
                    
                    # (Optional) Update lookup so we stay consistent in this session
                    url_lookup[pid] = mapped_url
                
                p.pop("image_data", None)

            data["image_mappings"] = img_map
            data.pop("uploaded_images", None)
            return data
        except Exception as e:
            st.error(f"Error loading: {e}"); return None

    def list_projects(self) -> List[Dict]:
        try:
            docs = self.db.collection(self.collection_name).stream()
            items = []
            for d in docs:
                v = d.to_dict() or {}
                count = v.get("product_count", len(v.get("products_data", [])))
                items.append({
                    "id": v.get("id"),
                    "name": v.get("name", ""),
                    "description": v.get("description", ""),
                    "created_date": v.get("created_date", ""),
                    "last_modified": v.get("last_modified", ""),
                    "num_products": count,
                    "num_attributes": len(v.get("attributes", [])),
                    "num_pending_changes": len(v.get("pending_changes", {})),
                })
            return sorted(items, key=lambda x: x.get("last_modified", ""), reverse=True)
        except Exception as e:
            st.error(f"Error listing: {e}"); return []

    def delete_project(self, project_id: str) -> bool:
        try:
            # 1. Delete ALL Storage Files under projects/{project_id}/
            # In Google Cloud Storage, "folders" are just prefixes. 
            # We list every blob starting with this project's ID and delete it.
            prefix = f"projects/{project_id}/"
            blobs = list(self._bucket().list_blobs(prefix=prefix))
            
            for blob in blobs:
                try:
                    blob.delete()
                except Exception:
                    pass # Continue deleting other files even if one fails

            # 2. Delete the Firestore Document
            self.db.collection(self.collection_name).document(project_id).delete()
            return True
            
        except Exception as e:
            st.error(f"Error deleting: {e}")
            return False

# =========================
# App Integration Helpers
# =========================

def integrate_with_streamlit_app() -> Optional[ProjectFirestoreManager]:
    if "firestore_manager" in st.session_state and st.session_state.firestore_manager:
        return st.session_state.firestore_manager

    try:
        if os.path.exists("serviceAccount.json"):
            bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET") or st.secrets.get("firebase", {}).get("bucket_name")
            if not bucket_name:
                st.error("Missing bucket_name.")
                st.stop()
            mgr = ProjectFirestoreManager(
                firebase_config_json_path="serviceAccount.json",
                bucket_name=bucket_name,
            )
            st.session_state.firestore_manager = mgr
            return mgr

        if "firebase" in st.secrets:
            fb = dict(st.secrets["firebase"])
            try:
                fb["private_key"] = _normalize_pem(str(fb["private_key"]))
                creds = service_account.Credentials.from_service_account_info(fb)
            except Exception as e:
                 st.error(f"Firebase Credentials Error: {e}")
                 st.stop()

            mgr = ProjectFirestoreManager(
                creds=creds,
                project_id=fb["project_id"],
                bucket_name=fb["bucket_name"],
            )
            st.session_state.firestore_manager = mgr
            return mgr

        st.warning("⚠️ Firebase credentials not configured.")
        st.stop()

    except Exception as e:
        st.error(f"❌ Firebase init failed: {e}")
        st.exception(e)
        st.session_state.firestore_manager = None
        return None

def load_project_summaries_from_cloud() -> int:
    mgr: ProjectFirestoreManager = st.session_state.get("firestore_manager")
    if not mgr:
        st.session_state.project_summaries = []
        return 0
    summaries = mgr.list_projects()
    st.session_state.project_summaries = summaries or []
    return len(st.session_state.project_summaries)

def ensure_project_loaded(project_id: str) -> bool:
    if "projects" not in st.session_state: st.session_state.projects = {}
    if project_id in st.session_state.projects: return True

    mgr: ProjectFirestoreManager = st.session_state.get("firestore_manager")
    if not mgr: return False
    
    with st.spinner(f"Loading project {project_id}..."):
        data = mgr.load_project(project_id)
        if not data:
            st.error("Failed to load project from Firestore.")
            return False
        st.session_state.projects[project_id] = data
        return True

def save_current_project_to_cloud() -> bool | Dict:
    mgr: ProjectFirestoreManager = st.session_state.get("firestore_manager")
    proj_id: Optional[str] = st.session_state.get("current_project")
    if not mgr or not proj_id: return False
    project = st.session_state.projects.get(proj_id)
    if not project: return False

    result = mgr.save_project(proj_id, project)
    if result is not False:
        st.success("☁️ Project saved to cloud!")
    return result

def get_or_create_user_id() -> str:
    if "user_id" not in st.session_state:
        import uuid
        st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id
