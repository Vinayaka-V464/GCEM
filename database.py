# ==============================================================================
# FILE: database.py - PostgreSQL Database for Paper Generator (Neon)
# Migrated from SQLite: ? → %s, AUTOINCREMENT → SERIAL, lastrowid → RETURNING
# ==============================================================================

import os
import psycopg2
import psycopg2.extras
from datetime import datetime
import json

DATABASE_URL = os.environ.get('DATABASE_URL', '')


def get_db():
    """Get a Postgres connection with RealDictCursor (rows as dicts)."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    """Initialize database with all tables (idempotent)."""
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
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
    ''')

    # Papers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id SERIAL PRIMARY KEY,
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
    ''')

    # Notes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            department TEXT,
            file_path TEXT NOT NULL,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # Question Bank table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS question_bank (
            id SERIAL PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            department TEXT,
            file_path TEXT NOT NULL,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # Timetables table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timetables (
            id SERIAL PRIMARY KEY,
            department TEXT,
            semester TEXT,
            section TEXT,
            title TEXT,
            file_path TEXT NOT NULL,
            file_name TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Teacher subjects table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_subjects (
            id SERIAL PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            subject_code TEXT,
            subject_name TEXT,
            semester TEXT,
            department TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # Teacher sections table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_sections (
            id SERIAL PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            semester TEXT,
            section TEXT,
            department TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(teacher_id, semester, section),
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # Section catalog table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS section_catalog (
            id SERIAL PRIMARY KEY,
            department TEXT NOT NULL,
            semester TEXT NOT NULL,
            section TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(department, semester, section)
        )
    ''')

    # Subject catalog table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subject_catalog (
            id SERIAL PRIMARY KEY,
            department TEXT NOT NULL,
            semester TEXT NOT NULL,
            subject_code TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(department, semester, subject_code)
        )
    ''')

    # Events table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
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
    ''')

    # Timetable entries table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timetable_entries (
            id SERIAL PRIMARY KEY,
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
    ''')

    # Add any missing columns safely (Postgres 9.6+ supports ADD COLUMN IF NOT EXISTS)
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
    ]
    for stmt in safe_alters:
        cursor.execute(stmt)

    conn.commit()
    conn.close()
    print("Database initialized successfully!")


# ===================== USER FUNCTIONS =====================

def create_user(uid, email, name, role, department=None, photo_url=None, email_verified=False, phone=None, semester=None, section=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        approved_by_hod = 1 if role in ['hod', 'student'] else 0
        profile_complete = 1 if role in ['hod', 'student'] else 0
        cursor.execute('''
            INSERT INTO users (id, email, name, role, department, photo_url, email_verified, approved_by_hod, profile_complete, phone, semester, section)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, role=EXCLUDED.role, department=EXCLUDED.department,
                photo_url=EXCLUDED.photo_url, email_verified=EXCLUDED.email_verified,
                phone=COALESCE(EXCLUDED.phone, users.phone),
                semester=COALESCE(EXCLUDED.semester, users.semester),
                section=COALESCE(EXCLUDED.section, users.section)
        ''', (
            uid, email, name, role, department, photo_url,
            1 if email_verified else 0, approved_by_hod, profile_complete,
            phone, semester, section
        ))
        conn.commit()
        return True
    finally:
        conn.close()


def get_user(uid):
    """Get user by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = %s', (uid,))
    user = cursor.fetchone()
    conn.close()
    if user:
        user_dict = dict(user)
        if user_dict.get('role') in ['teacher', 'faculty']:
            user_dict['subjects'] = get_teacher_subjects(uid)
            user_dict['sections'] = get_teacher_sections(uid)
        return user_dict
    return None


def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
    user = cursor.fetchone()
    conn.close()
    if user:
        user_dict = dict(user)
        if user_dict.get('role') in ['teacher', 'faculty']:
            user_dict['subjects'] = get_teacher_subjects(user_dict.get('id'))
            user_dict['sections'] = get_teacher_sections(user_dict.get('id'))
        return user_dict
    return None


