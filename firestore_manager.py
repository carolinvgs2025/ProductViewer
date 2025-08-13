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

    def save_project(self, project_id: str, project_data: Dict) -> bool:
        """
        Save a project to Firestore and upload any product images / excel if provided.

        project_data fields used:
          - name, description, created_date, attributes, distributions, filter_options,
            pending_changes, excel_filename, products_data (each product may have image_data bytes)
          - Optional: excel_file_data (bytes) to upload the Excel grid
        """
        if self._saving_in_progress:
            return False  # debounce: skip duplicate saves in this rerun
        self._saving_in_progress = True

        try:
            # Build Firestore document
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

            # Upload images and strip raw bytes from Firestore payload
            products_for_firestore = []
            image_mappings: Dict[str, Dict[str, str]] = {}  # product_id -> {"blob_path": ..., "public_url": ...}

            for product in project_data.get("products_data", []):
                pcopy = dict(product)
                img_bytes = pcopy.pop("image_data", None)
                if img_bytes:
                    image_name = f"{pcopy.get('product_id', 'unnamed')}.png"
                    blob_path = self._image_blob_path(project_id, image_name)
                    public_url = self._upload_bytes(blob_path, img_bytes, "image/png")
                    pcopy["image_url"] = public_url
                    image_mappings[pcopy.get("product_id", image_name)] = {
                        "blob_path": blob_path,
                        "public_url": public_url,
                    }
                products_for_firestore.append(pcopy)

            firestore_data["products_data"] = products_for_firestore
            firestore_data["image_mappings"] = image_mappings  # keep both blob_path and public_url

            # Upload Excel if present
            excel_bytes = project_data.get("excel_file_data")
            excel_filename = project_data.get("excel_filename") or "grid.xlsx"
            if excel_bytes:
                excel_blob_path = self._excel_blob_path(project_id, excel_filename)
                excel_public_url = self._upload_bytes(
                    excel_blob_path,
                    excel_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                firestore_data["excel_blob_path"] = excel_blob_path
                firestore_data["excel_url"] = excel_public_url

            # Persist metadata
            self.db.collection(self.collection_name).document(project_id).set(firestore_data)
            return True

        except Exception as e:
            st.error(f"Error saving project: {str(e)}")
            return False
        finally:
            self._saving_in_progress = False

    def load_project(self, project_id: str) -> Optional[Dict]:
        """Load a project (and fetch images back into memory). Supports legacy schemas."""
        try:
            doc = self.db.collection(self.collection_name).document(project_id).get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}

            # Rehydrate images (support both legacy string URLs and new dicts)
            uploaded_images: Dict[str, bytes] = {}
            img_map = data.get("image_mappings", {}) or {}

            normalized_map: Dict[str, Dict[str, str]] = {}

            for product_id, meta in img_map.items():
                if isinstance(meta, dict):
                    blob_path = meta.get("blob_path")
                    public_url = meta.get("public_url")
                    if not blob_path and public_url:
                        blob_path = _blob_path_from_url(public_url, self.bucket_name)
                elif isinstance(meta, str):
                    # Legacy: value is a URL string
                    public_url = meta
                    blob_path = _blob_path_from_url(public_url, self.bucket_name)
                else:
                    blob_path = None
                    public_url = None

                if blob_path:
                    img_bytes = self._download_blob_bytes(blob_path)
                    if img_bytes:
                        uploaded_images[f"{product_id}.png"] = img_bytes
                        normalized_map[product_id] = {"blob_path": blob_path, "public_url": public_url or ""}

            # Also support ultra-legacy case where each product only had "image_url"
            if not normalized_map:
                for p in data.get("products_data", []):
                    url = p.get("image_url")
                    if isinstance(url, str):
                        blob_path = _blob_path_from_url(url, self.bucket_name)
                        if blob_path:
                            img_bytes = self._download_blob_bytes(blob_path)
                            if img_bytes:
                                pid = p.get("product_id", "unnamed")
                                uploaded_images[f"{pid}.png"] = img_bytes
                                normalized_map[pid] = {"blob_path": blob_path, "public_url": url}

            # Put image_data back into products_data (for rendering)
            for p in data.get("products_data", []):
                pid = p.get("product_id")
                if pid:
                    buf = uploaded_images.get(f"{pid}.png")
                    if buf:

