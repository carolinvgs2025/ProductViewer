# firestore_manager.py
"""
Firestore/Storage integration for persisting projects.
- No per-user filtering.
- Debounced saves (avoid duplicate writes on rerun).
- Strong validation for Firebase secrets (incl. bucket_name).
- Stores Storage *blob paths* as source of truth (no URL parsing needed).
- Backward compatible with older docs where image_mappings values were string URLs.
"""

from __future__ import annotations

import os
import time # Needed for cache busting
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st
from google.cloud import firestore, storage
from google.oauth2 import service_account


# =========================
# Small utilities
# =========================

def _blob_path_from_url(url: str, bucket_name: str) -> Optional[str]:
    """Best-effort conversion of a public or gs:// URL to a blob path within our bucket."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None

    # Strip cache-busting query params if present
    u = u.split('?')[0]

    # gs://<bucket>/<blob_path>
    if u.startswith("gs://"):
        rest = u[len("gs://"):]
        if "/" in rest:
            bkt, blob_path = rest.split("/", 1)
            if bkt == bucket_name:
                return blob_path
        return None

    # https://storage.googleapis.com/<bucket>/<blob_path>
    if "storage.googleapis.com" in u:
        try:
            after = u.split("storage.googleapis.com/", 1)[1]
            bkt, blob_path = after.split("/", 1)
            if bkt == bucket_name:
                return blob_path
        except Exception:
            return None

    return None


def _normalize_pem(pem: str) -> str:
    pem = (pem or "").replace("\r", "")
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    pem = pem.strip()
    lines = [ln.strip() for ln in pem.splitlines() if ln.strip()]
    if not lines or lines[0] != "-----BEGIN PRIVATE KEY-----" or lines[-1] != "-----END PRIVATE KEY-----":
        raise ValueError("private_key PEM header/footer malformed. Paste exactly as provided by Google.")
    return "\n".join(lines) + "\n"


# =========================
# Core Manager
# =========================

class ProjectFirestoreManager:
    def __init__(
        self,
        *,
        firebase_config_json_path: Optional[str] = None,
        creds: Optional[service_account.Credentials] = None,
        project_id: Optional[str] = None,
        bucket_name: Optional[str] = None,
    ):
        """
        Initialize Firestore + Storage clients.

        Provide either:
          - firebase_config_json_path='serviceAccount.json'
        or
          - creds=<Credentials>, project_id='<gcp-project-id>', bucket_name='<bucket>'
        """
        if firebase_config_json_path:
            self.db = firestore.Client.from_service_account_json(firebase_config_json_path)
            self.storage_client = storage.Client.from_service_account_json(firebase_config_json_path)
            if not bucket_name:
                raise ValueError("bucket_name is required when using firebase_config_json_path")
        elif creds and project_id:
            self.db = firestore.Client(credentials=creds, project=project_id)
            self.storage_client = storage.Client(credentials=creds, project=project_id)
        else:
            raise ValueError("Provide either firebase_config_json_path OR (creds AND project_id).")

        if not bucket_name:
            raise ValueError(
                "bucket_name is required (e.g., 'your-project.firebasestorage.app'). "
                "Add it to Streamlit secrets under [firebase]."
            )

        # Configuration
        self.bucket_name = bucket_name
        self.collection_name = "projects"

        # Debounce flag to prevent duplicate writes in the same rerun
        self._saving_in_progress: bool = False

    # ---------- Internal: Storage helpers ----------

    def _bucket(self):
        return self.storage_client.bucket(self.bucket_name)

    def _image_blob_path(self, project_id: str, image_name: str) -> str:
        return f"projects/{project_id}/images/{image_name}"

    def _excel_blob_path(self, project_id: str, filename: str) -> str:
        return f"projects/{project_id}/{filename}"

    def _upload_bytes(self, blob_path: str, data: bytes, content_type: str) -> str:
        """Upload bytes to Storage at blob_path; return a public URL (best-effort)."""
        blob = self._bucket().blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        try:
            blob.make_public()
            return blob.public_url  # https://storage.googleapis.com/<bucket>/<path>
        except Exception:
            return f"gs://{self.bucket_name}/{blob_path}"

    def _download_blob_bytes(self, blob_path: str) -> Optional[bytes]:
        try:
            blob = self._bucket().blob(blob_path)
            return blob.download_as_bytes()
        except Exception as e:
            print(f"Download failed for {blob_path}: {e}")
            return None

    # ---------- CRUD ----------

    def save_project(self, project_id: str, project_data: Dict) -> bool | Dict:
        """
        Save a project using LOWERCASE product IDs as keys in image_mappings.
        If new image data is found, it DELETES the old image before uploading.
        Returns the updated image_mappings dictionary (keyed by lowercase ID) on success.
        """
        if self._saving_in_progress:
            return False
        self._saving_in_progress = True

        try:
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

            # --- CONSISTENCY FIX ---
            # Ensure we load mappings keyed by lowercase, handling potential old data
            image_mappings_raw = project_data.get("image_mappings", {})
            image_mappings: Dict[str, Dict[str, str]] = {
                str(k).lower().strip(): v for k, v in image_mappings_raw.items() if k and isinstance(v, dict)
            }
            
            products_for_firestore = []

            for product in project_data.get("products_data", []):
                pcopy = dict(product)
                img_info = pcopy.pop("image_data", None)

                if img_info:
                    if isinstance(img_info, tuple) and len(img_info) == 2:
                        image_name, img_bytes = img_info
                    elif isinstance(img_info, bytes):
                        img_bytes = img_info
                        image_name = f"{pcopy.get('product_id', 'unnamed')}.png" # Use original case for filename only
                    else: # If img_info is not valid, skip image processing for this product
                        products_for_firestore.append(pcopy)
                        continue
                    
                    # --- CONSISTENCY FIX ---
                    # Get and use LOWERCASE product ID for all mapping operations
                    product_id_lower = str(pcopy.get("product_id", "")).lower().strip()
                    if not product_id_lower: # Skip if no valid ID
                        products_for_firestore.append(pcopy)
                        continue

                    # Delete old image using the lowercase key
                    if product_id_lower in image_mappings:
                        old_blob_path = image_mappings[product_id_lower].get("blob_path")
                        if old_blob_path:
                            try:
                                self._bucket().blob(old_blob_path).delete()
                            except Exception as e:
                                print(f"Could not delete old image {old_blob_path}: {e}")
                    
                    # Upload new image
                    blob_path = self._image_blob_path(project_id, image_name) # Use original case filename
                    content_type = "image/png" if image_name.lower().endswith(".png") else "image/jpeg"
                    base_url = self._upload_bytes(blob_path, img_bytes, content_type)
                    public_url = f"{base_url}?t={int(time.time())}" # Cache busting
                    
                    # Update product data and mappings using LOWERCASE key
                    pcopy["image_url"] = public_url
                    image_mappings[product_id_lower] = {
                        "blob_path": blob_path,
                        "public_url": public_url,
                    }

                products_for_firestore.append(pcopy)

            firestore_data["products_data"] = products_for_firestore
            # Save mappings keyed by lowercase ID
            firestore_data["image_mappings"] = image_mappings

            # Upload Excel if present
            excel_bytes = project_data.get("excel_file_data")
            excel_filename = project_data.get("excel_filename") or "grid.xlsx"
            if excel_bytes:
                excel_blob_path = self._excel_blob_path(project_id, excel_filename)
                excel_public_url = self._upload_bytes(excel_blob_path, excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                firestore_data["excel_blob_path"] = excel_blob_path
                firestore_data["excel_url"] = excel_public_url

            self.db.collection(self.collection_name).document(project_id).set(firestore_data)
            
            # Return the updated, lowercase-keyed mappings
            return image_mappings

        except Exception as e:
            st.error(f"Error saving project: {str(e)}")
            return False
        finally:
            self._saving_in_progress = False


    def load_project(self, project_id: str) -> Optional[Dict]:
        """
        OPTIMIZED: Load project using LOWERCASE product IDs for URL lookup.
        """
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}

            # --- CONSISTENCY FIX ---
            # Ensure the lookup is built using LOWERCASE keys from Firestore data
            url_lookup: Dict[str, str] = {}
            img_map_raw = data.get("image_mappings", {}) or {}
            # Normalize keys read from Firestore to lowercase, ensure value is a dict
            img_map = {str(k).lower().strip(): v for k, v in img_map_raw.items() if k and isinstance(v, dict)}

            for p_id_lower, meta in img_map.items(): # p_id_lower is already lowercase
                public_url = None
                if isinstance(meta, dict):
                    public_url = meta.get("public_url")
                elif isinstance(meta, str): # Legacy support (should be less common now)
                    public_url = meta
                
                if public_url:
                    url_lookup[p_id_lower] = public_url # Store with lowercase key

            # (Ultra-legacy support remains the same conceptually, ensure pid is lowercased if needed)
            if not url_lookup:
                 for p in data.get("products_data", []):
                     url = p.get("image_url")
                     if isinstance(url, str):
                         pid_lower = str(p.get("product_id", "")).lower().strip() # Use lowercase
                         if pid_lower:
                             url_lookup[pid_lower] = url
            
            # --- CONSISTENCY FIX ---
            # Iterate through products and use LOWERCASE ID for lookup
            for p in data.get("products_data", []):
                pid_lower = str(p.get("product_id", "")).lower().strip() # Get lowercase ID
                if pid_lower and pid_lower in url_lookup:
                    p["image_url"] = url_lookup[pid_lower] # Look up using lowercase ID
                else:
                    p["image_url"] = None
                
                p.pop("image_data", None)

            data.pop("uploaded_images", None)
            # Ensure the mappings stored in session state are also consistently lowercase
            data["image_mappings"] = img_map 

            return data

        except Exception as e:
            st.error(f"Error loading project: {str(e)}")
            return None

    def list_projects(self) -> List[Dict]:
        """List all project summaries (no per-user filtering)."""
        try:
            docs = self.db.collection(self.collection_name).stream()
            items: List[Dict] = []
            for d in docs:
                v = d.to_dict() or {}
                items.append({
                    "id": v.get("id"),
                    "name": v.get("name", ""),
                    "description": v.get("description", ""),
                    "created_date": v.get("created_date", ""),
                    "last_modified": v.get("last_modified", ""),
                    "num_products": len(v.get("products_data", [])),
                    "num_attributes": len(v.get("attributes", [])),
                    "num_pending_changes": len(v.get("pending_changes", {})),
                })
            return sorted(items, key=lambda x: x.get("last_modified", ""), reverse=True)
        except Exception as e:
            st.error(f"Error listing projects: {str(e)}")
            return []

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and its images (works with legacy/new schemas)."""
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if doc.exists:
                v = doc.to_dict() or {}
                # Use lowercase keys to find blobs to delete
                image_mappings_raw = v.get("image_mappings", {}) or {}
                img_map_lower = {str(k).lower().strip(): v for k, v in image_mappings_raw.items() if k and isinstance(v, dict)}

                for p_id_lower, meta in img_map_lower.items():
                    blob_path = None
                    if isinstance(meta, dict):
                        blob_path = meta.get("blob_path")
                        if not blob_path and meta.get("public_url"):
                            blob_path = _blob_path_from_url(meta["public_url"], self.bucket_name)
                    elif isinstance(meta, str): # Legacy
                         blob_path = _blob_path_from_url(meta, self.bucket_name)

                    if blob_path:
                        try:
                            self._bucket().blob(blob_path).delete()
                        except Exception as e:
                            print(f"Delete skipped for {blob_path}: {e}")

                # Delete Excel if present
                excel_blob_path = v.get("excel_blob_path")
                if excel_blob_path:
                    try:
                        self._bucket().blob(excel_blob_path).delete()
                    except Exception as e:
                        print(f"Delete skipped for {excel_blob_path}: {e}")

            # Remove Firestore doc last
            self.db.collection(self.collection_name).document(project_id).delete()
            return True
        except Exception as e:
            st.error(f"Error deleting project: {str(e)}")
            return False


