"""Analyze orginal.pdf structure."""
import fitz
import re

file_path = r"d:\qp\Questgen\paper_generator\uploads\orginal.pdf"

doc = fitz.open(file_path)
print(f"Total pages: {len(doc)}")

for page_num, page in enumerate(doc):
    print(f"\n{'='*70}")
    print(f"PAGE {page_num + 1}")
    print(f"{'='*70}")
    
    words = page.get_text("words")
    print(f"\nTotal words: {len(words)}")
    
    if len(words) == 0:
        images = page.get_images(full=True)
        print(f"NO TEXT - {len(images)} image(s) - IMAGE-BASED PDF!")
        continue
    
    # Find semester indicators
    print("\n--- Semester/Class info ---")
    for w in words:
        if 'SEM' in w[4].upper() or 'SEMESTER' in w[4].upper():
            print(f"  '{w[4]}' at Y={w[1]:.1f}")
    
    # Find days
    days = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY']
    print("\n--- Days found ---")
    for w in words:
        if w[4].upper() in days:
            print(f"  '{w[4]}' at Y={w[1]:.1f}, X={w[0]:.1f}")
    
    # Find times
    print("\n--- Times found ---")
    for w in words:
        if re.match(r'\d{1,2}[:.]\d{2}', w[4]):
            print(f"  '{w[4]}' at Y={w[1]:.1f}, X={w[0]:.1f}")
    
    # Show first 30 rows
    print("\n--- First 30 rows ---")
    sorted_words = sorted(words, key=lambda x: (round(x[1]/12)*12, x[0]))
    current_y = -100
    row_text = []
    row_count = 0
    for w in sorted_words:
        y_bucket = round(w[1] / 12) * 12
        if y_bucket != current_y:
            if row_text:
                row_count += 1
                if row_count <= 30:
                    print(f"Row {row_count} (Y~{current_y}): {' | '.join(row_text[:15])}")
            row_text = [w[4]]
            current_y = y_bucket
        else:
            row_text.append(w[4])
    
    # Tables
    print("\n--- Tables ---")
    tabs = page.find_tables()
    print(f"Found {len(tabs.tables)} table(s)")
    for i, tab in enumerate(tabs.tables):
        print(f"\nTable {i+1}: {tab.row_count} rows x {tab.col_count} cols")
        extracted = tab.extract()
        for row_idx, row in enumerate(extracted[:10]):
            cleaned = [str(c).replace('\n', ' ')[:20] if c else '-' for c in row]
            print(f"  Row {row_idx}: {cleaned}")

doc.close()
