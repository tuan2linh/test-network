from utils.database import Database

def test_db_connection():
    db = None
    try:
        db = Database()
        # Attempt to list collections to verify connection
        collections = db.db.list_collection_names()
        print("Connected to the database. Collections:", collections)
        return True
    except Exception as e:
        print("Failed to connect to the database:", e)
        return False
    finally:
        if db:
            db.close()

if __name__ == "__main__":
    test_db_connection()