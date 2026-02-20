import fitz
import re

def debug_words(file_path):
    print(f"--- Debugging Words in {file_path} ---")
    doc = fitz.open(file_path)
    
    for pno, page in enumerate(doc):
        print(f"Page {pno+1}")
        words = page.get_text("words")
        # words: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
        
        days = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY']
        found_days = []
        found_times = []
        
        for w in words:
            text = w[4].upper().strip()
            # Check for Days
            if text in days:
                print(f"Found Day: {text} at {w[:4]}")
                found_days.append({'text': text, 'rect': w[:4]})
            
            # Check for Time patterns (simple check for now)
            if re.match(r'\d{1,2}:\d{2}', text):
                print(f"Found Time: {text} at {w[:4]}")
                found_times.append({'text': text, 'rect': w[:4]})
                
        # Group Times by X (columns)
        # Sort by X
        found_times.sort(key=lambda x: x['rect'][0])
        
        # Group Days by Y (rows)
        # Sort by Y
        found_days.sort(key=lambda x: x['rect'][1])
        
        if found_days and found_times:
            print(f"\nPotential Grid: {len(found_days)} Rows x {len(found_times)} Time markers")
            
            # Define Rows based on Days
            # Each day defines a Y start. Y end is the next day's start.
            rows = []
            for i in range(len(found_days)):
                y_start = found_days[i]['rect'][1] - 5 # buffer
                if i < len(found_days) - 1:
                    y_end = found_days[i+1]['rect'][1] - 5
                else:
                    y_end = y_start + 100 # arbitrary height for last row
                rows.append({'day': found_days[i]['text'], 'y0': y_start, 'y1': y_end})
                
            # Define Columns based on Times
            # This is trickier because "08:30" and "to" and "09:30" might appear.
            # We want unique column starts.
            # Let's cluster X coordinates.
            cols = []
            last_x = -100
            for t in found_times:
                x = t['rect'][0]
                if x - last_x > 20: # New column
                    cols.append({'x': x})
                    last_x = x
            
            print(f"Identified {len(cols)} unique column starts: {[c['x'] for c in cols]}")
            
            # Now extract content
            for r in rows:
                print(f"\n--- {r['day']} ---")
                for i in range(len(cols)):
                    x0 = cols[i]['x']
                    x1 = cols[i+1]['x'] if i < len(cols)-1 else page.rect.width
                    y0 = r['y0']
                    y1 = r['y1']
                    
                    # Find all words in this rect
                    cell_words = []
                    for w in words:
                        wx0, wy0, wx1, wy1 = w[:4]
                        # Check intersection (loosely)
                        if wx0 >= x0 - 5 and wy0 >= y0 and wy1 <= y1 + 5 and wx0 < x1:
                            cell_words.append(w[4])
                    
                    content = " ".join(cell_words)
                    print(f"  Col {i+1} ({int(x0)}-{int(x1)}): {content}")

if __name__ == "__main__":
    debug_words(r"d:\qp\Questgen\paper_generator\uploads\timetables\Computer Science_6_1770457523_6th_sem_TT.pdf")
