from utils.database import Database
import os
from bson.objectid import ObjectId
from gridfs.errors import NoFile

class FileDownloader:
    def __init__(self):
        self.db = Database()

    def download_file(self, file_id, download_path):
        try:
            # Convert string ID to ObjectId
            obj_id = ObjectId(file_id)
            
            # Check if file exists first
            if not self.db.fs.exists(obj_id):
                print(f"File with ID {file_id} does not exist")
                return None

            # Get file from GridFS
            file_data = self.db.fs.get(obj_id)
            filename = file_data.filename
            
            # Create download path if not exists
            os.makedirs(download_path, exist_ok=True)
            
            # Save file
            output_path = os.path.join(download_path, filename)
            with open(output_path, 'wb') as file:
                file.write(file_data.read())
                
            print(f"File downloaded successfully to: {output_path}")
            return output_path
            
        except NoFile:
            print(f"File with ID {file_id} not found in GridFS")
            return None
        except Exception as e:
            print(f"Error downloading file: {str(e)}")
            return None

    def list_files(self):
        try:
            files = self.db.fs.find()
            print("\nAvailable files:")
            for file in files:
                size = file.length / 1024  # Convert to KB
                upload_date = file.uploadDate.strftime("%Y-%m-%d %H:%M:%S")
                print(f"ID: {file._id}, Filename: {file.filename}")
                print(f"Size: {size:.2f}KB, Uploaded: {upload_date}\n")
        except Exception as e:
            print(f"Error listing files: {str(e)}")

if __name__ == "__main__":
    downloader = FileDownloader()
    
    # List available files
    downloader.list_files()
    
    # Get user input
    file_id = input("\nEnter file ID to download: ")
    download_path = input("Enter download path: ")
    
    # Download file
    downloader.download_file(file_id, download_path)