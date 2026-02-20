import fitz
import re
import os

# Exact logic from app.py
def debug_parse(file_path):
    doc = fitz.open(file_path)
    parsed_count = 0
    days_keywords = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    
    print(f"Keywords: {days_keywords}")
    
    for page in doc:
        tables = page.find_tables()
        if not tables.tables:
            print("No tables")
            continue
            
        timetable_grid = None
        
        for i, tab in enumerate(tables.tables):
            extracted = tab.extract()
            if not extracted: continue
            
            first_col_values = [str(row[0]).upper() if row and row[0] else '' for row in extracted]
            has_days = any(day in ' '.join(first_col_values) for day in days_keywords)
            
            print(f"Table {i}: Rows={tab.row_count} Col={tab.col_count} HasDays={has_days}")
            if has_days:
                 print(f"  First col sample: {first_col_values[:3]}")
            
            if has_days and tab.col_count >= 8:
                timetable_grid = extracted
        
        if timetable_grid:
            print("Processing Timetable Grid...")
            time_slots = []
            for idx, row in enumerate(timetable_grid[:3]):
                times_found = []
                for cell in row:
                    if cell and re.search(r'\d{1,2}:\d{2}', str(cell)):
                        times_found.append(str(cell).strip())
                if times_found:
                    time_slots = times_found
                    break
            
            print(f"Time Slots: {time_slots}")
            
            for r_idx, row in enumerate(timetable_grid):
                if not row or not row[0]: continue
                
                first_cell = str(row[0]).strip().upper()
                print(f"  Row {r_idx}: '{first_cell}'")
                
                if 'DAY' in first_cell or 'TIME' in first_cell or first_cell == '-':
                    print("    -> Skip Header")
                    continue
                
                day_name = None
                for day in days_keywords:
                    if day in first_cell:
                        day_name = day[:3].title()
                        print(f"    -> Match Day: {day_name} (Keyword: {day})")
                        break
                
                if not day_name:
                    print("    -> No Day Match")
                    continue
                
                for col_idx, cell in enumerate(row[1:], start=1):
                    if not cell or str(cell).strip() == '-': continue
                    content = str(cell).strip().replace('\n', ' ')
                    
                    if 'BREAK' in content.upper() or 'LUNCH' in content.upper():
                        continue
                        
                    if len(content) > 1:
                        print(f"      -> FOUND CLASS: {content}")
                        parsed_count += 1
                        
    print(f"Total Parsed: {parsed_count}")

# Find most recent PDF
upload_dir = r"d:\qp\Questgen\paper_generator\uploads\timetables"
files = [os.path.join(upload_dir, f) for f in os.listdir(upload_dir) if f.endswith(".pdf")]
latest_file = max(files, key=os.path.getctime)
print(f"Analyzing: {latest_file}")
debug_parse(latest_file)