def update_user_signature(uid, signature_path):
    """Update user's signature path."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET signature_path = %s WHERE id = %s', (signature_path, uid))
    conn.commit()
    conn.close()


def update_principal_signature(uid, signature_path):
    """Update principal signature path for a HOD user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET principal_signature_path = %s WHERE id = %s', (signature_path, uid))
    conn.commit()
    conn.close()


def update_teacher_profile(uid, phone=None, profile_complete=False, semester=None, section=None):
    """Update teacher profile data."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE users SET phone = %s, profile_complete = %s, semester = COALESCE(%s, semester), section = COALESCE(%s, section) WHERE id = %s',
        (phone, 1 if profile_complete else 0, semester, section, uid)
    )
    conn.commit()
    conn.close()


def set_teacher_approval(uid, approved):
    """Approve or revoke teacher access."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET approved_by_hod = %s WHERE id = %s', (1 if approved else 0, uid))
    conn.commit()
    conn.close()


def add_teacher_subject(teacher_id, subject_code, subject_name, semester, department):
    """Add subject/semester assignment for a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO teacher_subjects (teacher_id, subject_code, subject_name, semester, department)
        VALUES (%s, %s, %s, %s, %s)
    ''', (teacher_id, subject_code, subject_name, semester, department))
    conn.commit()
    conn.close()


def remove_teacher_subject(subject_id, teacher_id=None):
    """Remove subject assignment by id (optionally constrain by teacher)."""
    conn = get_db()
    cursor = conn.cursor()
    if teacher_id:
        cursor.execute('DELETE FROM teacher_subjects WHERE id = %s AND teacher_id = %s', (subject_id, teacher_id))
    else:
        cursor.execute('DELETE FROM teacher_subjects WHERE id = %s', (subject_id,))
    conn.commit()
    conn.close()


def clear_teacher_subjects(teacher_id):
    """Remove all subject assignments for a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM teacher_subjects WHERE teacher_id = %s', (teacher_id,))
    conn.commit()
    conn.close()


def get_teacher_subjects(teacher_id):
    """Get subject assignments for a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, subject_code, subject_name, semester, department
        FROM teacher_subjects
        WHERE teacher_id = %s
        ORDER BY semester, subject_code
    ''', (teacher_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_teacher_section(teacher_id, semester, section, department):
    """Add section assignment for a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO teacher_sections (teacher_id, semester, section, department)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (teacher_id, semester, section) DO NOTHING
        ''', (teacher_id, str(semester).strip(), str(section).strip().upper(), department))
        conn.commit()
        return True
    finally:
        conn.close()


def remove_teacher_section(section_id, teacher_id=None):
    """Remove teacher section assignment by id."""
    conn = get_db()
    cursor = conn.cursor()
    if teacher_id:
        cursor.execute('DELETE FROM teacher_sections WHERE id = %s AND teacher_id = %s', (section_id, teacher_id))
    else:
        cursor.execute('DELETE FROM teacher_sections WHERE id = %s', (section_id,))
    conn.commit()
    conn.close()


def clear_teacher_sections(teacher_id):
    """Remove all section assignments for a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM teacher_sections WHERE teacher_id = %s', (teacher_id,))
    conn.commit()
    conn.close()


def get_teacher_sections(teacher_id):
    """Get section assignments for a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, semester, section, department
        FROM teacher_sections
        WHERE teacher_id = %s
        ORDER BY CAST(semester AS INTEGER), section
    ''', (teacher_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def replace_teacher_assignments(from_teacher_id, to_teacher_id):
    """Move subject and section assignments from one teacher to another."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT subject_code, subject_name, semester, department FROM teacher_subjects WHERE teacher_id = %s', (from_teacher_id,))
        subjects = cursor.fetchall()
        for s in subjects:
            cursor.execute('''
                INSERT INTO teacher_subjects (teacher_id, subject_code, subject_name, semester, department)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            ''', (to_teacher_id, s['subject_code'], s['subject_name'], s['semester'], s['department']))

        cursor.execute('SELECT semester, section, department FROM teacher_sections WHERE teacher_id = %s', (from_teacher_id,))
        sections = cursor.fetchall()
        for s in sections:
            cursor.execute('''
                INSERT INTO teacher_sections (teacher_id, semester, section, department)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (teacher_id, semester, section) DO NOTHING
            ''', (to_teacher_id, s['semester'], s['section'], s['department']))

        cursor.execute('DELETE FROM teacher_subjects WHERE teacher_id = %s', (from_teacher_id,))
        cursor.execute('DELETE FROM teacher_sections WHERE teacher_id = %s', (from_teacher_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ===================== PAPER FUNCTIONS =====================

def create_paper(teacher_id, title, course_code, course_name, department, paper_data,
                 pdf_path=None, teacher_signature=None, status='draft'):
    """Create a new paper."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO papers (teacher_id, title, course_code, course_name, department,
                           paper_data, pdf_path, teacher_signature, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (teacher_id, title, course_code, course_name, department,
          json.dumps(paper_data), pdf_path, teacher_signature, status))
    paper_id = cursor.fetchone()['id']
    conn.commit()
    conn.close()
    return paper_id


