"""Analyze the 2nd.pdf structure to understand why parsing failed."""
import fitz
import os

file_path = r"d:\qp\Questgen\paper_generator\2nd.pdf"

doc = fitz.open(file_path)

for page_num, page in enumerate(doc):
    print(f"\n{'='*60}")
    print(f"PAGE {page_num + 1}")
    print(f"{'='*60}")
    
    # Get all words with coordinates
    words = page.get_text("words")
    print(f"\nTotal words: {len(words)}")
    
    # Find days to understand structure
    days = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 
            'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    
    print("\n--- Day markers found ---")
    for w in words:
        if w[4].upper() in days:
            print(f"  {w[4]} at Y={w[1]:.1f}, X={w[0]:.1f}")
    
    # Find time patterns
    print("\n--- Time patterns found ---")
    import re
    for w in words:
        if re.match(r'\d{1,2}[:.]\d{2}', w[4]):
            print(f"  {w[4]} at Y={w[1]:.1f}, X={w[0]:.1f}")
    
    # Print first 50 words to understand structure
    print("\n--- First 50 words (sorted by Y, then X) ---")
    sorted_words = sorted(words, key=lambda x: (round(x[1]/10)*10, x[0]))
    for i, w in enumerate(sorted_words[:50]):
        print(f"  {i+1}. Y={w[1]:.1f} X={w[0]:.1f}: '{w[4]}'")
    
    # Try to find tables
    print("\n--- Tables detected ---")
    tabs = page.find_tables()
    print(f"Found {len(tabs.tables)} table(s)")
    for i, tab in enumerate(tabs.tables):
        print(f"\nTable {i+1}: {tab.row_count} rows x {tab.col_count} cols")
        # Print a few rows
        extracted = tab.extract()
        for row_idx, row in enumerate(extracted[:8]):
            print(f"  Row {row_idx}: {row}")

doc.close()
