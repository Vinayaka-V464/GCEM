"""Test the updated timetable parsing to verify JSON output."""
import sys
import os

# Add the project directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app import parse_timetable_pdf
from database import get_timetables, init_db

# Init DB
init_db()

file_path = r"d:\qp\Questgen\paper_generator\uploads\timetables\Computer Science_6_1770457523_6th_sem_TT.pdf"
department = "Computer Science"
semester = "6"

print(f"Testing parse_timetable_pdf with:")
print(f"  File: {file_path}")
print(f"  Dept: {department}, Sem: {semester}\n")

# Run parsing
result = parse_timetable_pdf(file_path, department, semester)
print(f"Parse result: {result}\n")

# Check DB
print("--- Checking Details in DB ---")
timetables = get_timetables(department)
for t in timetables:
    if str(t['semester']) == semester:
        details = t['details']
        print(f"Details field type: {type(details)}")
        print(f"Details value (first 500 chars):\n{details[:500] if details else 'None'}")
        
        # Try to parse as JSON
        if details:
            import json
            try:
                parsed = json.loads(details)
                print(f"\nParsed JSON successfully! {len(parsed)} entries:")
                for item in parsed[:5]:  # First 5
                    print(f"  - {item}")
            except json.JSONDecodeError as e:
                print(f"\nJSON parse error: {e}")
        break