def get_paper(paper_id):
    """Get paper by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM papers WHERE id = %s', (paper_id,))
    paper = cursor.fetchone()
    conn.close()
    if paper:
        paper_dict = dict(paper)
        paper_dict['paper_data'] = json.loads(paper_dict['paper_data']) if paper_dict['paper_data'] else {}
        return paper_dict
    return None


def get_papers_by_teacher(teacher_id):
    """Get all papers by a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM papers WHERE teacher_id = %s ORDER BY created_at DESC', (teacher_id,))
    papers = cursor.fetchall()
    conn.close()
    return [dict(p) for p in papers]


def get_pending_papers(department=None):
    """Get all papers pending HOD approval."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute('''
            SELECT p.*, u.name as teacher_name
            FROM papers p JOIN users u ON p.teacher_id = u.id
            WHERE p.status = 'pending' AND p.department = %s
            ORDER BY p.submitted_at DESC
        ''', (department,))
    else:
        cursor.execute('''
            SELECT p.*, u.name as teacher_name
            FROM papers p JOIN users u ON p.teacher_id = u.id
            WHERE p.status = 'pending'
            ORDER BY p.submitted_at DESC
        ''')
    papers = cursor.fetchall()
    conn.close()
    return [dict(p) for p in papers]


def submit_paper(paper_id):
    """Submit paper for HOD review."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE papers SET status = 'pending', submitted_at = %s
        WHERE id = %s
    ''', (datetime.now(), paper_id))
    conn.commit()
    conn.close()


def approve_paper(paper_id, hod_signature, principal_signature):
    """Approve paper with HOD and Principal signatures."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE papers SET status = 'approved', hod_signature = %s, principal_signature = %s, approved_at = %s
        WHERE id = %s
    ''', (hod_signature, principal_signature, datetime.now(), paper_id))
    conn.commit()
    conn.close()


def reject_paper(paper_id, comments):
    """Reject paper with comments."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE papers SET status = 'rejected', rejection_comments = %s
        WHERE id = %s
    ''', (comments, paper_id))
    conn.commit()
    conn.close()


def get_all_papers_for_hod(department=None, teacher_id=None, course_code=None, status=None):
    """Get all papers for HOD with optional filters."""
    conn = get_db()
    cursor = conn.cursor()
    query = '''
        SELECT p.*, u.name as teacher_name
        FROM papers p
        JOIN users u ON p.teacher_id = u.id
        WHERE 1=1
    '''
    params = []
    if department:
        query += ' AND p.department = %s'
        params.append(department)
    if teacher_id:
        query += ' AND p.teacher_id = %s'
        params.append(teacher_id)
    if course_code:
        query += ' AND p.course_code LIKE %s'
        params.append(f'%{course_code}%')
    if status:
        query += ' AND p.status = %s'
        params.append(status)
    query += ' ORDER BY p.created_at DESC'
    cursor.execute(query, params)
    papers = cursor.fetchall()
    conn.close()
    return [dict(p) for p in papers]


def get_all_teachers(department=None):
    """Get all teachers, optionally filtered by department."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute("SELECT id, name, email, phone, semester, section, approved_by_hod, profile_complete, email_verified FROM users WHERE role IN ('teacher', 'faculty') AND department = %s", (department,))
    else:
        cursor.execute("SELECT id, name, email, phone, semester, section, approved_by_hod, profile_complete, email_verified FROM users WHERE role IN ('teacher', 'faculty')")
    teachers = cursor.fetchall()
    conn.close()
    return [dict(t) for t in teachers]


