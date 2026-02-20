"""Reset all application data except users/login."""
import sqlite3
import os

DB_PATH = 'paper_generator.db'

def reset_data():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    tables_to_clear = [
        'timetable_entries',
        'timetables',
        'events',
        'papers',
        'question_bank',
        'notes',
        # Add any other content tables here
    ]
    
    print("Clearing data...")
    for table in tables_to_clear:
        try:
            cursor.execute(f"DELETE FROM {table}")
            print(f"  - Cleared {table}")
        except sqlite3.OperationalError as e:
            print(f"  - Error clearing {table}: {e}")
            
    # Optional: Reset sequence for auto-increment IDs
    for table in tables_to_clear:
        try:
            cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")
        except:
            pass
            
    conn.commit()
    conn.close()
    print("\nData reset complete. Users/Login data preserved.")

if __name__ == "__main__":
    reset_data()
