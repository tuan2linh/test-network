from utils.database import Database
import os
import datetime

class FileUploader:
    def __init__(self):
        self.db = Database()

    def upload_file(self, file_path):
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File {file_path} not found")

            filename = os.path.basename(file_path)
            
            # Read file and upload to GridFS
            with open(file_path, 'rb') as file:
                file_id = self.db.fs.put(
                    file.read(),
                    filename=filename,
                    upload_date=datetime.datetime.now()
                )
                
            print(f"File {filename} uploaded successfully with id: {file_id}")
            return file_id
            
        except Exception as e:
            print(f"Error uploading file: {str(e)}")
            return None

if __name__ == "__main__":
    uploader = FileUploader()
    file_path = input("Enter file path to upload: ")
    uploader.upload_file(file_path)