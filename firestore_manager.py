# firestore_manager.py
"""
Firestore integration for persisting projects between sessions.
Updated to store both product images and Excel file in Firebase Storage.
"""

import streamlit as st
from google.cloud import firestore, storage
from google.oauth2 import service_account
from datetime import datetime
import uuid
from typing import Dict, List, Optional
import os
import requests


class ProjectFirestoreManager:
    def __init__(
        self,
        firebase_config_json_path: str = None,
        creds=None,
        project_id: str = None,
        bucket_name: str = None
    ):
        """
        Initialize Firestore connection.

        Args:
            firebase_config_json_path: Path to Firebase service account JSON
            creds: google.oauth2.service_account.Credentials object
            project_id: GCP project ID
            bucket_name: Optional GCS bucket name
        """
        if firebase_config_json_path:
            self.db = firestore.Client.from_service_account_json(firebase_config_json_path)
            self.storage_client = storage.Client.from_service_account_json(firebase_config_json_path)
        elif creds and project_id:
            self.db = firestore.Client(credentials=creds, project=project_id)
            self.storage_client = storage.Client(credentials=creds, project=project_id)
        else:
            raise ValueError("Firestore requires either a JSON path or (creds, project_id).")

        self.bucket_name = bucket_name or f"{project_id}.appspot.com"
        self.collection_name = "projects"

    # ---------------- IMAGE UPLOAD/DOWNLOAD ----------------

    def _upload_image_to_storage(self, image_data: bytes, image_name: str, project_id: str) -> str:
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            blob_name = f"projects/{project_id}/images/{image_name}"
            blob = bucket.blob(blob_name)
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
                blob_name = "/".join(parts[4:])
            else:
                return None
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            return blob.download_as_bytes()
        except Exception as e:
            print(f"Error downloading image: {str(e)}")
            return None

    # ---------------- CRUD ----------------

    def save_project(self, project_id: str, project_data: Dict) -> bool:
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
                'excel_filename': project_data.get('excel_filename'),
                'user_id': st.session_state.get('user_id', 'anonymous'),
            }

            products_for_firestore = []
            image_mappings = {}
            bucket = self.storage_client.bucket(self.bucket_name)

            # Upload images
            for product in project_data['products_data']:
                product_copy = product.copy()
                if product_copy.get('image_data'):
                    image_name = f"{product_copy['product_id']}.png"
                    image_url = self._upload_image_to_storage(
                        product_copy['image_data'], image_name, project_id
                    )
                    if image_url:
                        image_mappings[product_copy['product_id']] = image_url
                        product_copy['image_url'] = image_url
                    del product_copy['image_data']
                products_for_firestore.append(product_copy)

            firestore_data['products_data'] = products_for_firestore
            firestore_data['image_mappings'] = image_mappings

            # Upload Excel file if available
            if "excel_file_data" in project_data and project_data["excel_file_data"]:
                excel_blob = bucket.blob(f"projects/{project_id}/{project_data['excel_filename'] or 'grid.xlsx'}")
                excel_blob.upload_from_string(
                    project_data["excel_file_data"],
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                excel_blob.make_public()
                firestore_data['excel_url'] = excel_blob.public_url

            self.db.collection(self.collection_name).document(project_id).set(firestore_data)
            return True

        except Exception as e:
            st.error(f"Error saving project: {str(e)}")
            return False

    def load_project(self, project_id: str) -> Optional[Dict]:
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if not doc.exists:
                return None

            project_data = doc.to_dict()

            # Download images
            for product in project_data.get('products_data', []):
                if product.get('image_url'):
                    image_data = self._download_image_from_storage(product['image_url'])
                    if image_data:
                        product['image_data'] = image_data

            uploaded_images = {}
            for pid, image_url in project_data.get('image_mappings', {}).items():
                image_data = self._download_image_from_storage(image_url)
                if image_data:
                    uploaded_images[f"{pid}.png"] = image_data
            project_data['uploaded_images'] = uploaded_images

            # Download Excel file if URL is available
            if "excel_url" in project_data:
                try:
                    resp = requests.get(project_data["excel_url"])
                    if resp.status_code == 200:
                        project_data["excel_file_data"] = resp.content
                except Exception as e:
                    st.warning(f"Could not download Excel file: {e}")

            return project_data

        except Exception as e:
            st.error(f"Error loading project: {str(e)}")
            return None

    def list_user_projects(self, user_id: str = None) -> List[Dict]:
        try:
            query = self.db.collection(self.collection_name)
            if user_id:
                query = query.where('user_id', '==', user_id)

            docs = query.stream()
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
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if doc.exists:
                data = doc.to_dict()
                for image_url in data.get('image_mappings', {}).values():
                    if "storage.googleapis.com" in image_url:
                        parts = image_url.split("/")
                        blob_name = "/".join(parts[4:])
                        bucket = self.storage_client.bucket(self.bucket_name)
                        bucket.blob(blob_name).delete()
            self.db.collection(self.collection_name).document(project_id).delete()
            return True
        except Exception as e:
            st.error(f"Error deleting project: {str(e)}")
            return False


# ---------------- INTEGRATION ----------------

def integrate_with_streamlit_app():
    if 'firestore_manager' not in st.session_state:
        try:
            st.info("🔍 Checking Firebase configuration...")

            if os.path.exists('serviceAccount.json'):
                st.info("📄 Found local serviceAccount.json file")
                st.session_state.firestore_manager = ProjectFirestoreManager(
                    firebase_config_json_path='serviceAccount.json'
                )
                st.success("✅ Firestore initialized with local service account")

            elif 'firebase' in st.secrets:
                st.info("🔑 Found Firebase secrets in Streamlit")
                firebase_creds = dict(st.secrets["firebase"])

                # Normalize PEM formatting
                pk = str(firebase_creds.get("private_key", ""))
                if "\\n" in pk and "\n" not in pk:
                    pk = pk.replace("\\n", "\n")
                pk = pk.replace("\r", "").strip()
                if (pk.startswith('"') and pk.endswith('"')) or (pk.startswith("'") and pk.endswith("'")):
                    pk = pk[1:-1].strip()
                lines = [ln.strip() for ln in pk.splitlines() if ln.strip() != ""]
                if not lines or lines[0] != "-----BEGIN PRIVATE KEY-----" or lines[-1] != "-----END PRIVATE KEY-----":
                    st.error("❌ private_key PEM header/footer malformed.")
                    st.stop()
                pk = "\n".join(lines) + "\n"
                firebase_creds["private_key"] = pk

                required = [
                    "type", "project_id", "private_key_id", "private_key",
                    "client_email", "client_id", "auth_uri", "token_uri"
                ]
                missing = [k for k in required if not firebase_creds.get(k)]
                if missing:
                    st.error(f"❌ Missing required keys in Firebase secrets: {missing}")
                    st.stop()

                creds = service_account.Credentials.from_service_account_info(firebase_creds)
                st.session_state.firestore_manager = ProjectFirestoreManager(
                    creds=creds,
                    project_id=firebase_creds["project_id"],
                    bucket_name=firebase_creds.get("bucket_name")
                )
                st.success("✅ Firestore initialized with Streamlit secrets")
            else:
                st.warning("⚠️ Firebase credentials not configured.")
                st.stop()

        except Exception as e:
            st.error(f"❌ Failed to initialize Firebase: {str(e)}")
            st.exception(e)
            st.session_state.firestore_manager = None

    return st.session_state.firestore_manager


# ---------------- HELPERS ----------------

def save_current_project_to_cloud():
    if st.session_state.current_project and st.session_state.firestore_manager:
        project = st.session_state.projects[st.session_state.current_project]
        success = st.session_state.firestore_manager.save_project(
            st.session_state.current_project, project
        )
        if success:
            st.success("☁️ Project saved to cloud!")
        return success
    return False


def load_projects_from_cloud():
    if st.session_state.firestore_manager:
        user_id = st.session_state.get('user_id', 'anonymous')
        summaries = st.session_state.firestore_manager.list_user_projects(user_id)
        loaded_count = 0
        for summary in summaries:
            if summary['id'] not in st.session_state.projects:
                project_data = st.session_state.firestore_manager.load_project(summary['id'])
                if project_data:
                    st.session_state.projects[summary['id']] = project_data
                    loaded_count += 1
        if loaded_count > 0:
            st.success(f"☁️ Loaded {loaded_count} project(s) from cloud")
        return loaded_count
    return 0


def get_or_create_user_id():
    if 'user_id' not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id


