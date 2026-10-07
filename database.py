# ==============================================================================
# FILE: database.py
# Dual-mode: SQLite for local dev, PostgreSQL (Neon) for production.
# Automatically detected via DATABASE_URL environment variable.
# ==============================================================================

import os
import json
from datetime import datetime
from urllib.parse import urlparse

# Load .env for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()


def _is_postgres_url(url):
    return url.lower().startswith(('postgres://', 'postgresql://'))


if os.environ.get('VERCEL') and not _is_postgres_url(DATABASE_URL):
    raise RuntimeError(
        'A PostgreSQL DATABASE_URL is required on Vercel. Configure a connection string '
        'starting with postgres:// or postgresql://; SQLite is not persistent or writable there.'
    )


def _sqlite_path_from_url(url):
    parsed = urlparse(url)
    path = parsed.path or ''
    if path.startswith('/') and len(path) > 2 and path[2] == ':':
        path = path[1:]
    else:
        path = path.lstrip('/')
    if not path:
        return os.path.join(os.path.dirname(__file__), 'paper_generator.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    return os.path.abspath(path)


_USE_PG = _is_postgres_url(DATABASE_URL)

if _USE_PG:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise RuntimeError(
            'DATABASE_URL points to PostgreSQL, but psycopg2 is not installed. '
            'Install requirements or unset DATABASE_URL to use SQLite locally.'
        ) from exc
    PH = '%s'   # PostgreSQL placeholder
else:
    import sqlite3
    PH = '?'    # SQLite placeholder
    _SQLITE_PATH = _sqlite_path_from_url(DATABASE_URL) if DATABASE_URL.lower().startswith('sqlite://') else os.path.join(os.path.dirname(__file__), 'paper_generator.db')

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_db():
    """Return a DB connection.  Rows are always accessible as dicts."""
    if _USE_PG:
        conn = psycopg2.connect(DATABASE_URL,
                                cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(_SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        return conn


def _fix(sql):
    """
    Translate PostgreSQL-flavoured SQL to SQLite when running locally:
      %s  →  ?
      SERIAL PRIMARY KEY  →  INTEGER PRIMARY KEY AUTOINCREMENT
      RETURNING id        →  (stripped — handled separately)
      ADD COLUMN IF NOT EXISTS  →  ADD COLUMN IF NOT EXISTS  (SQLite 3.37+)
      TIMESTAMP  →  TEXT
      ON CONFLICT … DO NOTHING / DO UPDATE  →  kept as-is (SQLite supports these)
    """
    if _USE_PG:
        return sql
    sql = sql.replace('%s', '?')
    sql = sql.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
    sql = sql.replace(' TIMESTAMP ', ' TEXT ')
    sql = sql.replace(' TIMESTAMP\n', ' TEXT\n')
    sql = sql.replace('DEFAULT CURRENT_TIMESTAMP', "DEFAULT (datetime('now'))")
    # Strip RETURNING clause (handled via lastrowid)
    import re
    sql = re.sub(r'\s*RETURNING\s+\w+\s*$', '', sql, flags=re.IGNORECASE)
    return sql


def _execute_returning(cursor, sql, params=()):
    """Execute an INSERT … RETURNING id and return the new id."""
    if _USE_PG:
        cursor.execute(sql, params)
        return cursor.fetchone()['id']
    else:
        cursor.execute(_fix(sql), params)
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def init_db():
    """Create all tables (idempotent)."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            role TEXT,
            department TEXT,
            signature_path TEXT,
            principal_signature_path TEXT,
            phone TEXT,
            semester TEXT,
            section TEXT,
            profile_complete INTEGER DEFAULT 0,
            approved_by_hod INTEGER DEFAULT 0,
            photo_url TEXT,
            email_verified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            title TEXT,
            course_code TEXT,
            course_name TEXT,
            department TEXT,
            paper_data TEXT,
            pdf_path TEXT,
            status TEXT DEFAULT 'draft',
            teacher_signature TEXT,
            hod_signature TEXT,
            principal_signature TEXT,
            rejection_comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            submitted_at TIMESTAMP,
            approved_at TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            department TEXT,
            file_path TEXT NOT NULL,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))


    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            department TEXT,
            file_path TEXT NOT NULL,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT,
            semester TEXT,
            section TEXT,
            title TEXT,
            file_path TEXT NOT NULL,
            file_name TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS teacher_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            subject_code TEXT,
            subject_name TEXT,
            semester TEXT,
            department TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS teacher_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            semester TEXT,
            section TEXT,
            department TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(teacher_id, semester, section),
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS section_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            semester TEXT NOT NULL,
            section TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(department, semester, section)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS subject_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            semester TEXT NOT NULL,
            subject_code TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(department, semester, subject_code)
        )
    '''))


    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            event_date DATE,
            event_time TEXT,
            location TEXT,
            department TEXT,
            semester TEXT,
            type TEXT DEFAULT 'event',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS timetable_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT,
            semester TEXT,
            section TEXT,
            day TEXT,
            time_slot TEXT,
            subject TEXT,
            teacher_name TEXT,
            room TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS teacher_timetable_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            day TEXT NOT NULL,
            slot_code TEXT NOT NULL,
            slot_label TEXT NOT NULL,
            status TEXT DEFAULT 'leisure',
            subject TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(teacher_id, day, slot_code),
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS exam_duty_exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT,
            exam_date DATE NOT NULL,
            day TEXT NOT NULL,
            slot TEXT NOT NULL,
            subject TEXT NOT NULL,
            branch TEXT,
            semester TEXT,
            room TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS exam_duty_teacher_settings (
            teacher_id TEXT PRIMARY KEY,
            max_duties INTEGER DEFAULT 3,
            active INTEGER DEFAULT 1,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    cur.execute(_fix('''
        CREATE TABLE IF NOT EXISTS exam_duty_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL UNIQUE,
            teacher_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_id) REFERENCES exam_duty_exams(id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    '''))

    # Safe column additions (PostgreSQL supports IF NOT EXISTS natively;
    # SQLite 3.37+ does too — we catch errors silently for older SQLite)
    safe_alters = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS principal_signature_path TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_complete INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by_hod INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS semester TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS section TEXT",
        "ALTER TABLE timetables ADD COLUMN IF NOT EXISTS details TEXT",
        "ALTER TABLE timetables ADD COLUMN IF NOT EXISTS section TEXT",
        "ALTER TABLE papers ADD COLUMN IF NOT EXISTS principal_signature TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'event'",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS semester TEXT",
        "ALTER TABLE timetable_entries ADD COLUMN IF NOT EXISTS section TEXT",
        "ALTER TABLE teacher_timetable_slots ADD COLUMN IF NOT EXISTS slot_label TEXT",
        "ALTER TABLE teacher_timetable_slots ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'leisure'",
        "ALTER TABLE teacher_timetable_slots ADD COLUMN IF NOT EXISTS subject TEXT",
        "ALTER TABLE teacher_timetable_slots ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE teacher_timetable_slots ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE exam_duty_exams ADD COLUMN IF NOT EXISTS department TEXT",
        "ALTER TABLE exam_duty_exams ADD COLUMN IF NOT EXISTS active INTEGER DEFAULT 1",
        "ALTER TABLE exam_duty_exams ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE exam_duty_teacher_settings ADD COLUMN IF NOT EXISTS max_duties INTEGER DEFAULT 3",
        "ALTER TABLE exam_duty_teacher_settings ADD COLUMN IF NOT EXISTS active INTEGER DEFAULT 1",
        "ALTER TABLE exam_duty_teacher_settings ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE exam_duty_teacher_settings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE exam_duty_assignments ADD COLUMN IF NOT EXISTS exam_id INTEGER",
        "ALTER TABLE exam_duty_assignments ADD COLUMN IF NOT EXISTS teacher_id TEXT",
    ]
    for stmt in safe_alters:
        try:
            cur.execute(_fix(stmt))
        except Exception:
            pass  # column already exists on older SQLite

    conn.commit()
    conn.close()
    print(f"Database initialised ({'PostgreSQL' if _USE_PG else 'SQLite'}).")


# ---------------------------------------------------------------------------
# USER FUNCTIONS
# ---------------------------------------------------------------------------

def _row(r):
    """Convert a sqlite3.Row or psycopg2 RealDictRow to a plain dict."""
    return dict(r) if r else None


def create_user(uid, email, name, role, department=None, photo_url=None,
                email_verified=False, phone=None, semester=None, section=None):
    conn = get_db()
    cur = conn.cursor()
    try:
        approved_by_hod = 1 if role in ['hod', 'student'] else 0
        profile_complete = 1 if role in ['hod', 'student'] else 0
        cur.execute(_fix('''
            INSERT INTO users
                (id, email, name, role, department, photo_url, email_verified,
                 approved_by_hod, profile_complete, phone, semester, section)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, role=EXCLUDED.role,
                department=EXCLUDED.department, photo_url=EXCLUDED.photo_url,
                email_verified=EXCLUDED.email_verified,
                phone=COALESCE(EXCLUDED.phone, users.phone),
                semester=COALESCE(EXCLUDED.semester, users.semester),
                section=COALESCE(EXCLUDED.section, users.section)
        '''), (uid, email, name, role, department, photo_url,
               1 if email_verified else 0, approved_by_hod, profile_complete,
               phone, semester, section))
        conn.commit()
        return True
    finally:
        conn.close()


def get_user(uid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('SELECT * FROM users WHERE id = %s'), (uid,))
    row = _row(cur.fetchone())
    conn.close()
    if row:
        if row.get('role') in ['teacher', 'faculty']:
            row['subjects'] = get_teacher_subjects(uid)
            row['sections'] = get_teacher_sections(uid)
    return row


def get_user_by_email(email):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('SELECT * FROM users WHERE email = %s'), (email,))
    row = _row(cur.fetchone())
    conn.close()
    if row:
        if row.get('role') in ['teacher', 'faculty']:
            row['subjects'] = get_teacher_subjects(row.get('id'))
            row['sections'] = get_teacher_sections(row.get('id'))
    return row


def update_user_signature(uid, signature_path):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('UPDATE users SET signature_path = %s WHERE id = %s'), (signature_path, uid))
    conn.commit()
    conn.close()


def update_principal_signature(uid, signature_path):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('UPDATE users SET principal_signature_path = %s WHERE id = %s'), (signature_path, uid))
    conn.commit()
    conn.close()


def update_teacher_profile(uid, phone=None, profile_complete=False, semester=None, section=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix(
        'UPDATE users SET phone=%s, profile_complete=%s, '
        'semester=COALESCE(%s, semester), section=COALESCE(%s, section) WHERE id=%s'),
        (phone, 1 if profile_complete else 0, semester, section, uid))
    conn.commit()
    conn.close()


def set_teacher_approval(uid, approved):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('UPDATE users SET approved_by_hod = %s WHERE id = %s'), (1 if approved else 0, uid))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# TEACHER SUBJECT / SECTION FUNCTIONS
# ---------------------------------------------------------------------------

def add_teacher_subject(teacher_id, subject_code, subject_name, semester, department):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('''
        INSERT INTO teacher_subjects (teacher_id, subject_code, subject_name, semester, department)
        VALUES (%s, %s, %s, %s, %s)
    '''), (teacher_id, subject_code, subject_name, semester, department))
    conn.commit()
    conn.close()


def remove_teacher_subject(subject_id, teacher_id=None):
    conn = get_db()
    cur = conn.cursor()
    if teacher_id:
        cur.execute(_fix('DELETE FROM teacher_subjects WHERE id=%s AND teacher_id=%s'), (subject_id, teacher_id))
    else:
        cur.execute(_fix('DELETE FROM teacher_subjects WHERE id=%s'), (subject_id,))
    conn.commit()
    conn.close()


def clear_teacher_subjects(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('DELETE FROM teacher_subjects WHERE teacher_id=%s'), (teacher_id,))
    conn.commit()
    conn.close()


def get_teacher_subjects(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('''
        SELECT id, subject_code, subject_name, semester, department
        FROM teacher_subjects WHERE teacher_id=%s ORDER BY semester, subject_code
    '''), (teacher_id,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_teacher_section(teacher_id, semester, section, department):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('''
            INSERT INTO teacher_sections (teacher_id, semester, section, department)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (teacher_id, semester, section) DO NOTHING
        '''), (teacher_id, str(semester).strip(), str(section).strip().upper(), department))
        conn.commit()
        return True
    finally:
        conn.close()


def remove_teacher_section(section_id, teacher_id=None):
    conn = get_db()
    cur = conn.cursor()
    if teacher_id:
        cur.execute(_fix('DELETE FROM teacher_sections WHERE id=%s AND teacher_id=%s'), (section_id, teacher_id))
    else:
        cur.execute(_fix('DELETE FROM teacher_sections WHERE id=%s'), (section_id,))
    conn.commit()
    conn.close()


def clear_teacher_sections(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('DELETE FROM teacher_sections WHERE teacher_id=%s'), (teacher_id,))
    conn.commit()
    conn.close()


def get_teacher_sections(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('''
        SELECT id, semester, section, department FROM teacher_sections
        WHERE teacher_id=%s ORDER BY semester, section
    '''), (teacher_id,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def replace_teacher_assignments(from_teacher_id, to_teacher_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('SELECT subject_code, subject_name, semester, department FROM teacher_subjects WHERE teacher_id=%s'), (from_teacher_id,))
        for s in cur.fetchall():
            s = _row(s)
            cur.execute(_fix('''
                INSERT INTO teacher_subjects (teacher_id, subject_code, subject_name, semester, department)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            '''), (to_teacher_id, s['subject_code'], s['subject_name'], s['semester'], s['department']))

        cur.execute(_fix('SELECT semester, section, department FROM teacher_sections WHERE teacher_id=%s'), (from_teacher_id,))
        for s in cur.fetchall():
            s = _row(s)
            cur.execute(_fix('''
                INSERT INTO teacher_sections (teacher_id, semester, section, department)
                VALUES (%s, %s, %s, %s) ON CONFLICT (teacher_id, semester, section) DO NOTHING
            '''), (to_teacher_id, s['semester'], s['section'], s['department']))

        cur.execute(_fix('DELETE FROM teacher_subjects WHERE teacher_id=%s'), (from_teacher_id,))
        cur.execute(_fix('DELETE FROM teacher_sections WHERE teacher_id=%s'), (from_teacher_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PAPER FUNCTIONS
# ---------------------------------------------------------------------------

def create_paper(teacher_id, title, course_code, course_name, department,
                 paper_data, pdf_path=None, teacher_signature=None, status='draft'):
    conn = get_db()
    cur = conn.cursor()
    new_id = _execute_returning(cur, '''
        INSERT INTO papers
            (teacher_id, title, course_code, course_name, department,
             paper_data, pdf_path, teacher_signature, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (teacher_id, title, course_code, course_name, department,
          json.dumps(paper_data), pdf_path, teacher_signature, status))
    conn.commit()
    conn.close()
    return new_id


def get_paper(paper_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('SELECT * FROM papers WHERE id=%s'), (paper_id,))
    row = _row(cur.fetchone())
    conn.close()
    if row:
        row['paper_data'] = json.loads(row['paper_data']) if row.get('paper_data') else {}
    return row


def get_papers_by_teacher(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('SELECT * FROM papers WHERE teacher_id=%s ORDER BY created_at DESC'), (teacher_id,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_pending_papers(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('''
            SELECT p.*, u.name as teacher_name FROM papers p
            JOIN users u ON p.teacher_id=u.id
            WHERE p.status='pending' AND p.department=%s ORDER BY p.submitted_at DESC
        '''), (department,))
    else:
        cur.execute(_fix('''
            SELECT p.*, u.name as teacher_name FROM papers p
            JOIN users u ON p.teacher_id=u.id
            WHERE p.status='pending' ORDER BY p.submitted_at DESC
        '''))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def submit_paper(paper_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix("UPDATE papers SET status='pending', submitted_at=%s WHERE id=%s"),
                (datetime.now().isoformat(), paper_id))
    conn.commit()
    conn.close()


def approve_paper(paper_id, hod_signature, principal_signature):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('''
        UPDATE papers SET status='approved', hod_signature=%s,
        principal_signature=%s, approved_at=%s WHERE id=%s
    '''), (hod_signature, principal_signature, datetime.now().isoformat(), paper_id))
    conn.commit()
    conn.close()


def reject_paper(paper_id, comments):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix("UPDATE papers SET status='rejected', rejection_comments=%s WHERE id=%s"),
                (comments, paper_id))
    conn.commit()
    conn.close()


def get_all_papers_for_hod(department=None, teacher_id=None, course_code=None, status=None):
    conn = get_db()
    cur = conn.cursor()
    query = 'SELECT p.*, u.name as teacher_name FROM papers p JOIN users u ON p.teacher_id=u.id WHERE 1=1'
    params = []
    if department:
        query += _fix(' AND p.department=%s'); params.append(department)
    if teacher_id:
        query += _fix(' AND p.teacher_id=%s'); params.append(teacher_id)
    if course_code:
        query += _fix(' AND p.course_code LIKE %s'); params.append(f'%{course_code}%')
    if status:
        query += _fix(' AND p.status=%s'); params.append(status)
    query += ' ORDER BY p.created_at DESC'
    cur.execute(_fix(query), params)
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_all_teachers(department=None):
    conn = get_db()
    cur = conn.cursor()
    cols = 'id,name,email,phone,semester,section,approved_by_hod,profile_complete,email_verified'
    if department:
        cur.execute(_fix(f"SELECT {cols} FROM users WHERE role IN ('teacher','faculty') AND department=%s"), (department,))
    else:
        cur.execute(_fix(f"SELECT {cols} FROM users WHERE role IN ('teacher','faculty')"))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_pending_teachers(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('''
            SELECT id,name,email,phone,department FROM users
            WHERE role IN ('teacher','faculty') AND department=%s
              AND profile_complete=1 AND approved_by_hod=0 ORDER BY created_at DESC
        '''), (department,))
    else:
        cur.execute(_fix('''
            SELECT id,name,email,phone,department FROM users
            WHERE role IN ('teacher','faculty') AND profile_complete=1
              AND approved_by_hod=0 ORDER BY created_at DESC
        '''))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# HOD CATALOG FUNCTIONS
# ---------------------------------------------------------------------------

def add_section_catalog(department, semester, section):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('''
            INSERT INTO section_catalog (department, semester, section)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
        '''), (department, str(semester).strip(), str(section).strip().upper()))
        conn.commit()
        return True
    finally:
        conn.close()


def remove_section_catalog(section_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('DELETE FROM section_catalog WHERE id=%s'), (section_id,))
    conn.commit()
    conn.close()


def get_section_catalog(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('''
            SELECT id,department,semester,section FROM section_catalog
            WHERE department=%s ORDER BY semester, section
        '''), (department,))
    else:
        cur.execute('SELECT id,department,semester,section FROM section_catalog ORDER BY department,semester,section')
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_subject_catalog(department, semester, subject_code, subject_name):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('''
            INSERT INTO subject_catalog (department, semester, subject_code, subject_name)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
        '''), (department, str(semester).strip(), str(subject_code).strip().upper(), str(subject_name).strip()))
        conn.commit()
        return True
    finally:
        conn.close()


def remove_subject_catalog(subject_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('DELETE FROM subject_catalog WHERE id=%s'), (subject_id,))
    conn.commit()
    conn.close()


def get_subject_catalog(department=None, semester=None):
    conn = get_db()
    cur = conn.cursor()
    query = 'SELECT id,department,semester,subject_code,subject_name FROM subject_catalog WHERE 1=1'
    params = []
    if department:
        query += _fix(' AND department=%s'); params.append(department)
    if semester:
        query += _fix(' AND semester=%s'); params.append(str(semester))
    query += ' ORDER BY semester, subject_code'
    cur.execute(_fix(query), params)
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# NOTES FUNCTIONS
# ---------------------------------------------------------------------------

def create_note(teacher_id, title, subject, department, file_path, file_name):
    conn = get_db()
    cur = conn.cursor()
    new_id = _execute_returning(cur, '''
        INSERT INTO notes (teacher_id, title, subject, department, file_path, file_name)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    ''', (teacher_id, title, subject, department, file_path, file_name))
    conn.commit()
    conn.close()
    return new_id


def get_all_notes(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('SELECT * FROM notes WHERE department=%s ORDER BY created_at DESC'), (department,))
    else:
        cur.execute('SELECT * FROM notes ORDER BY created_at DESC')
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_notes_by_teacher(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('SELECT * FROM notes WHERE teacher_id=%s ORDER BY created_at DESC'), (teacher_id,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# QUESTION BANK FUNCTIONS
# ---------------------------------------------------------------------------

def create_question_bank(teacher_id, title, subject, department, file_path, file_name):
    conn = get_db()
    cur = conn.cursor()
    new_id = _execute_returning(cur, '''
        INSERT INTO question_bank (teacher_id, title, subject, department, file_path, file_name)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    ''', (teacher_id, title, subject, department, file_path, file_name))
    conn.commit()
    conn.close()
    return new_id


def get_all_question_banks(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('SELECT * FROM question_bank WHERE department=%s ORDER BY created_at DESC'), (department,))
    else:
        cur.execute('SELECT * FROM question_bank ORDER BY created_at DESC')
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_question_banks_by_teacher(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('SELECT * FROM question_bank WHERE teacher_id=%s ORDER BY created_at DESC'), (teacher_id,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_question_banks_by_ids(qb_ids):
    if not qb_ids:
        return []
    conn = get_db()
    cur = conn.cursor()
    if _USE_PG:
        cur.execute('SELECT * FROM question_bank WHERE id = ANY(%s) ORDER BY id', (list(qb_ids),))
    else:
        placeholders = ','.join('?' * len(qb_ids))
        cur.execute(f'SELECT * FROM question_bank WHERE id IN ({placeholders}) ORDER BY id', list(qb_ids))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# TIMETABLE FUNCTIONS
# ---------------------------------------------------------------------------

def create_timetable(department, semester, section, title, file_path, file_name, details=None):
    conn = get_db()
    cur = conn.cursor()
    new_id = _execute_returning(cur, '''
        INSERT INTO timetables (department, semester, section, title, file_path, file_name, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (department, semester, section, title, file_path, file_name, details))
    conn.commit()
    conn.close()
    return new_id


def update_timetable_details(department, semester, section, details):
    conn = get_db()
    cur = conn.cursor()
    if section:
        cur.execute(_fix('UPDATE timetables SET details=%s WHERE department=%s AND semester=%s AND section=%s'),
                    (details, department, semester, section))
    else:
        cur.execute(_fix('UPDATE timetables SET details=%s WHERE department=%s AND semester=%s'),
                    (details, department, semester))
    conn.commit()
    conn.close()


def get_timetables(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('SELECT * FROM timetables WHERE department=%s ORDER BY created_at DESC'), (department,))
    else:
        cur.execute('SELECT * FROM timetables ORDER BY created_at DESC')
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_timetable_entry(department, semester, section, day, time_slot, subject, teacher_name=None, room=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('''
        INSERT INTO timetable_entries
            (department, semester, section, day, time_slot, subject, teacher_name, room)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    '''), (department, semester, section, day, time_slot, subject, teacher_name, room))
    conn.commit()
    conn.close()


def clear_timetable_entries(department, semester, section=None):
    conn = get_db()
    cur = conn.cursor()
    if section:
        cur.execute(_fix('DELETE FROM timetable_entries WHERE department=%s AND semester=%s AND section=%s'),
                    (department, semester, section))
    else:
        cur.execute(_fix('DELETE FROM timetable_entries WHERE department=%s AND semester=%s'),
                    (department, semester))
    conn.commit()
    conn.close()


def get_timetable_entries(department, semester, section=None):
    conn = get_db()
    cur = conn.cursor()
    day_order = ("CASE day WHEN 'Mon' THEN 1 WHEN 'Tue' THEN 2 WHEN 'Wed' THEN 3 "
                 "WHEN 'Thu' THEN 4 WHEN 'Fri' THEN 5 WHEN 'Sat' THEN 6 ELSE 7 END")
    if section:
        cur.execute(_fix(f'''
            SELECT * FROM timetable_entries
            WHERE department=%s AND semester=%s AND section=%s
            ORDER BY {day_order}, id
        '''), (department, semester, section))
    else:
        cur.execute(_fix(f'''
            SELECT * FROM timetable_entries
            WHERE department=%s AND semester=%s
            ORDER BY {day_order}, id
        '''), (department, semester))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_teacher_timetable_slots(teacher_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('''
        SELECT * FROM teacher_timetable_slots
        WHERE teacher_id=%s
        ORDER BY
            CASE day
                WHEN 'Mon' THEN 1 WHEN 'Tue' THEN 2 WHEN 'Wed' THEN 3
                WHEN 'Thu' THEN 4 WHEN 'Fri' THEN 5 WHEN 'Sat' THEN 6
                WHEN 'Sun' THEN 7 ELSE 8 END,
            slot_code
    '''), (teacher_id,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def replace_teacher_timetable_slots(teacher_id, slots):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('DELETE FROM teacher_timetable_slots WHERE teacher_id=%s'), (teacher_id,))
        for slot in slots or []:
            cur.execute(_fix('''
                INSERT INTO teacher_timetable_slots
                    (teacher_id, day, slot_code, slot_label, status, subject, notes, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            '''), (
                teacher_id,
                slot.get('day'),
                slot.get('slot_code'),
                slot.get('slot_label'),
                slot.get('status') or 'leisure',
                slot.get('subject'),
                slot.get('notes'),
                datetime.now().isoformat(),
            ))
        return True
    finally:
        conn.commit()
        conn.close()


def get_teacher_timetable_map(teacher_id):
    timetable_map = {}
    for row in get_teacher_timetable_slots(teacher_id):
        day = str(row.get('day') or '').strip()
        slot_code = str(row.get('slot_code') or '').strip()
        if day and slot_code:
            timetable_map.setdefault(day, {})[slot_code] = row
    return timetable_map


# ---------------------------------------------------------------------------
# EXAM DUTY FUNCTIONS
# ---------------------------------------------------------------------------

def get_exam_duty_exams(department=None, active_only=False):
    conn = get_db()
    cur = conn.cursor()
    query = 'SELECT * FROM exam_duty_exams WHERE 1=1'
    params = []
    if department:
        query += _fix(' AND (department=%s OR department IS NULL)')
        params.append(department)
    if active_only:
        query += ' AND active=1'
    query += ' ORDER BY exam_date ASC, slot ASC, id ASC'
    cur.execute(_fix(query), params)
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_exam_duty_exam(exam_id=None, department=None, exam_date=None, day=None, slot=None,
                        subject=None, branch=None, semester=None, room=None, active=1):
    conn = get_db()
    cur = conn.cursor()
    try:
        if exam_id:
            cur.execute(_fix('''
                UPDATE exam_duty_exams
                SET department=%s, exam_date=%s, day=%s, slot=%s, subject=%s,
                    branch=%s, semester=%s, room=%s, active=%s, updated_at=%s
                WHERE id=%s
            '''), (
                department, exam_date, day, slot, subject, branch, semester, room,
                1 if active else 0, datetime.now().isoformat(), exam_id
            ))
            return int(exam_id)
        new_id = _execute_returning(cur, '''
            INSERT INTO exam_duty_exams
                (department, exam_date, day, slot, subject, branch, semester, room, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        ''', (department, exam_date, day, slot, subject, branch, semester, room, 1 if active else 0))
        return new_id
    finally:
        conn.commit()
        conn.close()


def delete_exam_duty_exam(exam_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(_fix('DELETE FROM exam_duty_exams WHERE id=%s'), (exam_id,))
    conn.commit()
    conn.close()


def upsert_exam_duty_teacher_setting(teacher_id, max_duties=3, active=1, notes=None):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('''
            INSERT INTO exam_duty_teacher_settings
                (teacher_id, max_duties, active, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (teacher_id) DO UPDATE SET
                max_duties=excluded.max_duties,
                active=excluded.active,
                notes=excluded.notes,
                updated_at=excluded.updated_at
        '''), (teacher_id, int(max_duties or 3), 1 if active else 0, notes, datetime.now().isoformat(), datetime.now().isoformat()))
        return True
    finally:
        conn.commit()
        conn.close()


def get_exam_duty_teacher_settings(department=None):
    conn = get_db()
    cur = conn.cursor()
    query = '''
        SELECT u.id, u.name, u.email, u.department, u.phone, u.profile_complete,
               COALESCE(s.max_duties, 3) AS max_duties,
               COALESCE(s.active, 1) AS active,
               COALESCE(s.notes, '') AS notes
        FROM users u
        LEFT JOIN exam_duty_teacher_settings s ON s.teacher_id = u.id
        WHERE u.role IN ('teacher', 'faculty')
    '''
    params = []
    if department:
        query += _fix(' AND u.department=%s')
        params.append(department)
    query += ' ORDER BY u.name ASC'
    cur.execute(_fix(query), params)
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_exam_duty_assignments(department=None, exam_id=None):
    conn = get_db()
    cur = conn.cursor()
    query = '''
        SELECT a.id, a.exam_id, a.teacher_id, a.created_at,
               e.exam_date, e.day, e.slot, e.subject, e.branch, e.semester, e.room, e.department,
               u.name as teacher_name, u.email as teacher_email,
               COALESCE(s.max_duties, 3) AS max_duties
        FROM exam_duty_assignments a
        JOIN exam_duty_exams e ON e.id = a.exam_id
        JOIN users u ON u.id = a.teacher_id
        LEFT JOIN exam_duty_teacher_settings s ON s.teacher_id = a.teacher_id
        WHERE 1=1
    '''
    params = []
    if department:
        query += _fix(' AND (e.department=%s OR e.department IS NULL)')
        params.append(department)
    if exam_id:
        query += _fix(' AND a.exam_id=%s')
        params.append(exam_id)
    query += ' ORDER BY e.exam_date ASC, e.slot ASC, a.id ASC'
    cur.execute(_fix(query), params)
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_exam_duty_assignment(exam_id, teacher_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_fix('''
            INSERT INTO exam_duty_assignments (exam_id, teacher_id)
            VALUES (%s, %s)
            ON CONFLICT (exam_id) DO UPDATE SET
                teacher_id=excluded.teacher_id
        '''), (exam_id, teacher_id))
        return True
    finally:
        conn.commit()
        conn.close()


def clear_exam_duty_assignments(department=None):
    conn = get_db()
    cur = conn.cursor()
    if department:
        cur.execute(_fix('''
            DELETE FROM exam_duty_assignments
            WHERE exam_id IN (
                SELECT id FROM exam_duty_exams WHERE department=%s OR department IS NULL
            )
        '''), (department,))
    else:
        cur.execute('DELETE FROM exam_duty_assignments')
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# EVENTS FUNCTIONS
# ---------------------------------------------------------------------------

def create_event(title, description, event_date, event_time=None, location=None,
                 department=None, semester=None, event_type='event'):
    conn = get_db()
    cur = conn.cursor()
    new_id = _execute_returning(cur, '''
        INSERT INTO events (title, description, event_date, event_time, location,
                            department, semester, type)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (title, description, event_date, event_time, location, department,
          str(semester) if semester is not None else None, event_type))
    conn.commit()
    conn.close()
    return new_id


def clear_calendar_events(department=None, semester=None):
    conn = get_db()
    cur = conn.cursor()
    if department and semester is not None:
        cur.execute(_fix('''
            DELETE FROM events
            WHERE (department=%s OR department IS NULL)
              AND (semester=%s OR semester IS NULL)
              AND type != 'manual'
        '''), (department, str(semester)))
    elif department:
        cur.execute(_fix("DELETE FROM events WHERE department=%s AND type != 'manual'"), (department,))
    else:
        cur.execute('DELETE FROM events')
    conn.commit()
    conn.close()


def get_upcoming_events(department=None, semester=None):
    conn = get_db()
    cur = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    if department and semester is not None:
        cur.execute(_fix('''
            SELECT * FROM events
            WHERE event_date >= %s
              AND (department=%s OR department IS NULL)
              AND (semester=%s OR semester IS NULL)
            ORDER BY event_date ASC
        '''), (today, department, str(semester)))
    elif department:
        cur.execute(_fix('''
            SELECT * FROM events
            WHERE event_date >= %s AND (department=%s OR department IS NULL)
            ORDER BY event_date ASC
        '''), (today, department))
    else:
        cur.execute(_fix('SELECT * FROM events WHERE event_date >= %s ORDER BY event_date ASC'), (today,))
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_all_events(department=None, semester=None):
    conn = get_db()
    cur = conn.cursor()
    if department and semester is not None:
        cur.execute(_fix('''
            SELECT * FROM events
            WHERE (department=%s OR department IS NULL)
              AND (semester=%s OR semester IS NULL)
            ORDER BY event_date ASC
        '''), (department, str(semester)))
    elif department:
        cur.execute(_fix('''
            SELECT * FROM events WHERE department=%s OR department IS NULL
            ORDER BY event_date ASC
        '''), (department,))
    else:
        cur.execute('SELECT * FROM events ORDER BY event_date ASC')
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# STATS FUNCTIONS
# ---------------------------------------------------------------------------

def get_teacher_stats(teacher_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(_fix('SELECT COUNT(*) as count FROM papers WHERE teacher_id=%s'), (teacher_id,))
    papers_count = _row(cur.fetchone())['count']

    cur.execute(_fix("SELECT COUNT(*) as count FROM papers WHERE teacher_id=%s AND status='approved'"), (teacher_id,))
    approved_count = _row(cur.fetchone())['count']

    cur.execute(_fix("SELECT COUNT(*) as count FROM papers WHERE teacher_id=%s AND status='pending'"), (teacher_id,))
    pending_count = _row(cur.fetchone())['count']

    cur.execute(_fix('SELECT COUNT(*) as count FROM notes WHERE teacher_id=%s'), (teacher_id,))
    notes_count = _row(cur.fetchone())['count']

    conn.close()
    return {
        'papers_created': papers_count,
        'approved': approved_count,
        'pending': pending_count,
        'notes': notes_count,
    }


def get_hod_stats(department=None):
    conn = get_db()
    cur = conn.cursor()

    if department:
        cur.execute(_fix("SELECT COUNT(*) as count FROM papers WHERE status='pending' AND department=%s"), (department,))
    else:
        cur.execute("SELECT COUNT(*) as count FROM papers WHERE status='pending'")
    pending = _row(cur.fetchone())['count']

    if department:
        cur.execute(_fix("SELECT COUNT(*) as count FROM papers WHERE status='approved' AND department=%s"), (department,))
    else:
        cur.execute("SELECT COUNT(*) as count FROM papers WHERE status='approved'")
    approved = _row(cur.fetchone())['count']

    if department:
        cur.execute(_fix("SELECT COUNT(*) as count FROM users WHERE role='teacher' AND department=%s"), (department,))
    else:
        cur.execute("SELECT COUNT(*) as count FROM users WHERE role='teacher'")
    teachers = _row(cur.fetchone())['count']

    if department:
        cur.execute(_fix('''
            SELECT COUNT(*) as count FROM users
            WHERE role IN ('teacher','faculty') AND department=%s
              AND profile_complete=1 AND approved_by_hod=0
        '''), (department,))
    else:
        cur.execute('''
            SELECT COUNT(*) as count FROM users
            WHERE role IN ('teacher','faculty') AND profile_complete=1 AND approved_by_hod=0
        ''')
    pending_teachers = _row(cur.fetchone())['count']

    conn.close()
    return {
        'pending_approvals': pending,
        'approved_papers': approved,
        'teachers': teachers,
        'pending_teachers': pending_teachers,
    }
