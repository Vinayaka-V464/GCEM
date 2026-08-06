"""Reset the local SQLite database to a clean state."""
import os

from database import DB_PATH, init_db


def reset_data():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed {DB_PATH}")
    else:
        print(f"Database {DB_PATH} not found.")

    init_db()
    print("\nFresh SQLite database created.")

if __name__ == "__main__":
    reset_data()
