import fitz
import re

file_path = r"d:\qp\Questgen\paper_generator\uploads\timetables\Computer Science_1_1770540542_orginal.pdf"

print(f"Analyzing: {file_path}")

try:
    doc = fitz.open(file_path)
    days_keywords = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']

    for page_num, page in enumerate(doc):
        tables = page.find_tables()
        print(f"Page {page_num+1}: Found {len(tables.tables)} tables")
        
        for i, tab in enumerate(tables.tables):
            extracted = tab.extract()
            if not extracted: continue
            
            print(f"\nTable {i+1} ({tab.row_count}x{tab.col_count}):")
            
            # Print first 5 rows' first column to see headers
            for r_idx, row in enumerate(extracted[:15]):
                first_cell = str(row[0]).strip().upper() if row and row[0] else "EMPTY"
                print(f"  Row {r_idx}: First Cell='{first_cell}'")
                
                # Check match against my current logic
                day_match = None
                for day in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY']:
                    if day in first_cell:
                        day_match = day
                        break
                print(f"    -> Matches current logic? {day_match}")
                
except Exception as e:
    print(f"Error: {e}")