def get_pending_teachers(department=None):
    """Get teachers pending HOD approval."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute('''
            SELECT id, name, email, phone, department
            FROM users
            WHERE role IN ('teacher','faculty') AND department = %s AND profile_complete = 1 AND approved_by_hod = 0
            ORDER BY created_at DESC
        ''', (department,))
    else:
        cursor.execute('''
            SELECT id, name, email, phone, department
            FROM users
            WHERE role IN ('teacher','faculty') AND profile_complete = 1 AND approved_by_hod = 0
            ORDER BY created_at DESC
        ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===================== HOD CATALOG FUNCTIONS =====================

def add_section_catalog(department, semester, section):
    """Add a semester-section entry to HOD catalog."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO section_catalog (department, semester, section) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
            (department, str(semester).strip(), str(section).strip().upper())
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_section_catalog(section_id):
    """Remove section entry by id."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM section_catalog WHERE id = %s', (section_id,))
    conn.commit()
    conn.close()


def get_section_catalog(department=None):
    """Get section catalog entries for a department."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute(
            'SELECT id, department, semester, section FROM section_catalog WHERE department = %s ORDER BY CAST(semester AS INTEGER), section',
            (department,)
        )
    else:
        cursor.execute(
            'SELECT id, department, semester, section FROM section_catalog ORDER BY department, CAST(semester AS INTEGER), section'
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_subject_catalog(department, semester, subject_code, subject_name):
    """Add a subject to department semester catalog."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO subject_catalog (department, semester, subject_code, subject_name) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING',
            (department, str(semester).strip(), str(subject_code).strip().upper(), str(subject_name).strip())
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_subject_catalog(subject_id):
    """Remove subject catalog entry by id."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM subject_catalog WHERE id = %s', (subject_id,))
    conn.commit()
    conn.close()


def get_subject_catalog(department=None, semester=None):
    """Get subject catalog entries."""
    conn = get_db()
    cursor = conn.cursor()
    query = 'SELECT id, department, semester, subject_code, subject_name FROM subject_catalog WHERE 1=1'
    params = []
    if department:
        query += ' AND department = %s'
        params.append(department)
    if semester:
        query += ' AND semester = %s'
        params.append(str(semester))
    query += ' ORDER BY CAST(semester AS INTEGER), subject_code'
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===================== NOTES FUNCTIONS =====================

def create_note(teacher_id, title, subject, department, file_path, file_name):
    """Create a new note."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO notes (teacher_id, title, subject, department, file_path, file_name)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (teacher_id, title, subject, department, file_path, file_name))
    note_id = cursor.fetchone()['id']
    conn.commit()
    conn.close()
    return note_id


def get_all_notes(department=None):
    """Get all notes, optionally filtered by department."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute('SELECT * FROM notes WHERE department = %s ORDER BY created_at DESC', (department,))
    else:
        cursor.execute('SELECT * FROM notes ORDER BY created_at DESC')
    notes = cursor.fetchall()
    conn.close()
    return [dict(n) for n in notes]


def get_notes_by_teacher(teacher_id):
    """Get all notes by a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM notes WHERE teacher_id = %s ORDER BY created_at DESC', (teacher_id,))
    notes = cursor.fetchall()
    conn.close()
    return [dict(n) for n in notes]


# ===================== QUESTION BANK FUNCTIONS =====================

def create_question_bank(teacher_id, title, subject, department, file_path, file_name):
    """Create a new question bank entry."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO question_bank (teacher_id, title, subject, department, file_path, file_name)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (teacher_id, title, subject, department, file_path, file_name))
    qb_id = cursor.fetchone()['id']
    conn.commit()
    conn.close()
    return qb_id


def get_all_question_banks(department=None):
    """Get all question banks, optionally filtered by department."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute('SELECT * FROM question_bank WHERE department = %s ORDER BY created_at DESC', (department,))
    else:
        cursor.execute('SELECT * FROM question_bank ORDER BY created_at DESC')
    qbs = cursor.fetchall()
    conn.close()
    return [dict(qb) for qb in qbs]


def get_question_banks_by_teacher(teacher_id):
    """Get all question banks by a teacher."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM question_bank WHERE teacher_id = %s ORDER BY created_at DESC', (teacher_id,))
    qbs = cursor.fetchall()
    conn.close()
    return [dict(qb) for qb in qbs]


def get_question_banks_by_ids(qb_ids):
    """Get question banks by their IDs."""
    if not qb_ids:
        return []
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM question_bank WHERE id = ANY(%s) ORDER BY id', (list(qb_ids),))
    qbs = cursor.fetchall()
    conn.close()
    return [dict(qb) for qb in qbs]


# ===================== TIMETABLE FUNCTIONS =====================

def create_timetable(department, semester, section, title, file_path, file_name, details=None):
    """Create a new timetable file entry."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO timetables (department, semester, section, title, file_path, file_name, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (department, semester, section, title, file_path, file_name, details))
    tt_id = cursor.fetchone()['id']
    conn.commit()
    conn.close()
    return tt_id


def update_timetable_details(department, semester, section, details):
    """Update details for a timetable."""
    conn = get_db()
    cursor = conn.cursor()
    if section:
        cursor.execute('''
            UPDATE timetables SET details = %s WHERE department = %s AND semester = %s AND section = %s
        ''', (details, department, semester, section))
    else:
        cursor.execute('''
            UPDATE timetables SET details = %s WHERE department = %s AND semester = %s
        ''', (details, department, semester))
    conn.commit()
    conn.close()


def get_timetables(department=None):
    """Get all timetables, optionally filtered by department."""
    conn = get_db()
    cursor = conn.cursor()
    if department:
        cursor.execute('SELECT * FROM timetables WHERE department = %s ORDER BY created_at DESC', (department,))
    else:
        cursor.execute('SELECT * FROM timetables ORDER BY created_at DESC')
    tts = cursor.fetchall()
    conn.close()
    return [dict(tt) for tt in tts]


def add_timetable_entry(department, semester, section, day, time_slot, subject, teacher_name=None, room=None):
    """Add a single timetable entry."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO timetable_entries (department, semester, section, day, time_slot, subject, teacher_name, room)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (department, semester, section, day, time_slot, subject, teacher_name, room))
    conn.commit()
    conn.close()


def clear_timetable_entries(department, semester, section=None):
    """Clear all timetable entries for a department and semester."""
    conn = get_db()
    cursor = conn.cursor()
    if section:
        cursor.execute(
            'DELETE FROM timetable_entries WHERE department = %s AND semester = %s AND section = %s',
            (department, semester, section)
        )
    else:
        cursor.execute('DELETE FROM timetable_entries WHERE department = %s AND semester = %s', (department, semester))
    conn.commit()
    conn.close()


def get_timetable_entries(department, semester, section=None):
    """Get timetable entries."""
    conn = get_db()
    cursor = conn.cursor()
    day_order = "CASE day WHEN 'Mon' THEN 1 WHEN 'Tue' THEN 2 WHEN 'Wed' THEN 3 WHEN 'Thu' THEN 4 WHEN 'Fri' THEN 5 WHEN 'Sat' THEN 6 ELSE 7 END"
    if section:
        cursor.execute(f'''
            SELECT * FROM timetable_entries
            WHERE department = %s AND semester = %s AND section = %s
            ORDER BY {day_order}, id
        ''', (department, semester, section))
    else:
        cursor.execute(f'''
            SELECT * FROM timetable_entries
            WHERE department = %s AND semester = %s
            ORDER BY {day_order}, id
        ''', (department, semester))
    entries = cursor.fetchall()
    conn.close()
    return [dict(e) for e in entries]


# ===================== EVENTS FUNCTIONS =====================

def create_event(title, description, event_date, event_time=None, location=None, department=None, semester=None, event_type='event'):
    """Create a new event."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO events (title, description, event_date, event_time, location, department, semester, type)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (title, description, event_date, event_time, location, department, str(semester) if semester is not None else None, event_type))
    event_id = cursor.fetchone()['id']
    conn.commit()
    conn.close()
    return event_id


def clear_calendar_events(department=None, semester=None):
    """Clear calendar events."""
    conn = get_db()
    cursor = conn.cursor()
    if department and semester is not None:
        cursor.execute(
            "DELETE FROM events WHERE (department = %s OR department IS NULL) AND (semester = %s OR semester IS NULL) AND type != 'manual'",
            (department, str(semester))
        )
    elif department:
        cursor.execute("DELETE FROM events WHERE department = %s AND type != 'manual'", (department,))
    else:
        cursor.execute("DELETE FROM events")
    conn.commit()
    conn.close()


def get_upcoming_events(department=None, semester=None):
    """Get upcoming events."""
    conn = get_db()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    if department and semester is not None:
        cursor.execute('''
            SELECT * FROM events
            WHERE event_date >= %s AND (department = %s OR department IS NULL)
              AND (semester = %s OR semester IS NULL)
            ORDER BY event_date ASC
        ''', (today, department, str(semester)))
    elif department:
        cursor.execute('''
            SELECT * FROM events WHERE event_date >= %s AND (department = %s OR department IS NULL)
            ORDER BY event_date ASC
        ''', (today, department))
    else:
        cursor.execute('SELECT * FROM events WHERE event_date >= %s ORDER BY event_date ASC', (today,))
    events = cursor.fetchall()
    conn.close()
    return [dict(e) for e in events]


def get_all_events(department=None, semester=None):
    """Get all events for calendar view."""
    conn = get_db()
    cursor = conn.cursor()
    if department and semester is not None:
        cursor.execute('''
            SELECT * FROM events
            WHERE (department = %s OR department IS NULL)
              AND (semester = %s OR semester IS NULL)
            ORDER BY event_date ASC
        ''', (department, str(semester)))
    elif department:
        cursor.execute('SELECT * FROM events WHERE department = %s OR department IS NULL ORDER BY event_date ASC', (department,))
    else:
        cursor.execute('SELECT * FROM events ORDER BY event_date ASC')
    events = cursor.fetchall()
    conn.close()
    return [dict(e) for e in events]


# ===================== STATS FUNCTIONS =====================

def get_teacher_stats(teacher_id):
    """Get stats for a teacher."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) as count FROM papers WHERE teacher_id = %s', (teacher_id,))
    papers_count = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM papers WHERE teacher_id = %s AND status = 'approved'", (teacher_id,))
    approved_count = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM papers WHERE teacher_id = %s AND status = 'pending'", (teacher_id,))
    pending_count = cursor.fetchone()['count']

    cursor.execute('SELECT COUNT(*) as count FROM notes WHERE teacher_id = %s', (teacher_id,))
    notes_count = cursor.fetchone()['count']

    conn.close()
    return {
        'papers_created': papers_count,
        'approved': approved_count,
        'pending': pending_count,
        'notes': notes_count
    }


def get_hod_stats(department=None):
    """Get stats for HOD dashboard."""
    conn = get_db()
    cursor = conn.cursor()

    if department:
        cursor.execute("SELECT COUNT(*) as count FROM papers WHERE status = 'pending' AND department = %s", (department,))
    else:
        cursor.execute("SELECT COUNT(*) as count FROM papers WHERE status = 'pending'")
    pending = cursor.fetchone()['count']

    if department:
        cursor.execute("SELECT COUNT(*) as count FROM papers WHERE status = 'approved' AND department = %s", (department,))
    else:
        cursor.execute("SELECT COUNT(*) as count FROM papers WHERE status = 'approved'")
    approved = cursor.fetchone()['count']

    if department:
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'teacher' AND department = %s", (department,))
    else:
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'teacher'")
    teachers = cursor.fetchone()['count']

    if department:
        cursor.execute('''
            SELECT COUNT(*) as count FROM users
            WHERE role IN ('teacher','faculty') AND department = %s AND profile_complete = 1 AND approved_by_hod = 0
        ''', (department,))
    else:
        cursor.execute('''
            SELECT COUNT(*) as count FROM users
            WHERE role IN ('teacher','faculty') AND profile_complete = 1 AND approved_by_hod = 0
        ''')
    pending_teachers = cursor.fetchone()['count']

    conn.close()
    return {
        'pending_approvals': pending,
        'approved_papers': approved,
        'teachers': teachers,
        'pending_teachers': pending_teachers
    }
