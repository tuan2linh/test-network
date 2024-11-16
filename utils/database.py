# database.py
from pymongo import MongoClient
from datetime import datetime
from gridfs import GridFS

class Database:
    def __init__(self):
        try:
            connection_string = "mongodb+srv://tuanlinhx2:JxqHwze6XPirZ176@file-trasfer-sharing.ltfi2.mongodb.net/?retryWrites=true&w=majority"
            self.client = MongoClient(connection_string, 
                                    serverSelectionTimeoutMS=5000)
            # Test the connection
            self.client.server_info()
            
            self.db = self.client["file_sharing"]
            self.fs = GridFS(self.db)
        except Exception as e:
            print(f"Database connection error: {str(e)}")
            raise
            
    def close(self):
        if hasattr(self, 'client'):
            self.client.close()