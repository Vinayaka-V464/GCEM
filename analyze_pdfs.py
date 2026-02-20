import fitz

def analyze_pdf(pdf_path):
    print(f"--- Analysis of {pdf_path} ---")
    try:
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            print(f"Page {page_num + 1}:")
            text = page.get_text("text")
            print("Text Sample (first 500 chars):")
            print(text[:500])
            print("-" * 20)
            
            tables = page.find_tables()
            if tables:
                print(f"Found {len(tables.tables)} tables.")
                for i, table in enumerate(tables):
                    print(f"Table {i+1} Extract (first 5 rows):")
                    print(table.extract()[:5])
            else:
                print("No tables found via find_tables().")
            print("=" * 30)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_pdf(r"d:\qp\Questgen\paper_generator\uploads\timetables\Computer Science_6_1770457523_6th_sem_TT.pdf")
