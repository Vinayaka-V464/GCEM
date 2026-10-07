# Paper Generator - Digital Campus

A Flask-based academic workflow app for generating question papers, managing approvals, and providing a digital campus experience (timetables, calendars, notes, and question banks). Includes HOD tooling, staff management, and an automatic bench allotment blueprint with print-ready layouts.

## Core Features
- Role-based access for **HOD**, **Teacher/Faculty**, and **Student**.
- **Firebase Authentication** (Email/Password + Google Sign-in + Email Verification).
- **Teacher workflow**
  - Upload Question Banks and Notes
  - Generate question papers from selected modules
  - Preview and submit to HOD for approval
  - Track status (draft/pending/approved/rejected)
- **HOD workflow**
  - Approve/reject papers, view history
  - Manage staff approvals and assignments
  - Manage subject and section catalogs
  - Upload timetable PDFs and calendar PDFs (auto parsing)
  - Upload HOD and Principal signatures
  - Bench allotment blueprint generation (print-ready)
- **Student workflow**
  - Access notes and question banks by semester/section
  - View calendar of events and timetable
- **Digital Campus**
  - Section-wise timetable rendering
  - Calendar of events with filters and detail popups
- **Bench Allotment (NEW)**
  - Manual input for rooms, benches, and multiple semesters
  - Column-wise seating order for easy paper collection
  - Strong alternation across semesters to reduce adjacency conflicts
  - Printable blueprint layout with roll numbers and semesters
- **UI/UX**
  - Glassmorphism-based modern UI
  - Light/Dark theme toggle stored in localStorage
  - Print-friendly layout support

## Project Structure
- `app.py` - Flask app, routes, parsing, bench allotment algorithm
- `database.py` - SQLite access layer
- `templates/` - HTML templates for dashboards, auth, tools
- `static/` - CSS/JS assets
- `uploads/` - Stored PDFs, signatures, notes, question banks
- `paper_generator.db` - SQLite database (auto created)

## Setup
### 1) Install dependencies
```bash
pip install -r requirements.txt
```

### 2) Configure environment variables
Create a local `.env` file with the provided Firebase keys, secret key, and SQLite path. The app uses `paper_generator.db` locally.

### 3) Configure Firebase Auth
Firebase config is in:
```
static/js/firebase-auth.js
```
Replace with your Firebase project values if needed.

### 4) Run the app
```bash
python app.py
```

The app will create the database and upload folders on startup.

## Environment
- Python 3.9+ recommended
- Flask + SQLite
- PyMuPDF for PDF parsing
- Set `UPLOAD_ROOT` to configure local file storage. On Vercel, uploads default to `/tmp/paper-generator-uploads` because the deployed filesystem is read-only outside `/tmp`.
- Vercel `/tmp` storage is temporary and instance-local. Configure an external object-storage provider before relying on uploaded files in production.

## Bench Allotment Usage
1. Open **HOD Dashboard ? Bench Allotment**.
2. Enter:
   - Exam date/time
   - Seats per bench (default: 3)
   - Room list (room number, rows, columns)
   - Group list (semester, prefix, roll ranges)
3. Click **Generate Blueprint** to visualize seating.
4. Use **Print Blueprint** for a clean print layout.

## Notes
- Timetable/Calendar uploads are semester and section-aware.
- Calendar re-uploads clear old entries for the selected semester.
- Scroll position is restored after post/redirect to avoid jump-to-top.

## Common Files
- `templates/bench_allotment.html` - blueprint visual layout + print
- `templates/digital_campus.html` - timetable + calendar UI
- `templates/hod_dashboard.html` - HOD overview & tools
- `templates/index.html` - paper generation

## Security
Set a production secret key via environment variable:
```
SECRET_KEY=your-secret
```

## License
Internal project.
