# firestore_manager.py
"""
Firestore integration for persisting projects between sessions.
No per-user separation. Prevents duplicate saves and duplicate loads.
"""

import streamlit as st
from google.cloud import firestore, storage
from google.oauth2 import service_account
from datetime import datetime
import uuid
from typing import Dict, List, Optional
import os


class ProjectFirestoreManager:
    def __init__(self, firebase_config_json_path: str = None, creds=None, project_id: str = None, bucket_name: str = None):
        """Initialize Firestore + Storage clients."""
        if firebase_config_json_path:
            self.db = firestore.Client.from_service_account_json(firebase_config_json_path)
            self.storage_client = storage.Client.from_service_account_json(firebase_config_json_path)
            self.project_id = None
        elif creds and project_id:
            self.db = firestore.Client(credentials=creds, project=project_id)
            self.storage_client = storage.Client(credentials=creds, project=project_id)
            self.project_id = project_id
        else:
            raise ValueError("Must provide either a service account JSON path or (creds, project_id).")

        self.bucket_name = bucket_name or f"{project_id}.appspot.com"
        self.collection_name = "projects"
        self._saving_in_progress = False  # Prevent multiple saves in one rerun

    # ---------- IMAGE UPLOAD/DOWNLOAD ----------

    def _upload_image_to_storage(self, image_data: bytes, image_name: str, project_id: str) -> str:
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            blob_path = f"projects/{project_id}/images/{image_name}"
            blob = bucket.blob(blob_path)
            blob.upload_from_string(image_data, content_type='image/png')
            blob.make_public()
            return blob.public_url
        except Exception as e:
            st.error(f"Error uploading image {image_name}: {str(e)}")
            return None

    def _download_image_from_storage(self, image_url: str) -> Optional[bytes]:
        try:
            if "storage.googleapis.com" in image_url:
                parts = image_url.split("/")
                blob_path = "/".join(parts[4:])
                bucket = self.storage_client.bucket(self.bucket_name)
                blob = bucket.blob(blob_path)
                return blob.download_as_bytes()
            return None
        except Exception as e:
            print(f"Error downloading image: {str(e)}")
            return None

    # ---------- CRUD ----------

    def save_project(self, project_id: str, project_data: Dict) -> bool:
        """Save a project to Firestore and upload images."""
        if self._saving_in_progress:
            return False  # Skip duplicate saves in one rerun
        self._saving_in_progress = True

        try:
            firestore_data = {
                'id': project_id,
                'name': project_data['name'],
                'description': project_data['description'],
                'created_date': project_data['created_date'],
                'last_modified': datetime.now().isoformat(),
                'attributes': project_data['attributes'],
                'distributions': project_data['distributions'],
                'filter_options': project_data['filter_options'],
                'pending_changes': project_data['pending_changes'],
                'excel_filename': project_data.get('excel_filename')
            }

            products_for_firestore = []
            image_mappings = {}

            for product in project_data.get('products_data', []):
                product_copy = product.copy()
                if product_copy.get('image_data'):
                    image_name = f"{product_copy['product_id']}.png"
                    image_url = self._upload_image_to_storage(product_copy['image_data'], image_name, project_id)
                    if image_url:
                        image_mappings[product_copy['product_id']] = image_url
                        product_copy['image_url'] = image_url
                    del product_copy['image_data']
                products_for_firestore.append(product_copy)

            firestore_data['products_data'] = products_for_firestore
            firestore_data['image_mappings'] = image_mappings

            self.db.collection(self.collection_name).document(project_id).set(firestore_data)
            return True
        except Exception as e:
            st.error(f"Error saving project: {str(e)}")
            return False
        finally:
            self._saving_in_progress = False

    def load_project(self, project_id: str) -> Optional[Dict]:
        """Load a project from Firestore and download its images."""
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if not doc.exists:
                return None

            project_data = doc.to_dict()

            for product in project_data.get('products_data', []):
                if product.get('image_url'):
                    img_data = self._download_image_from_storage(product['image_url'])
                    if img_data:
                        product['image_data'] = img_data

            uploaded_images = {}
            for pid, url in project_data.get('image_mappings', {}).items():
                img_data = self._download_image_from_storage(url)
                if img_data:
                    uploaded_images[f"{pid}.png"] = img_data
            project_data['uploaded_images'] = uploaded_images

            return project_data
        except Exception as e:
            st.error(f"Error loading project: {str(e)}")
            return None

    def list_projects(self) -> List[Dict]:
        """List all projects in Firestore."""
        try:
            docs = self.db.collection(self.collection_name).stream()
            projects = []
            for doc in docs:
                data = doc.to_dict()
                projects.append({
                    'id': data['id'],
                    'name': data['name'],
                    'description': data.get('description', ''),
                    'created_date': data.get('created_date', ''),
                    'last_modified': data.get('last_modified', ''),
                    'num_products': len(data.get('products_data', [])),
                    'num_attributes': len(data.get('attributes', [])),
                    'num_pending_changes': len(data.get('pending_changes', {}))
                })
            return sorted(projects, key=lambda x: x['last_modified'], reverse=True)
        except Exception as e:
            st.error(f"Error listing projects: {str(e)}")
            return []

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and its images from Firestore/Storage."""
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if doc.exists:
                data = doc.to_dict()
                for url in data.get('image_mappings', {}).values():
                    if "storage.googleapis.com" in url:
                        parts = url.split("/")
                        blob_path = "/".join(parts[4:])
                        self.storage_client.bucket(self.bucket_name).blob(blob_path).delete()

            self.db.collection(self.collection_name).document(project_id).delete()
            return True
        except Exception as e:
            st.error(f"Error deleting project: {str(e)}")
            return False


# ---------- INTEGRATION ----------

def integrate_with_streamlit_app():
    """Initialize FirestoreManager from local JSON or Streamlit secrets."""
    if 'firestore_manager' not in st.session_state:
        try:
            st.info("🔍 Checking Firebase configuration...")
            if os.path.exists('serviceAccount.json'):
                st.session_state.firestore_manager = ProjectFirestoreManager(firebase_config_json_path='serviceAccount.json')
                st.success("✅ Firestore initialized with local JSON")
            elif 'firebase' in st.secrets:
                firebase_creds = dict(st.secrets["firebase"])
                # Normalize private key
                pk = str(firebase_creds.get("private_key", ""))
                if "\\n" in pk and "\n" not in pk:
                    pk = pk.replace("\\n", "\n")
                firebase_creds["private_key"] = pk.strip() + "\n"
                creds = service_account.Credentials.from_service_account_info(firebase_creds)
                st.session_state.firestore_manager = ProjectFirestoreManager(
                    creds=creds,
                    project_id=firebase_creds["project_id"],
                    bucket_name=firebase_creds.get("bucket_name")
                )
                st.success("✅ Firestore initialized with Streamlit secrets")
            else:
                st.warning("⚠️ Firebase credentials not found.")
                st.stop()
        except Exception as e:
            st.error(f"❌ Firebase init failed: {str(e)}")
            st.exception(e)
            st.session_state.firestore_manager = None
    return st.session_state.firestore_manager


# ---------- HELPERS ----------

def save_current_project_to_cloud():
    """Save the active project to Firestore."""
    if st.session_state.get("current_project") and st.session_state.get("firestore_manager"):
        proj_id = st.session_state.current_project
        project = st.session_state.projects[proj_id]
        if st.session_state.firestore_manager.save_project(proj_id, project):
            st.success("☁️ Project saved to cloud!")
            return True
    return False


def load_projects_from_cloud():
    """Load all projects from Firestore into session_state."""
    if st.session_state.get("firestore_manager"):
        summaries = st.session_state.firestore_manager.list_projects()
        st.session_state.projects = {}  # Reset to avoid duplicates
        for summary in summaries:
            project_data = st.session_state.firestore_manager.load_project(summary['id'])
            if project_data:
                st.session_state.projects[summary['id']] = project_data
        st.success(f"☁️ Loaded {len(st.session_state.projects)} project(s) from cloud")
        return len(st.session_state.projects)
    return 0


def get_or_create_user_id():
    """Legacy helper — no longer used for filtering."""
    if 'user_id' not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id



