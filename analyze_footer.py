"""Analyze the teacher/course table structure in the timetable PDF."""
import fitz
import os

file_path = r"d:\qp\Questgen\paper_generator\uploads\timetables\Computer Science_6_1770457523_6th_sem_TT.pdf"

doc = fitz.open(file_path)

for page_num, page in enumerate(doc):
    print(f"\n=== PAGE {page_num + 1} ===")
    
    # Get all words with coordinates
    words = page.get_text("words")
    
    # Find the bottom section (below timetable grid)
    # The timetable usually ends around y=400-500
    # Footer table starts after
    
    # First find where the main grid ends by looking for last day row
    days = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY']
    max_day_y = 0
    for w in words:
        if w[4].upper() in days:
            if w[3] > max_day_y:  # w[3] is y1 (bottom of word)
                max_day_y = w[3]
    
    print(f"Last day row ends at Y: {max_day_y}")
    
    # Get all words below the grid
    footer_words = [w for w in words if w[1] > max_day_y + 50]  # w[1] is y0
    
    print(f"\n--- Footer Words (Y > {max_day_y + 50}) ---")
    # Sort by Y then X
    footer_words.sort(key=lambda x: (round(x[1] / 15) * 15, x[0]))  # Group by ~15px rows
    
    current_row_y = -100
    current_row = []
    
    for w in footer_words:
        y = round(w[1] / 15) * 15  # Bucket by 15px
        if y != current_row_y:
            if current_row:
                print(f"Row Y~{current_row_y}: {' | '.join([cw[4] for cw in current_row])}")
            current_row = [w]
            current_row_y = y
        else:
            current_row.append(w)
    
    if current_row:
        print(f"Row Y~{current_row_y}: {' | '.join([cw[4] for cw in current_row])}")
    
    # Also try to find tables using fitz
    print("\n--- Tables detected by fitz ---")
    tabs = page.find_tables()
    print(f"Found {len(tabs.tables)} table(s)")
    for i, tab in enumerate(tabs.tables):
        print(f"\nTable {i+1}: {tab.row_count} rows x {tab.col_count} cols")
        for row in tab.extract()[:10]:  # First 10 rows
            print(row)

doc.close()
