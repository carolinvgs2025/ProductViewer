# firestore_manager.py
"""
Firestore integration for persisting projects between sessions.
Add this as a separate file in your project.
"""

import streamlit as st
from google.cloud import firestore
from google.cloud import storage
import json
import base64
from datetime import datetime
import uuid
from typing import Dict, List, Optional
import io
import tempfile

class ProjectFirestoreManager:
    def __init__(self, firebase_config_json_path: str = None):
        """
        Initialize Firestore connection.
        
        Args:
            firebase_config_json_path: Path to your Firebase service account JSON file
        """
        # Initialize Firestore client
        if firebase_config_json_path:
            self.db = firestore.Client.from_service_account_json(firebase_config_json_path)
            self.storage_client = storage.Client.from_service_account_json(firebase_config_json_path)
        else:
            # Use default credentials (for deployment on Google Cloud)
            self.db = firestore.Client()
            self.storage_client = storage.Client()
        
        # UPDATE THIS with your actual bucket name from Firebase Console
        self.bucket_name = "product-grid-and-images.firebasestorage.app"  # Replace with your bucket name
        self.collection_name = "projects"
        
    def _upload_image_to_storage(self, image_data: bytes, image_name: str, project_id: str) -> str:
        """Upload image to Cloud Storage and return URL."""
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            blob_name = f"projects/{project_id}/images/{image_name}"
            blob = bucket.blob(blob_name)
            
            blob.upload_from_string(image_data, content_type='image/png')
            
            # Make the blob publicly accessible (optional)
            blob.make_public()
            
            return blob.public_url
        except Exception as e:
            st.error(f"Error uploading image {image_name}: {str(e)}")
            return None
    
    def _download_image_from_storage(self, image_url: str) -> bytes:
        """Download image from Cloud Storage URL."""
        try:
            # Extract blob name from URL
            if "storage.googleapis.com" in image_url:
                parts = image_url.split("/")
                blob_name = "/".join(parts[4:])  # Skip protocol, domain, bucket name
            else:
                return None
                
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            
            return blob.download_as_bytes()
        except Exception as e:
            print(f"Error downloading image: {str(e)}")
            return None
    
    def save_project(self, project_id: str, project_data: Dict) -> bool:
        """
        Save a project to Firestore.
        
        Args:
            project_id: Unique project identifier
            project_data: Project dictionary from session state
        
        Returns:
            Success status
        """
        try:
            # Prepare project data for Firestore
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
                'user_id': st.session_state.get('user_id', 'anonymous'),  # Add user management
            }
            
            # Handle products data separately (without image bytes)
            products_for_firestore = []
            image_mappings = {}  # Map product_id to image URL
            
            for product in project_data['products_data']:
                product_copy = product.copy()
                
                # Upload image if exists
                if product_copy.get('image_data'):
                    image_name = f"{product_copy['product_id']}.png"
                    image_url = self._upload_image_to_storage(
                        product_copy['image_data'],
                        image_name,
                        project_id
                    )
                    if image_url:
                        image_mappings[product_copy['product_id']] = image_url
                        # Remove image data from product (store URL reference instead)
                        product_copy['image_url'] = image_url
                    del product_copy['image_data']
                
                products_for_firestore.append(product_copy)
            
            firestore_data['products_data'] = products_for_firestore
            firestore_data['image_mappings'] = image_mappings
            
            # Save to Firestore
            doc_ref = self.db.collection(self.collection_name).document(project_id)
            doc_ref.set(firestore_data)
            
            return True
            
        except Exception as e:
            st.error(f"Error saving project: {str(e)}")
            return False
    
    def load_project(self, project_id: str) -> Optional[Dict]:
        """
        Load a project from Firestore.
        
        Args:
            project_id: Project identifier
        
        Returns:
            Project data dictionary or None if not found
        """
        try:
            doc_ref = self.db.collection(self.collection_name).document(project_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return None
            
            project_data = doc.to_dict()
            
            # Download images and restore image_data
            for product in project_data.get('products_data', []):
                if product.get('image_url'):
                    try:
                        image_data = self._download_image_from_storage(product['image_url'])
                        if image_data:
                            product['image_data'] = image_data
                    except Exception as e:
                        print(f"Could not load image for product {product['product_id']}: {e}")
                        product['image_data'] = None
            
            # Rebuild uploaded_images dict for compatibility
            uploaded_images = {}
            for product_id, image_url in project_data.get('image_mappings', {}).items():
                try:
                    image_data = self._download_image_from_storage(image_url)
                    if image_data:
                        uploaded_images[f"{product_id}.png"] = image_data
                except:
                    pass
            
            project_data['uploaded_images'] = uploaded_images
            
            return project_data
            
        except Exception as e:
            st.error(f"Error loading project: {str(e)}")
            return None
    
    def list_user_projects(self, user_id: str = None) -> List[Dict]:
        """
        List all projects for a user.
        
        Args:
            user_id: User identifier (optional)
        
        Returns:
            List of project summaries
        """
        try:
            query = self.db.collection(self.collection_name)
            
            if user_id:
                query = query.where('user_id', '==', user_id)
            
            docs = query.stream()
            
            projects = []
            for doc in docs:
                data = doc.to_dict()
                # Return summary without full product data
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
        """
        Delete a project from Firestore.
        
        Args:
            project_id: Project identifier
        
        Returns:
            Success status
        """
        try:
            # Delete images from Cloud Storage
            doc_ref = self.db.collection(self.collection_name).document(project_id)
            doc = doc_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                # Delete all images for this project
                for image_url in data.get('image_mappings', {}).values():
                    try:
                        # Extract blob name and delete
                        if "storage.googleapis.com" in image_url:
                            parts = image_url.split("/")
                            blob_name = "/".join(parts[4:])
                            bucket = self.storage_client.bucket(self.bucket_name)
                            blob = bucket.blob(blob_name)
                            blob.delete()
                    except:
                        pass  # Continue even if image deletion fails
            
            # Delete Firestore document
            doc_ref.delete()
            return True
            
        except Exception as e:
            st.error(f"Error deleting project: {str(e)}")
            return False


# Integration helper functions for your Streamlit app

def integrate_with_streamlit_app():
    """
    Add this to your main streamlit_app.py to integrate Firestore.
    Call this once at app startup.
    """
    
    # Initialize Firestore manager
    if 'firestore_manager' not in st.session_state:
        try:
            # Option 1: Local development with service account key file
            # Make sure you have 'serviceAccount.json' in your project folder
            import os
            if os.path.exists('serviceAccount.json'):
                st.session_state.firestore_manager = ProjectFirestoreManager('serviceAccount.json')
                print("Firestore initialized with local service account")
            
            # Option 2: Use Streamlit secrets (for deployment)
            elif 'firebase' in st.secrets:
                # Get credentials from Streamlit secrets
                firebase_creds = dict(st.secrets["firebase"])
                
                # Write credentials to temp file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    json.dump(firebase_creds, f)
                    temp_path = f.name
                
                st.session_state.firestore_manager = ProjectFirestoreManager(temp_path)
                print("Firestore initialized with Streamlit secrets")
            else:
                st.warning("⚠️ Firebase credentials not configured. Projects will not persist between sessions.")
                st.info("Add 'serviceAccount.json' to your project folder or configure Streamlit secrets.")
                st.session_state.firestore_manager = None
                
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {str(e)}")
            st.session_state.firestore_manager = None
    
    return st.session_state.firestore_manager


def save_current_project_to_cloud():
    """Add this function to save current project to Firestore."""
    if st.session_state.current_project and st.session_state.firestore_manager:
        project = st.session_state.projects[st.session_state.current_project]
        success = st.session_state.firestore_manager.save_project(
            st.session_state.current_project,
            project
        )
        if success:
            st.success("☁️ Project saved to cloud!")
        return success
    return False


def load_projects_from_cloud():
    """Load all user projects from Firestore on app startup."""
    if st.session_state.firestore_manager:
        user_id = st.session_state.get('user_id', 'anonymous')
        project_summaries = st.session_state.firestore_manager.list_user_projects(user_id)
        
        # Load full data for each project
        loaded_count = 0
        for summary in project_summaries:
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
    """
    Simple user identification for separating projects.
    In production, you'd want proper authentication.
    """
    if 'user_id' not in st.session_state:
        # Generate a unique user ID
        st.session_state.user_id = str(uuid.uuid4())
    return st.session_state.user_id


# Test function to verify Firebase connection
def test_firebase_connection():
    """
    Test function to verify Firebase is properly configured.
    Run this to check your setup.
    """
    try:
        manager = ProjectFirestoreManager('serviceAccount.json')
        
        # Create test project
        test_id = str(uuid.uuid4())
        test_project = {
            'id': test_id,
            'name': 'Test Project',
            'description': 'Testing Firebase connection',
            'created_date': datetime.now().isoformat(),
            'last_modified': datetime.now().isoformat(),
            'products_data': [],
            'attributes': [],
            'distributions': [],
            'filter_options': {},
            'pending_changes': {},
            'uploaded_images': {},
            'excel_filename': None
        }
        
        # Try to save
        if manager.save_project(test_id, test_project):
            print("✅ Firebase save successful!")
            
            # Try to load it back
            loaded = manager.load_project(test_id)
            if loaded:
                print("✅ Firebase load successful!")
                
                # Clean up - delete test
                if manager.delete_project(test_id):
                    print("✅ Firebase delete successful!")
                    print("\n🎉 All Firebase operations working correctly!")
                    return True
        
        print("❌ Firebase test failed")
        return False
        
    except Exception as e:
        print(f"❌ Firebase connection error: {str(e)}")
        return False


if __name__ == "__main__":
    # Run test if this file is executed directly
    print("Testing Firebase connection...")
    test_firebase_connection()