# =========================
# Integration helpers
# =========================

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


# =========================
# App-level helpers
# =========================

def load_project_summaries_from_cloud() -> int:
    """
    Load only project summaries (no products/images) into session_state.project_summaries.
    Does NOT populate session_state.projects.
    """
    mgr: ProjectFirestoreManager = st.session_state.get("firestore_manager")
    if not mgr:
        st.session_state.project_summaries = []
        return 0

    summaries = mgr.list_projects()  # already summaries, no images
    st.session_state.project_summaries = summaries or []
    # st.success(f"☁️ Loaded {len(st.session_state.project_summaries)} project summary(ies) from cloud") # Less verbose
    return len(st.session_state.project_summaries)


def ensure_project_loaded(project_id: str) -> bool:
    """
    Ensure a full project (with products/images) exists in session_state.projects[project_id].
    Fetches from Firestore if not already present. Returns True on success.
    """
    if "projects" not in st.session_state:
        st.session_state.projects = {}

    if project_id in st.session_state.projects:
        return True

    mgr: ProjectFirestoreManager = st.session_state.get("firestore_manager")
    if not mgr:
        return False
    
    with st.spinner(f"Loading project {project_id}..."):
        data = mgr.load_project(project_id)
        if not data:
            st.error("Failed to load project from Firestore.")
            return False

        st.session_state.projects[project_id] = data
        return True


def save_current_project_to_cloud() -> bool | Dict: # Modified return type hint
    """Save the active project one time and return the result."""
    mgr: ProjectFirestoreManager = st.session_state.get("firestore_manager")
    proj_id: Optional[str] = st.session_state.get("current_project")
    if not mgr or not proj_id:
        return False
    project = st.session_state.projects.get(proj_id)
    if not project:
        return False

    result = mgr.save_project(proj_id, project) # Result is mappings dict or False
    if result is not False: # Check if it was successful (didn't return False)
        st.success("☁️ Project saved to cloud!")
    
    return result # Return the mappings dict or False


def get_or_create_user_id() -> str:
    """Legacy helper to maintain compatibility with your app; not used for filtering."""
    if "user_id" not in st.session_state:
        import uuid
        st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id
