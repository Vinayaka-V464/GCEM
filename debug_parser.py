import fitz
import re
from datetime import datetime

def parse_timetable_pdf(file_path):
    print(f"--- Parsing {file_path} ---")
    try:
        doc = fitz.open(file_path)
        
        time_slots = [
            "9:30 - 10:30", "10:30 - 11:30", "11:30 - 11:45 (Break)", 
            "11:45 - 12:45", "12:45 - 1:45 (Lunch)", "1:45 - 2:45", 
            "2:45 - 3:45", "3:45 - 4:45"
        ]
        
        for i, page in enumerate(doc):
            print(f"Page {i+1}")
            # Try text strategy first as lines might be missing
            tables = page.find_tables(vertical_strategy="text", horizontal_strategy="text")
            if not tables:
                print("No tables found with text strategy, trying lines...")
                tables = page.find_tables()
            
            if not tables:
                print("No tables found")
                continue
                
            for j, table in enumerate(tables):
                print(f"Table {j+1}")
                data = table.extract()
                for row_idx, row in enumerate(data):
                    print(f"Row {row_idx}: {row}")
                    if not row or not row[0]: 
                        print("  Skipping empty row/cell")
                        continue
                    
                    day_raw = row[0]
                    day = day_raw.upper().strip()[:3] if day_raw else ""
                    print(f"  Day extracted: '{day}' from '{day_raw}'")
                    
                    if day in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']:
                        print("  MATCHED DAY!")
                        col_idx = 1
                        slot_idx = 0
                        while col_idx < len(row) and slot_idx < len(time_slots):
                            subject = row[col_idx]
                            current_slot = time_slots[slot_idx]
                            print(f"    Slot {current_slot}: '{subject}'")
                            col_idx += 1
                            slot_idx += 1
                    else:
                        print("  Day NOT matched")

    except Exception as e:
        print(f"Error parsing timetable: {e}")

if __name__ == "__main__":
    parse_timetable_pdf(r"d:\qp\Questgen\paper_generator\uploads\timetables\Computer Science_6_1770457203_6th_sem_TT.pdf")
