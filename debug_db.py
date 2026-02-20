from database import get_db

def check_db():
    conn = get_db()
    cursor = conn.cursor()
    
    print("--- Timetables Schema ---")
    cursor.execute("PRAGMA table_info(timetables)")
    columns = cursor.fetchall()
    for col in columns:
        print(dict(col))
        
    print("\n--- Timetables Files ---")
    cursor.execute("SELECT * FROM timetables")
    tts = cursor.fetchall()
    for tt in tts:
        print(dict(tt))
        
    print("\n--- Timetable Entries ---")
    cursor.execute("SELECT * FROM timetable_entries")
    entries = cursor.fetchall()
    print(f"Total Entries: {len(entries)}")
    for e in entries[:10]:
        print(dict(e))
        
    print("\n--- Events ---")
    cursor.execute("SELECT * FROM events")
    events = cursor.fetchall()
    print(f"Total Events: {len(events)}")
    for e in events[:10]:
        print(dict(e))
        
    conn.close()

if __name__ == "__main__":
    check_db()
