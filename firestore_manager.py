# firestore_manager.py
"""
Firestore/Storage integration for persisting projects.
- No per-user filtering.
- Debounced saves.
- NEW: Offloads 'products_data' to JSON in Storage (bypasses 1MB limit).
- NEW: Saves 'product_count' explicitly so lists remain accurate.
"""

from __future__ import annotations

import os
import time
import json
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st
from google.cloud import firestore, storage
from google.oauth2 import service_account

# ... [Keep your existing helper functions: _blob_path_from_url and _normalize_pem] ...
# (Copy them from your previous file or see below if you need them re-pasted)

def _blob_path_from_url(url: str, bucket_name: str) -> Optional[str]:
    if not isinstance(url, str): return None
    u = url.strip().split('?')[0]
    if not u: return None
    if u.startswith("gs://"):
        rest = u[len("gs://"):]
        if "/" in rest and rest.split("/", 1)[0] == bucket_name:
            return rest.split("/", 1)[1]
    if "storage.googleapis.com" in u:
        try:
            after = u.split("storage.googleapis.com/", 1)[1]
            if after.split("/", 1)[0] == bucket_name:
                return after.split("/", 1)[1]
        except: pass
    return None

def _normalize_pem(pem: str) -> str:
    pem = (pem or "").replace("\r", "")
    if "\\n" in pem and "\n" not in pem: pem = pem.replace("\\n", "\n")
    return pem.strip()

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
        blob = self._bucket().blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        try: 
            blob.make_public()
            return blob.public_url
        except: return f"gs://{self.bucket_name}/{blob_path}"

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
                "filter_options": project_data.get("filter_options", {}),
                "pending_changes": project_data.get("pending_changes", {}),
                "excel_filename": project_data.get("excel_filename"),
            }

            # 2. Process Images
            image_mappings_raw = project_data.get("image_mappings", {})
            image_mappings = {str(k).lower().strip(): v for k, v in image_mappings_raw.items() if k and isinstance(v, dict)}
            
            products_for_storage = []
            
            for product in project_data.get("products_data", []):
                pcopy = dict(product)
                img_info = pcopy.pop("image_data", None)

                if img_info:
                    # Logic to handle new image uploads
                    if isinstance(img_info, tuple) and len(img_info) == 2:
                        image_name, img_bytes = img_info
                    elif isinstance(img_info, bytes):
                        img_bytes = img_info
                        image_name = f"{pcopy.get('product_id', 'unnamed')}.png"
                    else:
                        products_for_storage.append(pcopy); continue
                    
                    pid_lower = str(pcopy.get("product_id", "")).lower().strip()
                    if not pid_lower: products_for_storage.append(pcopy); continue

                    # Delete old
                    if pid_lower in image_mappings:
                        old_path = image_mappings[pid_lower].get("blob_path")
                        if old_path: 
                            try: self._bucket().blob(old_path).delete()
                            except: pass
                    
                    # Upload new
                    blob_path = self._image_blob_path(project_id, image_name)
                    content_type = "image/png" if image_name.lower().endswith(".png") else "image/jpeg"
                    base_url = self._upload_bytes(blob_path, img_bytes, content_type)
                    
                    pcopy["image_url"] = f"{base_url}?t={int(time.time())}"
                    image_mappings[pid_lower] = {"blob_path": blob_path, "public_url": pcopy["image_url"]}

                products_for_storage.append(pcopy)

            # 3. Offload Products to JSON (Bypass 1MB limit)
            try:
                products_json = json.dumps(products_for_storage)
                json_path = f"projects/{project_id}/products_data.json"
                self._upload_bytes(json_path, products_json.encode('utf-8'), "application/json")
                
                firestore_data["products_blob_path"] = json_path
                firestore_data["products_data"] = [] # Clear from DB
                # FIX: Save count specifically so list view works
                firestore_data["product_count"] = len(products_for_storage) 
                
            except Exception as e:
                st.error(f"Failed to upload data file: {e}")
                return False

            firestore_data["image_mappings"] = image_mappings

            # 4. Excel
            excel_bytes = project_data.get("excel_file_data")
            if excel_bytes:
                name = project_data.get("excel_filename") or "grid.xlsx"
                path = self._excel_blob_path(project_id, name)
                url = self._upload_bytes(path, excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                firestore_data["excel_blob_path"] = path
                firestore_data["excel_url"] = url

            self.db.collection(self.collection_name).document(project_id).set(firestore_data)
            return image_mappings

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

            # 1. Load Products (From JSON or Legacy List)
            blob_path = data.get("products_blob_path")
            if blob_path:
                json_bytes = self._download_blob_bytes(blob_path)
                data["products_data"] = json.loads(json_bytes.decode('utf-8')) if json_bytes else []
            else:
                if "products_data" not in data: data["products_data"] = []

            # 2. Restore URLs
            img_map = data.get("image_mappings", {})
            url_lookup = {}
            for k, v in img_map.items():
                if isinstance(v, dict) and "public_url" in v: url_lookup[k] = v["public_url"]
                elif isinstance(v, str): url_lookup[k] = v

            # Fallback legacy lookup
            if not url_lookup:
                for p in data["products_data"]:
                    if p.get("image_url"): url_lookup[str(p.get("product_id")).lower().strip()] = p["image_url"]

            for p in data["products_data"]:
                pid = str(p.get("product_id", "")).lower().strip()
                p["image_url"] = url_lookup.get(pid)
                p.pop("image_data", None)

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
                # FIX: Use saved count OR legacy list length
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
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if doc.exists:
                v = doc.to_dict() or {}
                # Delete Images
                for meta in v.get("image_mappings", {}).values():
                    path = meta.get("blob_path") if isinstance(meta, dict) else _blob_path_from_url(meta, self.bucket_name)
                    if path: 
                        try: self._bucket().blob(path).delete()
                        except: pass
                
                # Delete Files
                for key in ["excel_blob_path", "products_blob_path"]:
                    if v.get(key):
                        try: self._bucket().blob(v[key]).delete()
                        except: pass

            self.db.collection(self.collection_name).document(project_id).delete()
            return True
        except Exception as e:
            st.error(f"Error deleting: {e}"); return False

# ... [Keep integrate_with_streamlit_app and other bottom helpers unchanged] ...
def integrate_with_streamlit_app() -> Optional[ProjectFirestoreManager]:
    """
    Initialize a singleton ProjectFirestoreManager and put it in session_state.
    Requires bucket_name in secrets when using Streamlit secrets.
    """
    if "firestore_manager" in st.session_state and st.session_state.firestore_manager:
        return st.session_state.firestore_manager

    try:
        # st.info("🔍 Checking Firebase configuration...") # Less verbose

        # Local JSON
        if os.path.exists("serviceAccount.json"):
            # st.info("📄 Found local serviceAccount.json")
            bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET") or st.secrets.get("firebase", {}).get("bucket_name")
            if not bucket_name:
                st.error("Missing bucket_name. Set env FIREBASE_STORAGE_BUCKET or secrets [firebase].bucket_name")
                st.stop()
            mgr = ProjectFirestoreManager(
                firebase_config_json_path="serviceAccount.json",
                bucket_name=bucket_name,
            )
            # st.success("✅ Firestore initialized with local JSON")
            st.session_state.firestore_manager = mgr
            return mgr

        # Streamlit secrets
        if "firebase" in st.secrets:
            # st.info("🔑 Found Firebase secrets")
            fb = dict(st.secrets["firebase"])

            required = [
                "type", "project_id", "private_key_id", "private_key",
                "client_email", "client_id", "auth_uri", "token_uri", "bucket_name"
            ]
            missing = [k for k in required if not fb.get(k)]
            if missing:
                st.error(f"❌ Missing keys in [firebase] secrets: {missing}")
                st.stop()

            try:
                fb["private_key"] = _normalize_pem(str(fb["private_key"]))
                creds = service_account.Credentials.from_service_account_info(fb)
            except ValueError as e:
                 st.error(f"❌ Error processing Firebase private key: {e}")
                 st.stop()
            except Exception as e:
                 st.error(f"❌ Unexpected error initializing Firebase credentials: {e}")
                 st.stop()


            mgr = ProjectFirestoreManager(
                creds=creds,
                project_id=fb["project_id"],
                bucket_name=fb["bucket_name"],  # e.g. your-project.firebasestorage.app
            )
            # st.success("✅ Firestore initialized with Streamlit secrets")
            st.session_state.firestore_manager = mgr
            return mgr

        st.warning("⚠️ Firebase credentials not configured.")
        st.stop() # Stop execution if no credentials found

    except Exception as e:
        st.error(f"❌ Firebase init failed: {e}")
        st.exception(e)
        st.session_state.firestore_manager = None
        return None
