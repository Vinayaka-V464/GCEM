# ==============================================================================
# FILE: app.py - Paper Generator with Firebase Auth & SQLite Database
# ==============================================================================

import os
import base64
import random
import re
import json
import uuid
import tempfile
import fitz  # PyMuPDF
from collections import Counter
from datetime import datetime, timedelta

# Load .env file (only needed in local dev; in production set env vars directly)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on system environment variables
from functools import wraps
from flask import Flask, render_template, request, abort, jsonify, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from database import (
    init_db, create_user, get_user, get_user_by_email, update_user_signature,
    update_principal_signature, update_teacher_profile, set_teacher_approval,
    add_teacher_subject, remove_teacher_subject, clear_teacher_subjects, get_teacher_subjects,
    add_teacher_section, remove_teacher_section, clear_teacher_sections, get_teacher_sections, replace_teacher_assignments,
    get_pending_teachers,
    add_section_catalog, remove_section_catalog, get_section_catalog,
    add_subject_catalog, remove_subject_catalog, get_subject_catalog,
    create_paper, get_paper, get_papers_by_teacher, get_pending_papers,
    submit_paper, approve_paper, reject_paper, get_all_papers_for_hod, get_all_teachers,
    create_note, get_all_notes, get_notes_by_teacher, create_question_bank, get_all_question_banks, get_question_banks_by_teacher, get_question_banks_by_ids,
    get_timetables, create_timetable, add_timetable_entry, clear_timetable_entries, get_timetable_entries, update_timetable_details,
    get_upcoming_events, create_event, clear_calendar_events, get_all_events,
    get_teacher_stats, get_hod_stats
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'paper-generator-secret-key-change-in-production')

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['UPLOAD_FOLDER'] = os.path.abspath(os.environ.get('UPLOAD_ROOT', 'uploads'))
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
for folder_name in ['signatures', 'notes', 'question_banks', 'timetables']:
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], folder_name), exist_ok=True)

# Local file storage
import storage as cloud_storage

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}


# Initialize database
init_db()

# --- Firebase Config API ---

@app.route('/api/firebase-config')
def firebase_config():
    """Serve Firebase config — only to same-origin fetch() requests."""
    # Block external callers: require the X-Requested-With header
    # (set automatically by our JS fetch wrapper call; curl/browser-URL won't have it)
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return jsonify({'error': 'Forbidden'}), 403

    config = {
        'apiKey':            os.environ.get('FIREBASE_API_KEY', ''),
        'authDomain':        os.environ.get('FIREBASE_AUTH_DOMAIN', ''),
        'projectId':         os.environ.get('FIREBASE_PROJECT_ID', ''),
        'storageBucket':     os.environ.get('FIREBASE_STORAGE_BUCKET', ''),
        'messagingSenderId': os.environ.get('FIREBASE_MESSAGING_SENDER_ID', ''),
        'appId':             os.environ.get('FIREBASE_APP_ID', ''),
        'measurementId':     os.environ.get('FIREBASE_MEASUREMENT_ID', ''),
    }
    response = jsonify(config)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    return response


# --- Helper Functions ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def encode_image_to_base64(file_storage):
    """Encode a FileStorage image to a base64 data-URL (used for inline preview only)."""
    if not file_storage:
        return None
    try:
        encoded_string = base64.b64encode(file_storage.read()).decode('utf-8')
        return f"data:{file_storage.mimetype};base64,{encoded_string}"
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None

def signature_url_or_none(url):
    """Return a local uploads path as-is, or None if empty."""
    return url if url else None

def normalize_subject_code(value):
    """Normalize subject code to alphanumeric uppercase (e.g., BCS 601 -> BCS601)."""
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())

def roman_to_int(token):
    values = {'I': 1, 'V': 5, 'X': 10}
    total = 0
    prev = 0
    for ch in reversed(token):
        current = values.get(ch, 0)
        if current < prev:
            total -= current
        else:
            total += current
            prev = current
    return total if total > 0 else None

def semester_core(value):
    """
    Convert semester labels into a comparable numeric token:
    6, "Sem 6", "VI", "VI/A" -> "6"
    """
    text = str(value or '').strip().upper()
    if not text:
        return ''
    match = re.search(r'([0-9IVX]+)', text)
    if not match:
        return ''
    token = match.group(1)
    if token.isdigit():
        return str(int(token))
    converted = roman_to_int(token)
    return str(converted) if converted else ''

def extract_qb_subject_parts(subject_text):
    """Extract subject code and semester token from stored subject text."""
    text = str(subject_text or '')
    compact = re.sub(r'\s+', '', text.upper())
    code_match = re.search(r'([A-Z]{2,}\d{2,})', compact)
    subject_code = code_match.group(1) if code_match else ''
    sem_match = re.search(r'SEM(?:ESTER)?\s*[-:]?\s*([0-9IVX]+(?:/[A-Z0-9]+)?)', text, re.IGNORECASE)
    semester_token = sem_match.group(1) if sem_match else ''
    return subject_code, semester_token

def question_bank_matches_subject(qb, selected_code, selected_semester):
    """True when a question bank belongs to selected subject/semester."""
    selected_code_norm = normalize_subject_code(selected_code)
    selected_sem_core = semester_core(selected_semester)
    if not selected_code_norm:
        return False

    parsed_code, parsed_sem = extract_qb_subject_parts(qb.get('subject'))
    qb_code_norm = normalize_subject_code(parsed_code)
    qb_sem_core = semester_core(parsed_sem)

    if not qb_code_norm:
        return False
    if qb_code_norm != selected_code_norm:
        return False
    if selected_sem_core and qb_sem_core and qb_sem_core != selected_sem_core:
        return False
    return True

def _open_pdf_from_source(source):
    """
    Open a PDF for PyMuPDF.
    source must be a local file path.
    Returns (fitz.Document, tmp_path_or_None) — caller must delete tmp_path if not None.
    """
    source_path = str(source or '')
    if not os.path.isabs(source_path):
        source_path = os.path.join(app.config['UPLOAD_FOLDER'], source_path)
    return fitz.open(source_path), None

def get_file_url(path):
    """Return a local uploads URL for a stored file path."""
    if not path:
        return ""
    path_text = str(path).replace('\\', '/')
    if path_text.startswith('/paper/'):
        path_text = path_text[len('/paper/'):]
    elif path_text.startswith('paper/'):
        path_text = path_text[len('paper/'):]
    if path_text.startswith('/uploads/'):
        return path_text
    if os.path.isabs(path_text):
        try:
            relative_path = os.path.relpath(path_text, app.config['UPLOAD_FOLDER']).replace('\\', '/')
            return f"/uploads/{relative_path}"
        except ValueError:
            return ''
    return f"/uploads/{path_text.lstrip('/')}"

app.jinja_env.globals.update(get_file_url=get_file_url)


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/paper/<path:filename>')
def serve_legacy_paper_upload(filename):
    """Compatibility route for older stored paths that still point under /paper/."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


def clean_question_text(text):
    """Clean exam-paper text so only the actual question remains."""
    if not text:
        return ""

    text = str(text).strip()
    text = re.sub(r'\s+', ' ', text)

    # Remove exam metadata like "M : Marks, L : Bloom's level, C : Course outcomes"
    text = re.sub(r'\bM\s*:\s*Marks\b[^.]*?\bC\s*:\s*Course\s*outcomes\b', '', text, flags=re.I)
    text = re.sub(r'\bM\s*:\s*Marks\b', '', text, flags=re.I)
    text = re.sub(r'\bL\s*:\s*Bloom\s*["\']?s\s*level\b', '', text, flags=re.I)
    text = re.sub(r'\bC\s*:\s*Course\s*outcomes\b', '', text, flags=re.I)

    # Remove module and question number prefixes such as "M L C Module – 1 Q.1 a." or "10 L2 CO1 b."
    prefix_tokens = [
        r'^M\s+L\s+C\s*',
        r'^M\s*:\s*Marks\s*',
        r'^L\s*:\s*Bloom(?:\s*[\"\']?s)?\s*level\s*',
        r'^C\s*:\s*Course\s*outcomes\s*',
        r'^Module\b[^A-Za-z0-9]*[–-]?\s*\d+\s*',
        r'^Q(?:uestion)?\.?\s*\d+(?:\.\d+)?(?:\s*[a-z])?\s*',
        r'^[a-z]\s*[.)]\s*',
        r'^[0-9]+\s*',
        r'^[ivx]+\s*',
        r'^\d+\s+[A-Za-z0-9]+\s+[A-Za-z0-9]+\s*',
        r'^\d+\s+[A-Za-z0-9]+\s*',
        r'^[A-Za-z]\d+\s+[A-Za-z0-9]+\s*',
        r'^[A-Za-z]\d+\s*',
    ]
    while True:
        changed = False
        text = re.sub(r'^[\s,;:.:-]+', '', text)
        for pattern in prefix_tokens:
            new_text = re.sub(pattern, '', text, flags=re.I)
            if new_text != text:
                text = new_text
                changed = True
                break
        if not changed:
            break

    question_word_match = re.search(
        r'\b(?:what|why|how|describe|explain|write|state|differentiate|compare|define|list|discuss|identify|analyze|analyse|derive|sketch|draw|illustrate|name|give|show|find|solve|prove|calculate|prepare|elaborate)\b',
        text,
        flags=re.I,
    )
    if question_word_match:
        text = text[question_word_match.start():]

    # Ignore generic instructions, headers, and one-off fragments that are not questions.
    if len(text) < 12:
        return ""
    if re.match(r'^(?:Answer|Note|Time|Max|Marks|Module|Question|Semester|Department|Department of|Internet of Things|Seventh Semester|B\.E\./B\.Tech\.)', text, re.I):
        return ""
    if not question_word_match and not re.search(r'[?]$', text) and len(re.findall(r'\b\w+\b', text)) < 5:
        return ""

    # Remove any remaining numbering or bullet prefixes at the start or trailing exam labels at the end
    text = re.sub(r'^(?:\s*(?:Q(?:uestion)?\s*\d*|[0-9]+|[ivx]+|[a-z]\s*[.)])\s*)+', '', text, flags=re.I)
    split_match = re.search(r'(?<!\w)(?:\b(?:\d+\s+L\d+|\d+\s+CO\d+|\d+\s+of\s+\d+|\b(?:BCS|MCA|CSE|ECE|EEE|ME|CE|ISE|AI|DS|CS)\d{3,4}\b|Module\b[^A-Za-z0-9]*[–-]?\s*\d+|Q(?:uestion)?\.?\s*\d+(?:\.\d+)?(?:\s*[a-z])?))', text, flags=re.I)
    if split_match:
        text = text[:split_match.start()].rstrip(' .:-')
    text = re.sub(r'^[^A-Za-z0-9]+', '', text)

    trailing_punct = ''
    if re.search(r'[?.!]$', text):
        trailing_punct = text[-1]
        text = text[:-1].rstrip()

    text = re.sub(r'[^A-Za-z0-9]+$', '', text)

    text = re.sub(r'\s+', ' ', text).strip()
    if trailing_punct:
        text = text + trailing_punct
    elif text and text[-1] not in '.!?':
        text = text + '.'
    return text


def normalize_question_text(text):
    """Normalize a question so repeated questions can be matched reliably."""
    cleaned = clean_question_text(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r'[^a-z0-9]+', ' ', cleaned.lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def infer_paper_context(filename, pdf_text):
    """Infer a paper label and year from the filename and PDF text."""
    paper_name = os.path.splitext(os.path.basename(str(filename or '')))[0] if filename else ''
    year_text = ''

    if pdf_text:
        year_candidates = re.findall(r'(?:June|July|August|September|October|November|December|January|February|March|April|May|June-July|June\s*July|Dec|Jan|Feb|Mar|Apr|May)[^\n]{0,40}(?:20\d{2})', str(pdf_text), re.I)
        if year_candidates:
            year_text = year_candidates[0].strip()
        else:
            year_match = re.search(r'(20\d{2})', str(pdf_text))
            if year_match:
                year_text = year_match.group(1)

    if not year_text and paper_name:
        year_match = re.search(r'(20\d{2})', paper_name)
        if year_match:
            year_text = year_match.group(1)

    if not year_text:
        year_text = 'Unknown year'

    return {
        'paper_name': paper_name or 'Uploaded paper',
        'year': year_text,
    }


def extract_questions_from_pdf(pdf_source):
    """Extract likely question blocks from a PDF question-paper file."""
    questions = []
    _tmp_path = None

    try:
        doc, _tmp_path = _open_pdf_from_source(pdf_source)
        full_text = "\n".join(page.get_text("text") for page in doc)
        lines = [re.sub(r'\s+', ' ', ln).strip() for ln in full_text.splitlines() if re.sub(r'\s+', ' ', ln).strip()]

        def _looks_like_question(line):
            if not line:
                return False
            if len(line) < 10:
                return False
            if re.match(r'^(?:Q(?:uestion)?\s*)?[0-9]+[\.)]', line, re.I):
                return True
            if re.match(r'^[A-Za-z]\)', line):
                return True
            if re.search(r'\?$', line):
                return True
            if re.search(r'\b(?:what|why|how|describe|explain|write|state|differentiate|compare|define|list|discuss|sketch|draw|illustrate|derive|analyze|analyse)\b', line, re.I):
                return True
            return False

        current = []

        def _flush_current():
            nonlocal current
            if not current:
                return
            block = " ".join(part for part in current if part).strip()
            cleaned_block = clean_question_text(block)
            if len(cleaned_block) >= 12 and not re.fullmatch(r'[^A-Za-z0-9]+', cleaned_block):
                questions.append(cleaned_block)
            current = []

        for line in lines:
            if _looks_like_question(line):
                _flush_current()
                current = [line]
            else:
                if current:
                    current.append(line)
                elif len(line) >= 20:
                    current = [line]

        _flush_current()

    except Exception as e:
        print(f"Error extracting questions from PDF: {e}")
        return []
    finally:
        if _tmp_path:
            try:
                os.unlink(_tmp_path)
            except OSError:
                pass

    return questions


def analyze_repeated_questions(question_texts, top_n=10):
    """Return the most repeated questions with provenance details for each occurrence."""
    normalized_counts = Counter()
    display_by_key = {}
    occurrences_by_key = {}

    for entry in question_texts:
        if isinstance(entry, dict):
            question = entry.get('question')
            source = entry.get('source') or {}
        else:
            question = entry
            source = {}

        normalized = normalize_question_text(question)
        if not normalized:
            continue
        normalized_counts[normalized] += 1
        display_by_key.setdefault(normalized, question.strip())
        occurrences_by_key.setdefault(normalized, []).append({
            'question': question.strip(),
            'paper_name': source.get('paper_name') or 'Uploaded paper',
            'year': source.get('year') or 'Unknown year',
        })

    ranked = []
    for normalized, count in normalized_counts.most_common(max(1, int(top_n or 10))):
        if count < 2:
            continue
        question_text = display_by_key.get(normalized, normalized)
        if not question_text or len(question_text) < 12:
            continue
        ranked.append({
            'question': question_text,
            'count': count,
            'normalized': normalized,
            'occurrences': occurrences_by_key.get(normalized, []),
        })
    return ranked


def parse_question_bank_pdf(pdf_source):
    """Parse question bank PDF from a local path."""
    questions_pool = []
    co_descriptions = {}
    q_counter = 1
    _tmp_path = None

    try:
        doc, _tmp_path = _open_pdf_from_source(pdf_source)

        for page in doc:
            tables = page.find_tables()
            for table in tables:
                extracted = table.extract()
                if not extracted or len(extracted[0]) < 2: continue

                header = "".join(str(cell) for cell in extracted[0]).lower()
                first_col_content = "".join(str(row[0]) for row in extracted).upper()

                if "outcome" in header or "cos" in header or "CO" in first_col_content:
                    start_row = 1 if "outcome" in header or "cos" in header else 0
                    for row in extracted[start_row:]:
                        co_num_raw = str(row[0])
                        co_desc_raw = str(row[1])
                        if "CO" in co_num_raw and len(co_desc_raw) > 10:
                            co_num = "CO" + "".join(filter(str.isdigit, co_num_raw))
                            co_descriptions[co_num] = co_desc_raw.strip()

        for page in doc:
            tables = page.find_tables()
            for table in tables:
                extracted_table = table.extract()
                for row in extracted_table[1:]:
                    if len(row) >= 5 and row[0] is not None:
                        question_text = str(row[1]).replace('\n', ' ').strip()
                        marks_str = str(row[2]).strip()
                        if question_text and marks_str.isdigit():
                            questions_pool.append({
                                'id': q_counter,
                                'text': question_text,
                                'marks': int(marks_str),
                                'co': str(row[3]).strip().replace(" ",""),
                                'rbt': str(row[4]).strip()
                            })
                            q_counter += 1

        full_text = "\n".join(page.get_text("text") for page in doc)
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

        if not co_descriptions:
            co_line_re = re.compile(r'(?:Course\s*Outcome(?:s)?\s*[:\-]?\s*)?(CO\s*\d+)\s*[:\-]\s*(.+)', re.I)
            for line in lines:
                m = co_line_re.search(line)
                if m:
                    co_num = m.group(1).replace(" ", "").upper()
                    co_desc = m.group(2).strip()
                    if co_desc and len(co_desc) > 5:
                        co_descriptions[co_num] = co_desc

        if not questions_pool:
            header_idx = None
            for i, line in enumerate(lines):
                if re.fullmatch(r'Q\.?\s*No\.?', line, re.IGNORECASE):
                    header_idx = i
                    break

            if header_idx is not None:
                i = header_idx + 1
                label_set = {'question', 'marks', 'co', 'rbt', 'rbt level', 'rbt level.'}
                while i < len(lines) and lines[i].lower() in label_set:
                    i += 1

                while i < len(lines):
                    if not re.fullmatch(r'\d+', lines[i]):
                        i += 1
                        continue
                    i += 1
                    qtext_parts = []
                    while i < len(lines):
                        if re.fullmatch(r'\d+', lines[i]):
                            if i + 2 < len(lines) and re.fullmatch(r'CO\s*\d+', lines[i + 1], re.IGNORECASE):
                                rbt_candidate = lines[i + 2]
                                if re.search(r'\bL\s*[1-6]\b', rbt_candidate, re.IGNORECASE) or re.search(r'(remember|understand|apply|analyze|analyse|evaluate|create)', rbt_candidate, re.IGNORECASE):
                                    question_text = " ".join(qtext_parts).strip()
                                    if question_text:
                                        questions_pool.append({
                                            'id': q_counter,
                                            'text': question_text,
                                            'marks': int(lines[i]),
                                            'co': lines[i + 1].replace(' ', '').upper(),
                                            'rbt': rbt_candidate.strip()
                                        })
                                        q_counter += 1
                                    i += 3
                                    break
                        qtext_parts.append(lines[i])
                        i += 1
                    else:
                        break

        if not co_descriptions:
            co_pattern = re.compile(r"^(CO\s*\d+)\s*(.*)", re.MULTILINE)
            for match in co_pattern.finditer(full_text):
                co_num = match.group(1).replace(" ", "")
                co_desc = match.group(2).strip()
                if co_desc and len(co_desc) > 10:
                    co_descriptions[co_num] = co_desc

    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return [], {}
    finally:
        if _tmp_path:
            try:
                os.unlink(_tmp_path)
            except OSError:
                pass

    return questions_pool, co_descriptions

# --- Decorators ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        if (session.get('user') or {}).get('role') not in ['teacher', 'faculty']:
            flash('Access denied. Teachers only.', 'error')
            return redirect(url_for('dashboard'))
        # Refresh user from DB to reflect approvals/subjects
        user = get_user((session.get('user') or {}).get('id'))
        if user:
            session['user'] = user
        else:
            session.clear()
            return redirect(url_for('login'))
        # Gate access until email verified + profile complete + HOD approved
        if not (user or {}).get('email_verified'):
            return redirect(url_for('teacher_onboarding'))
        if not (user or {}).get('profile_complete'):
            return redirect(url_for('teacher_onboarding'))
        if not (user or {}).get('approved_by_hod'):
            return redirect(url_for('teacher_onboarding'))
        return f(*args, **kwargs)
    return decorated_function

def academic_staff_required(f):
    """Allow teacher/faculty and HOD for academic content creation routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        role = ((session.get('user') or {}).get('role') or '').strip().lower()
        if role not in ['teacher', 'faculty', 'hod']:
            flash('Access denied. Academic staff only.', 'error')
            return redirect(url_for('dashboard'))

        user = get_user((session.get('user') or {}).get('id'))
        if user:
            session['user'] = user
        else:
            session.clear()
            return redirect(url_for('login'))

        if role in ['teacher', 'faculty']:
            if not (user or {}).get('email_verified'):
                return redirect(url_for('teacher_onboarding'))
            if not (user or {}).get('profile_complete'):
                return redirect(url_for('teacher_onboarding'))
            if not (user or {}).get('approved_by_hod'):
                return redirect(url_for('teacher_onboarding'))
        return f(*args, **kwargs)
    return decorated_function

def hod_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        if (session.get('user') or {}).get('role') != 'hod':
            flash('Access denied. HOD only.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# --- Authentication Routes ---

@app.route('/login')
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/signup')
def signup():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    department = 'Computer Science'
    section_catalog = get_section_catalog(department)
    subject_catalog = get_subject_catalog(department)
    return render_template(
        'signup.html',
        section_catalog=section_catalog,
        subject_catalog=subject_catalog
    )

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.json or {}
    uid = data.get('uid')
    email = data.get('email', '')
    name = data.get('name', '')
    role = data.get('role', 'student')
    department = data.get('department', 'Computer Science')
    photo_url = data.get('photoURL', '')
    email_verified = data.get('emailVerified', False)
    phone = (data.get('phone') or '').strip()
    semester = (str(data.get('semester') or '')).strip()
    section = (str(data.get('section') or '')).strip().upper()
    subject_ids = data.get('subject_ids') or []
    section_ids = data.get('section_ids') or []
    selected_catalog_items = []
    selected_section_items = []
    
    if not uid:
        return jsonify({'success': False, 'message': 'User ID required'}), 400

    if role == 'student':
        if not phone or not semester or not section:
            return jsonify({'success': False, 'message': 'Phone, semester, and section are required for students.'}), 400

        valid_sections = {
            (str(s.get('semester')), str(s.get('section')).upper())
            for s in get_section_catalog(department)
        }
        if not valid_sections:
            return jsonify({'success': False, 'message': 'No semester/section options configured by HOD yet.'}), 400
        if (semester, section) not in valid_sections:
            return jsonify({'success': False, 'message': 'Invalid semester/section selection.'}), 400

    if role in ['teacher', 'faculty']:
        if not phone:
            return jsonify({'success': False, 'message': 'Phone number is required for teachers.'}), 400
        if not subject_ids:
            return jsonify({'success': False, 'message': 'Select at least one subject.'}), 400
        if not section_ids:
            return jsonify({'success': False, 'message': 'Select at least one section.'}), 400
        raw_catalog = get_subject_catalog(department)
        catalog_by_id = {int(s.get('id')): s for s in raw_catalog}
        for sid in subject_ids:
            try:
                sid_int = int(sid)
            except Exception:
                continue
            if sid_int in catalog_by_id:
                selected_catalog_items.append(catalog_by_id[sid_int])
        if not selected_catalog_items:
            return jsonify({'success': False, 'message': 'Invalid subject selection.'}), 400

        section_catalog = get_section_catalog(department) or []
        section_by_id = {int(s.get('id')): s for s in section_catalog}
        for sec_id in section_ids:
            try:
                sec_id_int = int(sec_id)
            except Exception:
                continue
            if sec_id_int in section_by_id:
                selected_section_items.append(section_by_id[sec_id_int])
        if not selected_section_items:
            return jsonify({'success': False, 'message': 'Invalid section selection.'}), 400
    
    # Create user in database
    teacher_primary_section = None
    if role in ['teacher', 'faculty'] and selected_section_items:
        teacher_primary_section = (selected_section_items[0].get('section') or '').strip().upper() or None
    create_user(
        uid, email, name, role, department, photo_url, email_verified,
        phone=phone if phone else None,
        semester=semester if semester else None,
        section=(section if section else teacher_primary_section)
    )
    effective_user = get_user(uid) or get_user_by_email(email) or {}
    effective_user_id = effective_user.get('id') or uid

    if role in ['teacher', 'faculty']:
        clear_teacher_subjects(effective_user_id)
        clear_teacher_sections(effective_user_id)
        for s in selected_catalog_items:
            add_teacher_subject(
                effective_user_id,
                s.get('subject_code'),
                s.get('subject_name'),
                s.get('semester'),
                department
            )
        for sec in selected_section_items:
            add_teacher_section(
                effective_user_id,
                sec.get('semester'),
                sec.get('section'),
                department
            )
        primary_sem = (selected_section_items[0].get('semester') if selected_section_items else None)
        primary_sec = (selected_section_items[0].get('section') if selected_section_items else None)
        update_teacher_profile(effective_user_id, phone=phone, profile_complete=True, semester=primary_sem, section=primary_sec)
    
    # Get user from database
    user = get_user(effective_user_id)
    
    # Set session
    session['user'] = user
    
    # Determine redirect based on role
    if role == 'hod':
        redirect_url = '/hod/dashboard'
    elif role in ['teacher', 'faculty']:
        redirect_url = '/teacher/onboarding'
    else:
        redirect_url = '/student/dashboard'
    
    return jsonify({
        'success': True,
        'redirect': redirect_url,
        'user': user
    })

@app.route('/api/auth/verify', methods=['POST'])
def api_verify():
    data = request.json or {}
    id_token = data.get('idToken')
    uid = data.get('uid')
    email = data.get('email')
    
    print(f"[VERIFY] Received uid={uid}, email={email}")
    
    # Check if user exists in database by UID first, then email
    user = None
    if uid:
        user = get_user(uid)
        print(f"[VERIFY] Lookup by UID: {user is not None}")
    if not user and email:
        user = get_user_by_email(email)
        print(f"[VERIFY] Lookup by email: {user is not None}")
    
    if user:
        print(f"[VERIFY] User found: {user.get('name')}, role={user.get('role')}")
        # User exists, set session and return redirect
        session['user'] = user
        role = user.get('role', 'student')
        
        if role == 'hod':
            redirect_url = '/hod/dashboard'
        elif role in ['teacher', 'faculty']:
            redirect_url = '/teacher/onboarding'
        else:
            redirect_url = '/student/dashboard'
        
        return jsonify({
            'exists': True,
            'success': True,
            'redirect': redirect_url,
            'user': user
        })
    
    print(f"[VERIFY] User NOT found - will redirect to role selection")
    # User doesn't exist, needs to register
    return jsonify({'exists': False, 'success': True})

# --- Dashboard Routes ---

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = (session.get('user') or {})
    role = user.get('role', 'student')
    
    if role == 'hod':
        return redirect(url_for('hod_dashboard'))
    elif role in ['teacher', 'faculty']:
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('student_dashboard'))

# --- Student Dashboard ---

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    user = (session.get('user') or {})
    
    # If user is empty, redirect to login
    if not user or not user.get('id'):
        session.clear()
        flash('Please log in again.', 'error')
        return redirect(url_for('login'))
    
    # Get data for student - show all if no department
    department = user.get('department')
    student_semester = user.get('semester')
    notes = get_all_notes(department) or []
    question_banks = get_all_question_banks(department) or []
    if student_semester:
        sem_core = semester_core(student_semester)
        if sem_core:
            notes = [n for n in notes if semester_core(n.get('subject')) == sem_core]
            question_banks = [qb for qb in question_banks if semester_core(qb.get('subject')) == sem_core]
    timetables = get_timetables(department) or []
    events = get_upcoming_events(department, student_semester) or []
    
    return render_template('student_dashboard.html', 
                         user=user, 
                         notes=notes,
                         question_banks=question_banks,
                         timetables=timetables,
                         events=events,
                         current_user=user,
                         show_navbar=True)

# --- Teacher Onboarding ---

@app.route('/teacher/onboarding')
@login_required
def teacher_onboarding():
    user = (session.get('user') or {})
    if (user.get('role') or '') not in ['teacher', 'faculty']:
        return redirect(url_for('dashboard'))
    # Refresh user and subjects
    user = get_user(user.get('id')) or user
    session['user'] = user
    subjects = user.get('subjects') or []
    sections = user.get('sections') or []
    subject_catalog = get_subject_catalog(user.get('department')) or []
    section_catalog = get_section_catalog(user.get('department')) or []
    return render_template('teacher_onboarding.html',
                         user=user,
                         subjects=subjects,
                         sections=sections,
                         subject_catalog=subject_catalog,
                         section_catalog=section_catalog,
                         current_user=user,
                         show_navbar=False)

# --- Teacher Dashboard ---

# --- Digital Campus Route ---

@app.route('/digital-campus')
@login_required
def digital_campus():
    user = (session.get('user') or {})
    
    if not user or not user.get('id'):
        session.clear()
        flash('Please log in again.', 'error')
        return redirect(url_for('login'))

    allowed_semesters = None
    allowed_sections_map = {}
    if user.get('role') in ['teacher', 'faculty']:
        subjects = get_teacher_subjects(user.get('id'))
        allowed_semesters = sorted(
            {str(s.get('semester')) for s in subjects if s.get('semester')},
            key=lambda x: int(x) if str(x).isdigit() else 0
        )
        teacher_sections = get_teacher_sections(user.get('id')) or []
        for sec in teacher_sections:
            sem = str(sec.get('semester') or '').strip()
            section = str(sec.get('section') or '').strip().upper()
            if sem and section:
                allowed_sections_map.setdefault(sem, [])
                if section not in allowed_sections_map[sem]:
                    allowed_sections_map[sem].append(section)
    elif user.get('role') == 'student':
        if user.get('semester'):
            allowed_semesters = [str(user.get('semester'))]
            section = str(user.get('section') or '').strip().upper()
            if section:
                allowed_sections_map[str(user.get('semester'))] = [section]
    elif user.get('role') == 'hod':
        sections = get_section_catalog(user.get('department')) or []
        allowed_semesters = sorted({str(s.get('semester')) for s in sections if s.get('semester')}, key=lambda x: int(x) if x.isdigit() else 0)
        if not allowed_semesters:
            allowed_semesters = [str(i) for i in range(1, 9)]
        for sec in sections:
            sem = str(sec.get('semester') or '').strip()
            section = str(sec.get('section') or '').strip().upper()
            if sem and section:
                allowed_sections_map.setdefault(sem, [])
                if section not in allowed_sections_map[sem]:
                    allowed_sections_map[sem].append(section)

    for sem_key in list(allowed_sections_map.keys()):
        allowed_sections_map[sem_key] = sorted(set(allowed_sections_map[sem_key]))

    initial_semester = (request.args.get('semester') or '').strip()
    if not initial_semester:
        initial_semester = allowed_semesters[0] if allowed_semesters else '1'
    elif allowed_semesters and initial_semester not in allowed_semesters:
        initial_semester = allowed_semesters[0]

    initial_section = (request.args.get('section') or '').strip().upper()
    if initial_semester:
        sem_sections = allowed_sections_map.get(initial_semester) or []
        if sem_sections and initial_section not in sem_sections:
            initial_section = sem_sections[0]
        if not sem_sections:
            initial_section = ""
    
    return render_template('digital_campus.html', 
                         user=user, 
                         allowed_semesters=allowed_semesters,
                         allowed_sections_map=allowed_sections_map,
                         initial_semester=initial_semester,
                         initial_section=initial_section,
                         current_user=user,
                         show_navbar=True)

# --- Teacher Dashboard (continued) ---

@app.route('/teacher/dashboard')
@login_required
@teacher_required
def teacher_dashboard():
    user = (session.get('user') or {})
    
    # Get teacher stats
    stats = get_teacher_stats(user.get('id'))
    papers = get_papers_by_teacher(user.get('id'))
    subjects = get_teacher_subjects(user.get('id'))
    sections = get_teacher_sections(user.get('id'))
    
    return render_template('teacher_dashboard.html', 
                         user=user, 
                         stats=stats, 
                         papers=papers,
                         subjects=subjects,
                         sections=sections,
                         current_user=user,
                         show_navbar=True)

# --- HOD Dashboard ---

@app.route('/hod/dashboard')
@login_required
@hod_required
def hod_dashboard():
    user = (session.get('user') or {})
    
    # Get HOD stats
    stats = get_hod_stats(user.get('department'))
    question_analysis = session.get('hod_question_paper_analysis')
    pending_papers = get_pending_papers(user.get('department'))
    pending_teachers = get_pending_teachers(user.get('department'))
    teachers = get_all_teachers(user.get('department')) or []
    for teacher in teachers:
        teacher_subjects = get_teacher_subjects(teacher.get('id')) or []
        teacher_sections = get_teacher_sections(teacher.get('id')) or []
        teacher['subjects_count'] = len(teacher_subjects)
        teacher['sections_count'] = len(teacher_sections)
        teacher['subjects'] = teacher_subjects
        teacher['sections'] = teacher_sections
    section_catalog = get_section_catalog(user.get('department')) or []
    semester_options = sorted({str(s.get('semester')) for s in section_catalog if s.get('semester')}, key=lambda x: int(x) if x.isdigit() else 0)
    if not semester_options:
        semester_options = [str(i) for i in range(1, 9)]
    
    return render_template('hod_dashboard.html', 
                         user=user, 
                         stats=stats, 
                         pending_papers=pending_papers,
                         teachers=teachers,
                         section_catalog=section_catalog,
                         semester_options=semester_options,
                         pending_teachers=pending_teachers,
                         question_analysis=question_analysis,
                         current_user=user,
                         show_navbar=True)

@app.route('/hod/academics')
@login_required
@hod_required
def hod_academics():
    user = (session.get('user') or {})
    subjects = get_teacher_subjects(user.get('id')) or []
    sections = get_teacher_sections(user.get('id')) or []
    subject_catalog = get_subject_catalog(user.get('department')) or []
    section_catalog = get_section_catalog(user.get('department')) or []
    return render_template(
        'hod_academics.html',
        user=user,
        subjects=subjects,
        sections=sections,
        subject_catalog=subject_catalog,
        section_catalog=section_catalog,
        current_user=user,
        show_navbar=True
    )

@app.route('/hod/staff')
@login_required
@hod_required
def hod_staff_management():
    user = (session.get('user') or {})
    teachers = get_all_teachers(user.get('department')) or []
    subject_catalog = get_subject_catalog(user.get('department')) or []
    section_catalog = get_section_catalog(user.get('department')) or []
    for t in teachers:
        t['subjects'] = get_teacher_subjects(t.get('id'))
        t['sections'] = get_teacher_sections(t.get('id'))
    return render_template('hod_staff.html',
                         user=user,
                         teachers=teachers,
                         subject_catalog=subject_catalog,
                         section_catalog=section_catalog,
                         current_user=user,
                         show_navbar=True)

@app.route('/hod/analyze-question-papers', methods=['POST'])
@login_required
@hod_required
def analyze_previous_question_papers():
    uploaded_files = request.files.getlist('question_papers')
    top_n = int(request.form.get('top_n') or 10)

    if not uploaded_files or not any(f and f.filename for f in uploaded_files):
        flash('Please upload at least one PDF question paper.', 'error')
        return redirect(url_for('hod_dashboard'))

    all_questions = []
    file_names = []
    for file_obj in uploaded_files:
        if not file_obj or not file_obj.filename:
            continue
        if not allowed_file(file_obj.filename):
            flash(f"Unsupported file type: {file_obj.filename}", 'error')
            return redirect(url_for('hod_dashboard'))

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', dir=tempfile.gettempdir())
        try:
            file_obj.save(tmp.name)
            tmp.close()
            extracted = extract_questions_from_pdf(tmp.name)
            pdf_text = "\n".join(page.get_text("text") for page in fitz.open(tmp.name)) if os.path.exists(tmp.name) else ''
            context = infer_paper_context(file_obj.filename, pdf_text)
            all_questions.extend([
                {
                    'question': item,
                    'source': context,
                } for item in extracted
            ])
            file_names.append(file_obj.filename)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    if not all_questions:
        flash('No readable questions could be extracted from the uploaded PDFs.', 'warning')
        return redirect(url_for('hod_dashboard'))

    results = analyze_repeated_questions(all_questions, top_n=top_n)
    session['hod_question_paper_analysis'] = {
        'files': file_names,
        'top_n': top_n,
        'total_questions': len(all_questions),
        'results': results,
    }
    flash(f'Analyzed {len(all_questions)} questions and found the most repeated ones.', 'success')
    return redirect(url_for('hod_dashboard'))

@app.route('/api/hod/approve-teacher/<teacher_id>', methods=['POST'])
@login_required
@hod_required
def api_approve_teacher(teacher_id):
    set_teacher_approval(teacher_id, True)
    return jsonify({'success': True})

@app.route('/api/hod/revoke-teacher/<teacher_id>', methods=['POST'])
@login_required
@hod_required
def api_revoke_teacher(teacher_id):
    set_teacher_approval(teacher_id, False)
    return jsonify({'success': True})

@app.route('/api/hod/teacher/<teacher_id>/subjects', methods=['POST'])
@login_required
@hod_required
def api_add_teacher_subject(teacher_id):
    data = request.json or {}
    department = (session.get('user') or {}).get('department')
    valid_teacher_ids = {t.get('id') for t in (get_all_teachers(department) or [])}
    if teacher_id not in valid_teacher_ids:
        return jsonify({'success': False, 'message': 'Invalid teacher'}), 400
    catalog_subject_id = data.get('catalog_subject_id')

    code = (data.get('subject_code') or '').strip().upper()
    name = (data.get('subject_name') or '').strip()
    sem = (str(data.get('semester') or '')).strip()

    if catalog_subject_id:
        try:
            catalog_subject_id = int(catalog_subject_id)
            catalog_items = get_subject_catalog(department)
            selected = next((s for s in catalog_items if int(s.get('id')) == catalog_subject_id), None)
            if selected:
                code = (selected.get('subject_code') or '').strip().upper()
                name = (selected.get('subject_name') or '').strip()
                sem = (str(selected.get('semester') or '')).strip()
        except Exception:
            pass

    if not code or not name or not sem:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    if department:
        valid_subject = any(
            (s.get('subject_code') == code and str(s.get('semester')) == str(sem))
            for s in get_subject_catalog(department)
        )
        if not valid_subject:
            return jsonify({'success': False, 'message': 'Subject must be selected from HOD subject catalog.'}), 400

    add_teacher_subject(teacher_id, code, name, sem, department)
    return jsonify({'success': True})

@app.route('/api/hod/teacher/subjects/<int:subject_id>/remove', methods=['POST'])
@login_required
@hod_required
def api_remove_teacher_subject(subject_id):
    remove_teacher_subject(subject_id)
    return jsonify({'success': True})

@app.route('/api/hod/teacher/<teacher_id>/sections', methods=['POST'])
@login_required
@hod_required
def api_add_teacher_section(teacher_id):
    data = request.json or {}
    department = (session.get('user') or {}).get('department')
    valid_teacher_ids = {t.get('id') for t in (get_all_teachers(department) or [])}
    if teacher_id not in valid_teacher_ids:
        return jsonify({'success': False, 'message': 'Invalid teacher'}), 400
    catalog_section_id = data.get('catalog_section_id')
    semester = (str(data.get('semester') or '')).strip()
    section = (str(data.get('section') or '')).strip().upper()

    if catalog_section_id:
        try:
            catalog_section_id = int(catalog_section_id)
            catalog_items = get_section_catalog(department)
            selected = next((s for s in catalog_items if int(s.get('id')) == catalog_section_id), None)
            if selected:
                semester = (str(selected.get('semester') or '')).strip()
                section = (str(selected.get('section') or '')).strip().upper()
        except Exception:
            pass

    if not semester or not section:
        return jsonify({'success': False, 'message': 'Semester and section are required'}), 400

    valid_section = any(
        str(s.get('semester')) == semester and str(s.get('section')).upper() == section
        for s in (get_section_catalog(department) or [])
    )
    if not valid_section:
        return jsonify({'success': False, 'message': 'Section must be selected from HOD section catalog.'}), 400

    add_teacher_section(teacher_id, semester, section, department)
    return jsonify({'success': True})

@app.route('/api/hod/teacher/sections/<int:section_id>/remove', methods=['POST'])
@login_required
@hod_required
def api_remove_teacher_section(section_id):
    remove_teacher_section(section_id)
    return jsonify({'success': True})

@app.route('/api/hod/teacher/replace', methods=['POST'])
@login_required
@hod_required
def api_replace_teacher():
    data = request.json or {}
    from_teacher_id = (data.get('from_teacher_id') or '').strip()
    to_teacher_id = (data.get('to_teacher_id') or '').strip()
    department = (session.get('user') or {}).get('department')
    if not from_teacher_id or not to_teacher_id:
        return jsonify({'success': False, 'message': 'Both source and target teacher are required'}), 400
    if from_teacher_id == to_teacher_id:
        return jsonify({'success': False, 'message': 'Source and target teacher cannot be same'}), 400
    valid_teacher_ids = {t.get('id') for t in (get_all_teachers(department) or [])}
    if from_teacher_id not in valid_teacher_ids or to_teacher_id not in valid_teacher_ids:
        return jsonify({'success': False, 'message': 'Invalid teacher selection'}), 400
    replace_teacher_assignments(from_teacher_id, to_teacher_id)
    return jsonify({'success': True})

@app.route('/api/hod/teacher/<teacher_id>/details')
@login_required
@hod_required
def api_get_teacher_details(teacher_id):
    user = (session.get('user') or {})
    department = user.get('department')
    teacher = next((t for t in (get_all_teachers(department) or []) if t.get('id') == teacher_id), None)
    if not teacher:
        return jsonify({'success': False, 'message': 'Teacher not found'}), 404

    subjects = get_teacher_subjects(teacher_id)
    sections = get_teacher_sections(teacher_id)
    papers = get_papers_by_teacher(teacher_id)
    stats = {
        'total_papers': len(papers),
        'approved': len([p for p in papers if p.get('status') == 'approved']),
        'pending': len([p for p in papers if p.get('status') == 'pending']),
        'rejected': len([p for p in papers if p.get('status') == 'rejected']),
        'draft': len([p for p in papers if p.get('status') == 'draft']),
    }

    recent_papers = [
        {
            'id': p.get('id'),
            'title': p.get('title') or p.get('course_code'),
            'course_code': p.get('course_code'),
            'status': p.get('status'),
            'created_at': p.get('created_at')
        }
        for p in papers[:10]
    ]

    return jsonify({
        'success': True,
        'teacher': teacher,
        'subjects': subjects,
        'sections': sections,
        'stats': stats,
        'recent_papers': recent_papers
    })

@app.route('/api/hod/profile', methods=['POST'])
@login_required
@hod_required
def api_hod_profile_update():
    data = request.json or {}
    user = (session.get('user') or {})
    uid = user.get('id')
    phone = (data.get('phone') or '').strip()
    semester = (str(data.get('semester') or '')).strip() or None
    section = (str(data.get('section') or '')).strip().upper() or None
    update_teacher_profile(uid, phone=phone, profile_complete=True, semester=semester, section=section)
    refreshed = get_user(uid) or user
    session['user'] = refreshed
    return jsonify({'success': True, 'user': refreshed})

@app.route('/api/hod/self/subjects', methods=['POST'])
@login_required
@hod_required
def api_hod_self_add_subject():
    data = request.json or {}
    user = (session.get('user') or {})
    uid = user.get('id')
    department = user.get('department')
    catalog_subject_id = data.get('catalog_subject_id')
    if not catalog_subject_id:
        return jsonify({'success': False, 'message': 'Subject is required'}), 400
    try:
        catalog_subject_id = int(catalog_subject_id)
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid subject'}), 400

    catalog_items = get_subject_catalog(department) or []
    selected = next((s for s in catalog_items if int(s.get('id')) == catalog_subject_id), None)
    if not selected:
        return jsonify({'success': False, 'message': 'Invalid subject selection'}), 400

    existing = get_teacher_subjects(uid) or []
    duplicate = next(
        (
            s for s in existing
            if (s.get('subject_code') == selected.get('subject_code') and str(s.get('semester')) == str(selected.get('semester'))
                and (s.get('department') or department) == department)
        ),
        None
    )
    if not duplicate:
        add_teacher_subject(
            uid,
            selected.get('subject_code'),
            selected.get('subject_name'),
            selected.get('semester'),
            department
        )
    updated = get_teacher_subjects(uid) or []
    return jsonify({'success': True, 'subjects': updated})

@app.route('/api/hod/self/subjects/<int:subject_id>/remove', methods=['POST'])
@login_required
@hod_required
def api_hod_self_remove_subject(subject_id):
    uid = (session.get('user') or {}).get('id')
    remove_teacher_subject(subject_id, uid)
    return jsonify({'success': True, 'subjects': get_teacher_subjects(uid) or []})

@app.route('/api/hod/self/sections', methods=['POST'])
@login_required
@hod_required
def api_hod_self_add_section():
    data = request.json or {}
    user = (session.get('user') or {})
    uid = user.get('id')
    department = user.get('department')
    catalog_section_id = data.get('catalog_section_id')
    if not catalog_section_id:
        return jsonify({'success': False, 'message': 'Section is required'}), 400
    try:
        catalog_section_id = int(catalog_section_id)
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid section'}), 400

    catalog_items = get_section_catalog(department) or []
    selected = next((s for s in catalog_items if int(s.get('id')) == catalog_section_id), None)
    if not selected:
        return jsonify({'success': False, 'message': 'Invalid section selection'}), 400

    add_teacher_section(uid, selected.get('semester'), selected.get('section'), department)
    updated = get_teacher_sections(uid) or []
    return jsonify({'success': True, 'sections': updated})

@app.route('/api/hod/self/sections/<int:section_id>/remove', methods=['POST'])
@login_required
@hod_required
def api_hod_self_remove_section(section_id):
    uid = (session.get('user') or {}).get('id')
    remove_teacher_section(section_id, uid)
    return jsonify({'success': True, 'sections': get_teacher_sections(uid) or []})

@app.route('/api/hod/staff/create', methods=['POST'])
@login_required
@hod_required
def api_hod_create_staff():
    data = request.json or {}
    department = (session.get('user') or {}).get('department')
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip()
    subject_ids = data.get('subject_ids') or []
    section_ids = data.get('section_ids') or []

    if not name or not email or not phone:
        return jsonify({'success': False, 'message': 'Name, email and phone are required'}), 400
    if not subject_ids:
        return jsonify({'success': False, 'message': 'Select at least one subject'}), 400
    if not section_ids:
        return jsonify({'success': False, 'message': 'Select at least one section'}), 400

    catalog_subjects = get_subject_catalog(department) or []
    subj_by_id = {int(s.get('id')): s for s in catalog_subjects}
    selected_subjects = []
    for sid in subject_ids:
        try:
            sid_int = int(sid)
        except Exception:
            continue
        if sid_int in subj_by_id:
            selected_subjects.append(subj_by_id[sid_int])
    if not selected_subjects:
        return jsonify({'success': False, 'message': 'Invalid subject selection'}), 400

    catalog_sections = get_section_catalog(department) or []
    sec_by_id = {int(s.get('id')): s for s in catalog_sections}
    selected_sections = []
    for sec_id in section_ids:
        try:
            sec_int = int(sec_id)
        except Exception:
            continue
        if sec_int in sec_by_id:
            selected_sections.append(sec_by_id[sec_int])
    if not selected_sections:
        return jsonify({'success': False, 'message': 'Invalid section selection'}), 400

    temp_uid = f"manual_{uuid.uuid4().hex[:20]}"
    create_user(
        temp_uid,
        email,
        name,
        'teacher',
        department=department,
        photo_url=None,
        email_verified=True,
        phone=phone,
        section=(selected_sections[0].get('section') if selected_sections else None),
        semester=(selected_sections[0].get('semester') if selected_sections else None)
    )
    created_user = get_user(temp_uid) or get_user_by_email(email) or {}
    teacher_id = created_user.get('id') or temp_uid
    update_teacher_profile(teacher_id, phone=phone, profile_complete=True)
    set_teacher_approval(teacher_id, True)

    clear_teacher_subjects(teacher_id)
    clear_teacher_sections(teacher_id)
    for s in selected_subjects:
        add_teacher_subject(teacher_id, s.get('subject_code'), s.get('subject_name'), s.get('semester'), department)
    for sec in selected_sections:
        add_teacher_section(teacher_id, sec.get('semester'), sec.get('section'), department)

    return jsonify({
        'success': True,
        'message': 'Staff added and approved. Ask staff to sign up/login with the same email to access dashboard.'
    })

@app.route('/api/hod/catalog/sections', methods=['POST'])
@login_required
@hod_required
def api_add_section_catalog():
    data = request.json or {}
    semester = (str(data.get('semester') or '')).strip()
    section = (str(data.get('section') or '')).strip().upper()
    department = (session.get('user') or {}).get('department')
    if not semester or not section:
        return jsonify({'success': False, 'message': 'Semester and section are required'}), 400
    add_section_catalog(department, semester, section)
    return jsonify({'success': True})

@app.route('/api/hod/catalog/sections/auto', methods=['POST'])
@login_required
@hod_required
def api_auto_add_section_catalog():
    data = request.json or {}
    semester = (str(data.get('semester') or '')).strip()
    count_raw = data.get('count')
    department = (session.get('user') or {}).get('department')

    try:
        count = int(count_raw)
    except Exception:
        return jsonify({'success': False, 'message': 'Section count must be a number'}), 400

    if not semester:
        return jsonify({'success': False, 'message': 'Semester is required'}), 400
    if count < 1 or count > 26:
        return jsonify({'success': False, 'message': 'Section count must be between 1 and 26'}), 400

    created = []
    for i in range(count):
        letter = chr(ord('A') + i)
        # Example: 6A, 6B, 6C
        section_label = f"{semester}{letter}"
        add_section_catalog(department, semester, section_label)
        created.append(section_label)

    return jsonify({'success': True, 'created': created})

@app.route('/api/hod/catalog/sections/<int:section_id>/remove', methods=['POST'])
@login_required
@hod_required
def api_remove_section_catalog(section_id):
    remove_section_catalog(section_id)
    return jsonify({'success': True})

@app.route('/api/hod/catalog/subjects', methods=['POST'])
@login_required
@hod_required
def api_add_subject_catalog():
    data = request.json or {}
    semester = (str(data.get('semester') or '')).strip()
    subject_code = (data.get('subject_code') or '').strip().upper()
    subject_name = (data.get('subject_name') or '').strip()
    department = (session.get('user') or {}).get('department')
    if not semester or not subject_code or not subject_name:
        return jsonify({'success': False, 'message': 'Semester, subject code and subject name are required'}), 400
    add_subject_catalog(department, semester, subject_code, subject_name)
    return jsonify({'success': True})

@app.route('/api/hod/catalog/subjects/<int:subject_id>/remove', methods=['POST'])
@login_required
@hod_required
def api_remove_subject_catalog(subject_id):
    remove_subject_catalog(subject_id)
    return jsonify({'success': True})

@app.route('/hod/history')
@login_required
@hod_required
def hod_paper_history():
    user = (session.get('user') or {})
    
    # Get filter parameters
    teacher_filter = request.args.get('teacher', '')
    subject_filter = request.args.get('subject', '')
    status_filter = request.args.get('status', '')
    
    # Get all papers with filters
    papers = get_all_papers_for_hod(
        department=user.get('department'),
        teacher_id=teacher_filter if teacher_filter else None,
        course_code=subject_filter if subject_filter else None,
        status=status_filter if status_filter else None
    )
    
    # Get list of teachers for filter dropdown
    teachers = get_all_teachers(user.get('department'))
    
    return render_template('hod_history.html', 
                         user=user, 
                         papers=papers,
                         teachers=teachers,
                         teacher_filter=teacher_filter,
                         subject_filter=subject_filter,
                         status_filter=status_filter,
                         current_user=user,
                         show_navbar=True)

# --- Paper Approval Routes ---

@app.route('/paper/<int:paper_id>/review')
@login_required
@hod_required
def review_paper(paper_id):
    user = (session.get('user') or {})
    paper = get_paper(paper_id)
    
    if not paper:
        flash('Paper not found.', 'error')
        return redirect(url_for('hod_dashboard'))
    
    return render_template('paper_review.html',
                         paper=paper,
                         current_user=user,
                         show_navbar=True)

@app.route('/paper/<int:paper_id>')
@login_required
def view_paper(paper_id):
    user = (session.get('user') or {})
    paper = get_paper(paper_id)
    
    if not paper:
        flash('Paper not found.', 'error')
        return redirect(url_for('dashboard'))
    
    role = (user.get('role') or 'student')
    if role in ['teacher', 'faculty']:
        if paper.get('teacher_id') != user.get('id'):
            flash('Access denied.', 'error')
            return redirect(url_for('dashboard'))
    elif role == 'hod':
        if paper.get('department') != user.get('department'):
            flash('Access denied.', 'error')
            return redirect(url_for('dashboard'))
    else:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))
    
    data = paper.get('paper_data') or {}
    paper_questions = data.get('paper_questions') or []
    co_outcomes = data.get('co_outcomes') or []
    rbt_totals = data.get('rbt_totals') or {}
    
    if not paper_questions:
        flash('Paper content not available for this record.', 'warning')
        return redirect(url_for('my_papers') if role in ['teacher', 'faculty'] else url_for('hod_history'))
    
    # Attach signatures from local uploads — pass directly to template
    if paper.get('teacher_signature'):
        data['prepared_by_sig_encoded'] = paper.get('teacher_signature')
    if paper.get('status') == 'approved':
        if paper.get('principal_signature'):
            data['principal_sig_encoded'] = paper.get('principal_signature')
        if paper.get('hod_signature'):
            data['hod_sig_encoded'] = paper.get('hod_signature')
    
    return render_template('paper.html',
                         data=data,
                         paper_questions=paper_questions,
                         co_outcomes=co_outcomes,
                         rbt_totals=rbt_totals,
                         paper_id=paper_id,
                         current_user=user,
                         show_send_to_hod=(role in ['teacher', 'faculty'] and paper.get('status') == 'draft'),
                         show_my_papers=(role in ['teacher', 'faculty']),
                         show_navbar=False)

@app.route('/api/paper/<int:paper_id>/approve', methods=['POST'])
@login_required
@hod_required
def api_approve_paper(paper_id):
    user = (session.get('user') or {})
    
    # Get HOD signature
    hod_signature = user.get('signature_path')
    if not hod_signature:
        return jsonify({'success': False, 'message': 'Please upload your signature first.'}), 400

    principal_signature = user.get('principal_signature_path')
    if not principal_signature:
        return jsonify({'success': False, 'message': 'Please upload principal signature first.'}), 400
    
    approve_paper(paper_id, hod_signature, principal_signature)
    
    return jsonify({'success': True, 'message': 'Paper approved successfully!'})

@app.route('/api/paper/<int:paper_id>/reject', methods=['POST'])
@login_required
@hod_required
def api_reject_paper(paper_id):
    data = request.json or {}
    comments = data.get('comments', '')
    
    if not comments:
        return jsonify({'success': False, 'message': 'Please provide rejection comments.'}), 400
    
    reject_paper(paper_id, comments)
    
    return jsonify({'success': True, 'message': 'Paper rejected with comments.'})

@app.route('/api/paper/<int:paper_id>/submit', methods=['POST'])
@login_required
@teacher_required
def api_submit_paper(paper_id):
    user = (session.get('user') or {})
    paper = get_paper(paper_id)
    
    if not paper or paper['teacher_id'] != user.get('id'):
        return jsonify({'success': False, 'message': 'Paper not found.'}), 404

    if not paper.get('teacher_signature'):
        return jsonify({'success': False, 'message': 'Please upload your signature before submitting.'}), 400
    
    submit_paper(paper_id)
    
    return jsonify({'success': True, 'message': 'Paper submitted for HOD review!'})

# --- Upload Routes ---

@app.route('/api/upload/signature', methods=['POST'])
@login_required
def upload_signature():
    user = (session.get('user') or {})
    user_id = user.get('id')

    if not user_id:
        return jsonify({'success': False, 'message': 'User not found in session'}), 400

    if 'signature' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400

    file = request.files['signature']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    url = cloud_storage.upload_file(file, subfolder='signatures', resource_type='image')
    if url:
        update_user_signature(user_id, url)
        updated_user = get_user(user_id)
        if updated_user:
            session['user'] = updated_user
        return jsonify({'success': True, 'path': url})

    return jsonify({'success': False, 'message': 'Upload failed'}), 500

@app.route('/api/upload/principal-signature', methods=['POST'])
@login_required
@hod_required
def upload_principal_signature():
    user = (session.get('user') or {})
    user_id = user.get('id')

    if not user_id:
        return jsonify({'success': False, 'message': 'User not found in session'}), 400

    if 'signature' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400

    file = request.files['signature']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    url = cloud_storage.upload_file(file, subfolder='signatures', resource_type='image')
    if url:
        update_principal_signature(user_id, url)
        updated_user = get_user(user_id)
        if updated_user:
            session['user'] = updated_user
        return jsonify({'success': True, 'path': url})

    return jsonify({'success': False, 'message': 'Upload failed'}), 500

@app.route('/api/teacher/complete-profile', methods=['POST'])
@login_required
def complete_teacher_profile():
    user = (session.get('user') or {})
    if (user.get('role') or '') not in ['teacher', 'faculty']:
        return jsonify({'success': False, 'message': 'Invalid role'}), 403
    if not user.get('email_verified'):
        return jsonify({'success': False, 'message': 'Please verify your email first.'}), 400
    
    data = request.json or {}
    phone = (data.get('phone') or '').strip()
    subject_ids = data.get('subject_ids') or []
    section_ids = data.get('section_ids') or []
    
    if not phone:
        return jsonify({'success': False, 'message': 'Phone number is required'}), 400
    if not subject_ids:
        return jsonify({'success': False, 'message': 'At least one subject is required'}), 400
    if not section_ids:
        return jsonify({'success': False, 'message': 'At least one section is required'}), 400

    catalog = get_subject_catalog(user.get('department')) or []
    catalog_by_id = {int(s.get('id')): s for s in catalog}
    selected_catalog_items = []
    for sid in subject_ids:
        try:
            sid_int = int(sid)
        except Exception:
            continue
        if sid_int in catalog_by_id:
            selected_catalog_items.append(catalog_by_id[sid_int])
    if not selected_catalog_items:
        return jsonify({'success': False, 'message': 'Invalid subject selection'}), 400

    section_catalog = get_section_catalog(user.get('department')) or []
    section_by_id = {int(s.get('id')): s for s in section_catalog}
    selected_sections = []
    for sec_id in section_ids:
        try:
            sec_id_int = int(sec_id)
        except Exception:
            continue
        if sec_id_int in section_by_id:
            selected_sections.append(section_by_id[sec_id_int])
    if not selected_sections:
        return jsonify({'success': False, 'message': 'Invalid section selection'}), 400
    
    # Replace subjects
    clear_teacher_subjects(user.get('id'))
    clear_teacher_sections(user.get('id'))
    for s in selected_catalog_items:
        add_teacher_subject(
            user.get('id'),
            (s.get('subject_code') or '').strip().upper(),
            (s.get('subject_name') or '').strip(),
            (str(s.get('semester') or '')).strip(),
            user.get('department')
        )
    for sec in selected_sections:
        add_teacher_section(
            user.get('id'),
            sec.get('semester'),
            sec.get('section'),
            user.get('department')
        )
    
    primary_sem = (selected_sections[0].get('semester') if selected_sections else None)
    primary_sec = (selected_sections[0].get('section') if selected_sections else None)
    update_teacher_profile(user.get('id'), phone=phone, profile_complete=True, semester=primary_sem, section=primary_sec)
    # Refresh session
    refreshed = get_user(user.get('id'))
    if refreshed:
        session['user'] = refreshed
    return jsonify({'success': True})

@app.route('/upload-notes')
@login_required
@academic_staff_required
def upload_notes_page():
    user = (session.get('user') or {})
    subjects = get_teacher_subjects(user.get('id'))
    if not subjects:
        flash('Assign at least one subject before uploading notes.', 'error')
        if (user.get('role') or '').lower() == 'hod':
            return redirect(url_for('hod_academics'))
        return redirect(url_for('teacher_dashboard'))
    return render_template('upload_resource.html', resource_type='notes', current_user=user, show_navbar=True, subjects=subjects)

@app.route('/upload-qb')
@login_required
@academic_staff_required
def upload_qb_page():
    user = (session.get('user') or {})
    subjects = get_teacher_subjects(user.get('id'))
    if not subjects:
        flash('Assign at least one subject before uploading question banks.', 'error')
        if (user.get('role') or '').lower() == 'hod':
            return redirect(url_for('hod_academics'))
        return redirect(url_for('teacher_dashboard'))
    return render_template('upload_resource.html', resource_type='qb', current_user=user, show_navbar=True, subjects=subjects)

@app.route('/api/upload/resource', methods=['POST'])
@login_required
@academic_staff_required
def upload_resource():
    user = (session.get('user') or {})
    resource_type = request.form.get('resource_type')
    title = request.form.get('title')
    subject = request.form.get('subject')
    subject_code = request.form.get('subject_code')
    semester = request.form.get('semester')
    department = request.form.get('department')

    file = request.files.get('file')
    if not file:
        flash('No file uploaded', 'error')
        return redirect(request.referrer)

    # Validate subject access first (before uploading)
    subjects = get_teacher_subjects(user.get('id'))
    if not subjects:
        flash('No subject assignment found. Update your class handling profile first.', 'error')
        if (user.get('role') or '').lower() == 'hod':
            return redirect(url_for('hod_academics'))
        return redirect(url_for('teacher_dashboard'))
    allowed = {(s.get('subject_code'), str(s.get('semester'))) for s in subjects}
    if allowed and (subject_code, str(semester)) not in allowed:
        flash('You are not authorized for this subject/semester.', 'error')
        return redirect(request.referrer)

    subfolder = 'notes' if resource_type == 'notes' else 'question_banks'
    file_url = cloud_storage.upload_file(file, subfolder=subfolder, resource_type='auto')

    if file_url:
        if resource_type == 'notes':
            create_note(user['id'], title, subject, department, file_url, file.filename)
            flash('Notes uploaded successfully!', 'success')
        else:
            create_question_bank(user['id'], title, subject, department, file_url, file.filename)
            flash('Question Bank uploaded successfully!', 'success')
        if (user.get('role') or '').lower() == 'hod':
            return redirect(url_for('hod_academics'))
        return redirect(url_for('teacher_dashboard'))

    flash('Upload failed. Please try again.', 'error')
    return redirect(request.referrer)

# --- Paper Generation Routes ---

@app.route('/generate', methods=['GET'])
@login_required
@academic_staff_required
def generate_form():
    user = (session.get('user') or {})
    subjects = get_teacher_subjects(user.get('id'))
    if not subjects:
        flash('No subjects assigned. Update your class handling profile first.', 'error')
        if (user.get('role') or '').lower() == 'hod':
            return redirect(url_for('hod_academics'))
        return redirect(url_for('teacher_dashboard'))
    allowed_codes = {normalize_subject_code(s.get('subject_code')) for s in subjects if s.get('subject_code')}

    # Get available question banks for the user's department and allowed subjects
    raw_question_banks = get_all_question_banks(user.get('department'))
    question_banks = []
    for qb in raw_question_banks:
        qb_data = dict(qb)
        parsed_code, parsed_sem = extract_qb_subject_parts(qb_data.get('subject'))
        qb_data['subject_code_parsed'] = normalize_subject_code(parsed_code)
        qb_data['semester_core_parsed'] = semester_core(parsed_sem)
        if qb_data['subject_code_parsed'] and (not allowed_codes or qb_data['subject_code_parsed'] in allowed_codes):
            question_banks.append(qb_data)

    return render_template('index.html', current_user=user, show_navbar=True, question_banks=question_banks, subjects=subjects)

@app.route('/api/paper/preview', methods=['POST'])
@login_required
@academic_staff_required
def preview_paper():
    """Generate a draft preview with alternatives for each question slot."""
    try:
        user = (session.get('user') or {})
        form_data = request.form.to_dict()
        selected_code = (form_data.get('course_code') or '').strip()
        selected_sem = (form_data.get('semester') or '').strip()

        # Enforce teacher's assigned subject/semester access
        subjects = get_teacher_subjects(user.get('id'))
        if not subjects:
            return jsonify({'success': False, 'message': 'No subject assignment found. Update profile first.'}), 403
        allowed = {(s.get('subject_code'), str(s.get('semester'))) for s in subjects}
        if allowed and (selected_code, selected_sem) not in allowed:
            return jsonify({'success': False, 'message': 'You are not authorized for this subject/semester'}), 403
        
        # Get selected question bank IDs
        qb_ids = request.form.getlist('qb_ids[]')
        
        if not qb_ids:
            return jsonify({'success': False, 'message': 'At least one Question Bank must be selected'}), 400
            
        # Get question bank details from database
        selected_qbs = get_question_banks_by_ids(qb_ids)
        
        if not selected_qbs:
             return jsonify({'success': False, 'message': 'Selected Question Banks not found'}), 404

        # Ensure selected QBs match selected subject/semester
        invalid_qbs = [qb.get('title', 'Unknown Module') for qb in selected_qbs if not question_bank_matches_subject(qb, selected_code, selected_sem)]
        if invalid_qbs:
            return jsonify({
                'success': False,
                'message': f'Selected question bank does not match {selected_code} (Sem {selected_sem}): {invalid_qbs[0]}'
            }), 400
        
        questions_pool = []
        co_descriptions = {}
        q_counter = 1
        modules_parsed = []
        
        # Parse each module PDF from stored path
        for qb in selected_qbs:
            file_path = qb.get('file_path')
            # Handle both absolute and relative paths
            if not os.path.isabs(file_path):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_path)
                
            if os.path.exists(file_path):
                module_name = qb.get('title', 'Unknown Module')
                
                # Parse questions from this module
                module_questions, module_cos = parse_question_bank_pdf(file_path)
                
                # Add module info to each question and update IDs
                for q in module_questions:
                    q['id'] = q_counter
                    q['module'] = module_name
                    q_counter += 1
                    questions_pool.append(q)
                
                co_descriptions.update(module_cos)
                modules_parsed.append(module_name)
            else:
                print(f"File not found: {file_path}")
        
        if not questions_pool:
            return jsonify({'success': False, 'message': 'No questions found in the selected Question Banks'}), 400
        
        # Group questions by marks
        questions_by_marks = {}
        for q in questions_pool:
            marks = q['marks']
            if marks not in questions_by_marks:
                questions_by_marks[marks] = []
            questions_by_marks[marks].append(q)
        
        # Build questions for preview with all alternatives
        preview_questions = []
        used_question_ids = set()  # Track used questions to prevent duplicates
        
        for i in range(1, 7):
            marks_string = form_data.get(f'q{i}_marks', '')
            marks_list = []
            if marks_string:
                try:
                    marks_list = [int(m.strip()) for m in marks_string.split(',') if m.strip()]
                except ValueError:
                    continue
            
            if not marks_list:
                continue
            
            question_data = {
                'number': str(i),
                'sub_questions': [],
                'total_marks': sum(marks_list)
            }
            
            for sub_index, marks in enumerate(marks_list):
                # Get only questions not already used
                available = [q for q in questions_by_marks.get(marks, []) if q['id'] not in used_question_ids]
                
                if available:
                    # Select first available as default (mark as used)
                    selected_q = available[0]
                    used_question_ids.add(selected_q['id'])
                    
                    sub_q = {
                        'letter': chr(97 + sub_index),
                        'marks': marks,
                        'slot_id': f'q{i}_{sub_index}',
                        'selected_index': 0,
                        'options': []
                    }
                    
                    # First option is the selected one
                    sub_q['options'].append({
                        'id': selected_q['id'],
                        'text': selected_q['text'],
                        'co': selected_q['co'],
                        'rbt': selected_q['rbt'],
                        'marks': selected_q['marks'],
                        'module': selected_q.get('module', 'Unknown')
                    })
                    
                    # Add remaining alternatives (excluding all used questions)
                    for q in available[1:]:
                        sub_q['options'].append({
                            'id': q['id'],
                            'text': q['text'],
                            'co': q['co'],
                            'rbt': q['rbt'],
                            'marks': q['marks'],
                            'module': q.get('module', 'Unknown')
                        })
                    
                    question_data['sub_questions'].append(sub_q)
            
            if question_data['sub_questions']:
                preview_questions.append(question_data)
        
        return jsonify({
            'success': True,
            'questions': preview_questions,
            'total_questions_in_pool': len(questions_pool),
            'questions_by_marks': {str(k): len(v) for k, v in questions_by_marks.items()}
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/generate', methods=['POST'])
@login_required
@academic_staff_required
def generate_paper():
    try:
        user = (session.get('user') or {})
        form_data = request.form.to_dict()
        
        # Enforce subject/semester access
        subjects = get_teacher_subjects(user.get('id'))
        if not subjects:
            flash("No subject assignment found. Update your profile first.", "error")
            if (user.get('role') or '').lower() == 'hod':
                return redirect(url_for('hod_academics'))
            return redirect(url_for('teacher_dashboard'))
        allowed = {(s.get('subject_code'), str(s.get('semester'))) for s in subjects}
        selected_code = (form_data.get('course_code') or '').strip()
        selected_sem = (form_data.get('semester') or '').strip()
        if allowed and (selected_code, selected_sem) not in allowed:
            flash("You are not authorized to generate papers for this subject/semester.", "error")
            return redirect(url_for('generate_form'))

        # Get selected question bank IDs (handle both list and direct access)
        qb_ids = request.form.getlist('qb_ids[]')
        
        if not qb_ids:
            flash("At least one Question Bank must be selected.", "error")
            return redirect(url_for('generate_form'))

        # Get question bank details from database
        selected_qbs = get_question_banks_by_ids(qb_ids)
        
        if not selected_qbs:
             flash("Selected Question Banks not found.", "error")
             return redirect(url_for('generate_form'))

        # Ensure selected QBs match selected subject/semester
        invalid_qbs = [qb.get('title', 'Unknown Module') for qb in selected_qbs if not question_bank_matches_subject(qb, selected_code, selected_sem)]
        if invalid_qbs:
            flash(f"Selected question bank does not match {selected_code} (Sem {selected_sem}): {invalid_qbs[0]}", "error")
            return redirect(url_for('generate_form'))

        combined_questions = []
        combined_cos = {}
        q_counter = 1
        
        # Parse each module PDF
        for qb in selected_qbs:
            file_path = qb.get('file_path')
            # Handle both absolute and relative paths
            if not os.path.isabs(file_path):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_path)
            
            if os.path.exists(file_path):
                module_name = qb.get('title', 'Unknown Module')
                
                module_questions, module_cos = parse_question_bank_pdf(file_path)
                
                for q in module_questions:
                    q['id'] = q_counter
                    q['module'] = module_name
                    q_counter += 1
                    combined_questions.append(q)
                
                combined_cos.update(module_cos)
            else:
                 print(f"File not found: {file_path}")
        
        # Handle image uploads
        logo_file = request.files.get('logo_image')
        if logo_file and logo_file.filename != '':
            form_data['logo_encoded'] = encode_image_to_base64(logo_file)
        else:
            # Auto-use static logo
            static_logo_path = os.path.join(app.root_path, 'static', 'logo.jpeg')
            if os.path.exists(static_logo_path):
                with open(static_logo_path, 'rb') as f:
                    encoded = base64.b64encode(f.read()).decode('utf-8')
                    form_data['logo_encoded'] = f"data:image/jpeg;base64,{encoded}"
        
        # Teacher signature (required)
        teacher_sig_file = request.files.get('teacher_signature')
        teacher_sig_path = None
        if teacher_sig_file:
            teacher_sig_path = cloud_storage.upload_file(teacher_sig_file, subfolder='signatures', resource_type='image')
            teacher_sig_file.seek(0)  # Reset file pointer
            form_data['teacher_sig_encoded'] = encode_image_to_base64(teacher_sig_file)
            form_data['prepared_by_sig_encoded'] = form_data.get('teacher_sig_encoded')
        else:
            # Use saved signature if available
            if user.get('signature_path'):
                teacher_sig_path = user.get('signature_path')
                # Load from file
                sig_full_path = os.path.join(app.config['UPLOAD_FOLDER'], teacher_sig_path)
                if os.path.exists(sig_full_path):
                    with open(sig_full_path, 'rb') as f:
                        encoded = base64.b64encode(f.read()).decode('utf-8')
                        form_data['teacher_sig_encoded'] = f"data:image/png;base64,{encoded}"
                        form_data['prepared_by_sig_encoded'] = form_data.get('teacher_sig_encoded')

        # Use combined questions from all modules
        questions_pool = combined_questions
        co_descriptions = combined_cos

        if not questions_pool:
            flash("Could not parse any questions from the provided PDFs.", "error")
            return redirect(url_for('generate_form'))

        # CO-balanced selection logic
        total_paper_marks = 0

        def normalize_co_list(value):
            if not value:
                return []
            text = str(value).upper()
            # Prefer explicit CO tokens
            tokens = re.findall(r'CO\s*\d+', text)
            if tokens:
                return [t.replace(' ', '') for t in tokens]
            # Fallback split by separators
            parts = re.split(r'[,/]|\\s+and\\s+|&', text, flags=re.IGNORECASE)
            cleaned = [p.strip().upper().replace(' ', '') for p in parts if p and p.strip()]
            valid = [p for p in cleaned if re.match(r'^CO\\d+$', p)]
            return valid or cleaned

        def normalize_rbt_list(value):
            if not value:
                return []
            text = str(value)
            tokens = re.findall(r'\bL\s*([1-6])\b', text, re.IGNORECASE)
            if tokens:
                return [f"L{t}" for t in tokens]
            lower = text.lower()
            mapping = {
                'remember': 'L1',
                'understand': 'L2',
                'apply': 'L3',
                'analyze': 'L4',
                'analyse': 'L4',
                'evaluate': 'L5',
                'create': 'L6'
            }
            found = []
            for key, code in mapping.items():
                if key in lower:
                    found.append(code)
            if found:
                return sorted(set(found), key=lambda x: int(x[1]))
            # Try split by separators for tokens like "L1/L2"
            parts = re.split(r'[,/]|\\s+and\\s+|&', text, flags=re.IGNORECASE)
            out = []
            for p in parts:
                m = re.search(r'\bL\s*([1-6])\b', p, re.IGNORECASE)
                if m:
                    out.append(f"L{m.group(1)}")
            if out:
                return out
            m = re.search(r'([1-6])', text)
            if m:
                return [f"L{m.group(1)}"]
            return []

        all_cos_in_pool = set()
        for q in questions_pool:
            co_list = normalize_co_list(q.get('co'))
            if co_list:
                all_cos_in_pool.update(co_list)
            elif q.get('co'):
                all_cos_in_pool.add(q.get('co'))
        num_cos = len(all_cos_in_pool)

        modules_in_pool = {q.get('module', 'Unknown') for q in questions_pool}
        num_modules = len(modules_in_pool) if modules_in_pool else 0

        for i in range(1, 7, 2):
            marks_string = form_data.get(f'q{i}_marks', '')
            if marks_string:
                try:
                    marks_list = [int(m.strip()) for m in marks_string.split(',') if m.strip()]
                    total_paper_marks += sum(marks_list)
                except ValueError:
                    flash(f"Invalid marks format for Question {i}", "error")
                    return redirect(url_for('generate_form'))

        target_marks_per_co = total_paper_marks / num_cos if num_cos > 0 else 0
        co_marks_so_far = {co: 0 for co in all_cos_in_pool}
        target_marks_per_module = total_paper_marks / num_modules if num_modules > 0 else 0
        module_marks_so_far = {m: 0 for m in modules_in_pool}
        
        configured_questions = {}
        used_question_ids = set()
        
        for i in range(1, 7):
            marks_string = form_data.get(f'q{i}_marks', '')
            marks_list = []
            if marks_string:
                try:
                    marks_list = [int(m.strip()) for m in marks_string.split(',') if m.strip()]
                except ValueError:
                    flash(f"Invalid marks format for Question {i}", "error")
                    return redirect(url_for('generate_form'))

            if not marks_list:
                continue

            main_question_data = {
                'number': str(i), 'sub_questions': [], 'total_marks': sum(marks_list),
                'main_co': set(), 'main_rbt': set()
            }

            for sub_index, marks in enumerate(marks_list):
                eligible_by_mark = [q for q in questions_pool if q['marks'] == marks and q['id'] not in used_question_ids]
                
                if not eligible_by_mark:
                    flash(f"Could not find an unused question worth {marks} marks for Q{i}.", "error")
                    return redirect(url_for('generate_form'))

                def calculate_cost(q):
                    co_list = normalize_co_list(q.get('co'))
                    if not co_list:
                        co_list = [q.get('co')]
                    co_costs = []
                    for co in co_list:
                        current_marks = co_marks_so_far.get(co, 0)
                        future_marks = current_marks + q['marks']
                        co_costs.append(abs(future_marks - target_marks_per_co))
                    co_cost = sum(co_costs) / len(co_costs) if co_costs else 0
                    
                    module = q.get('module', 'Unknown')
                    mod_current = module_marks_so_far.get(module, 0)
                    mod_future = mod_current + q['marks']
                    mod_cost = abs(mod_future - target_marks_per_module) if num_modules > 0 else 0
                    
                    return co_cost + mod_cost
                
                eligible_by_mark.sort(key=calculate_cost)
                selected_q = eligible_by_mark[0]
                
                used_question_ids.add(selected_q['id'])
                co_list = normalize_co_list(selected_q.get('co'))
                if not co_list:
                    co_list = [selected_q.get('co')]
                for co in co_list:
                    if co in co_marks_so_far:
                        co_marks_so_far[co] += selected_q['marks']
                module_name = selected_q.get('module', 'Unknown')
                if module_name in module_marks_so_far:
                    module_marks_so_far[module_name] += selected_q['marks']
                
                main_question_data['sub_questions'].append({
                    'letter': chr(97 + sub_index), 'text': selected_q['text'],
                    'marks': selected_q['marks'], 'co': selected_q['co'], 'rbt': selected_q['rbt']
                })
                co_list = normalize_co_list(selected_q['co'])
                if co_list:
                    for co in co_list:
                        main_question_data['main_co'].add(co)
                else:
                    main_question_data['main_co'].add(selected_q['co'])
                rbt_list = normalize_rbt_list(selected_q['rbt'])
                if rbt_list:
                    for rbt in rbt_list:
                        main_question_data['main_rbt'].add(rbt.strip().upper())
                else:
                    main_question_data['main_rbt'].add(selected_q['rbt'])
            
            configured_questions[f'q{i}'] = main_question_data

        final_paper_questions = []
        for i in range(1, 7):
            if f'q{i}' in configured_questions:
                final_paper_questions.append(configured_questions[f'q{i}'])

        # Calculate totals for summary table
        co_totals = {co: 0 for co in co_descriptions.keys()}
        rbt_totals = {}
        for q_data in final_paper_questions:
            for sub_q in q_data['sub_questions']:
                co_list = normalize_co_list(sub_q['co'])
                if not co_list:
                    co_list = [sub_q['co']]
                for co in co_list:
                    if co in co_totals:
                        co_totals[co] += sub_q['marks']
                    else:
                        co_totals[co] = sub_q['marks']
                rbt_list = normalize_rbt_list(sub_q['rbt'])
                for rbt_key in rbt_list:
                    key = rbt_key.strip().upper()
                    if re.match(r'^L[1-6]$', key):
                        rbt_totals[key] = rbt_totals.get(key, 0) + sub_q['marks']
        
        co_outcomes_for_template = []
        for co_num, co_desc in co_descriptions.items():
            if co_totals.get(co_num, 0) > 0:
                co_outcomes_for_template.append({
                    'number': co_num,
                    'description': co_desc,
                    'marks': co_totals.get(co_num)
                })

        # Prepare data for storage (avoid non-serializable types)
        stored_questions = []
        for q in final_paper_questions:
            stored_questions.append({
                'number': q.get('number'),
                'sub_questions': q.get('sub_questions', []),
                'total_marks': q.get('total_marks'),
                'main_co': list(q.get('main_co', [])),
                'main_rbt': list(q.get('main_rbt', []))
            })
        paper_data_for_db = dict(form_data)
        paper_data_for_db['paper_questions'] = stored_questions
        paper_data_for_db['co_outcomes'] = co_outcomes_for_template
        paper_data_for_db['rbt_totals'] = rbt_totals
        paper_data_for_db.pop('hod_sig_encoded', None)
        paper_data_for_db.pop('principal_sig_encoded', None)

        # Save paper to database
        paper_id = create_paper(
            teacher_id=user.get('id'),
            title=f"{form_data.get('course_code', '')} - {form_data.get('exam_title', '')}",
            course_code=form_data.get('course_code', ''),
            course_name=form_data.get('course_name', ''),
            department=user.get('department', 'Computer Science'),
            paper_data=paper_data_for_db,
            teacher_signature=teacher_sig_path,
            status='draft'
        )

        return render_template('paper.html', 
                             data=form_data, 
                             paper_questions=final_paper_questions, 
                             co_outcomes=co_outcomes_for_template, 
                             rbt_totals=rbt_totals,
                             paper_id=paper_id,
                             current_user=user,
                             show_send_to_hod=True,
                             show_my_papers=True,
                             show_navbar=False)

    except Exception as e:
        print(f"An error occurred: {e}")
        flash("An internal error occurred while generating the paper.", "error")
        return redirect(url_for('generate_form'))

# --- My Papers Route ---

# --- Parsing Functions ---

def parse_timetable_pdf(file_path, department, semester, section=None):
    """Parse timetable PDF using PyMuPDF table extraction."""
    try:
        doc = fitz.open(file_path)
        clear_timetable_entries(department, semester, section)
        
        parsed_count = 0
        seen_entries = set()
        details_table = []
        days_keywords = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
        
        for page in doc:
            # Use PyMuPDF's table finder for reliable extraction
            tables = page.find_tables()
            
            if not tables.tables:
                print(f"No tables found on page")
                continue
            
            print(f"Found {len(tables.tables)} tables")
            
            timetable_grid = None
            faculty_table = None
            
            # Identify tables by structure
            for tab in tables.tables:
                extracted = tab.extract()
                if not extracted:
                    continue
                
                first_row = extracted[0] if extracted else []
                first_col_values = [str(row[0]).upper() if row and row[0] else '' for row in extracted]
                
                # Check for semester info in the table content (usually first few rows)
                # Look for 'III/6', 'Sem 6', '6th Semester', '6A', etc.
                full_table_text = " ".join([str(cell).upper() for row in extracted[:5] for cell in row if cell])
                
                # Detect semester from text
                detected_sem = None
                if re.search(r'\b(III|3)/6', full_table_text) or re.search(r'\b6(TH|RD|ND|ST)?\s*SEM', full_table_text) or re.search(r'\bSEM(ESTER)?\s*:?\s*6', full_table_text):
                    detected_sem = '6'
                elif re.search(r'\b(II|2)/4', full_table_text) or re.search(r'\b4(TH|RD|ND|ST)?\s*SEM', full_table_text) or re.search(r'\bSEM(ESTER)?\s*:?\s*4', full_table_text):
                    detected_sem = '4'
                elif re.search(r'\b(I|1)/2', full_table_text) or re.search(r'\b2(ND|RD|TH|ST)?\s*SEM', full_table_text) or re.search(r'\bSEM(ESTER)?\s*:?\s*2', full_table_text):
                    detected_sem = '2'
                elif re.search(r'\b(IV|4)/8', full_table_text) or re.search(r'\b8(TH|RD|ND|ST)?\s*SEM', full_table_text) or re.search(r'\bSEM(ESTER)?\s*:?\s*8', full_table_text):
                    detected_sem = '8'

                detected_section = None
                section_match = re.search(rf'\b{re.escape(str(semester).strip())}\s*([A-Z])\b', full_table_text)
                if section_match:
                    detected_section = f"{str(semester).strip()}{section_match.group(1).upper()}"
                
                # Check if this is the timetable grid
                has_days = any(day in ' '.join(first_col_values) for day in days_keywords)
                
                if has_days and tab.col_count >= 8:
                    if detected_sem and str(detected_sem) != str(semester):
                        print(f"Skipping table for Sem {detected_sem} (requested Sem {semester})")
                        continue
                        
                    timetable_grid = extracted
                    print(f"Found timetable grid: {tab.row_count} rows x {tab.col_count} cols")
                
                # Check if this is the faculty/course details table
                has_course_code = any('CODE' in str(cell).upper() for cell in first_row)
                has_faculty = any('FACULTY' in str(cell).upper() for cell in first_row)
                
                if has_course_code or has_faculty:
                    if detected_sem and str(detected_sem) != str(semester):
                        return False, f"Semester Mismatch: PDF appears to be for Semester {detected_sem}, but you uploaded to Semester {semester}."
                    if detected_section and section and detected_section != section:
                        return False, f"Section Mismatch: PDF appears to be for Section {detected_section}, but you uploaded to Section {section}."
                        
                    faculty_table = extracted
                    print(f"Found faculty table: {tab.row_count} rows x {tab.col_count} cols")
            
            faculty_by_code = {}
            if faculty_table:
                header = faculty_table[0] if faculty_table else []
                code_idx = faculty_idx = name_idx = -1

                for i, cell in enumerate(header):
                    cell_upper = str(cell).upper() if cell else ''
                    if 'CODE' in cell_upper:
                        code_idx = i
                    elif 'FACULTY' in cell_upper:
                        faculty_idx = i
                    elif 'COURSE' in cell_upper and 'NAME' in cell_upper:
                        name_idx = i
                    elif 'NAME' in cell_upper and name_idx == -1:
                        name_idx = i

                for row in faculty_table[1:]:
                    if not row:
                        continue
                    first_cell = str(row[0]).strip() if row[0] else ''
                    if not first_cell or first_cell == '-' or 'THEORY' in first_cell.upper() or 'LAB' in first_cell.upper():
                        continue
                    code = str(row[code_idx]).strip() if code_idx >= 0 and code_idx < len(row) and row[code_idx] else ''
                    name = str(row[name_idx]).strip() if name_idx >= 0 and name_idx < len(row) and row[name_idx] else ''
                    faculty = str(row[faculty_idx]).strip() if faculty_idx >= 0 and faculty_idx < len(row) and row[faculty_idx] else ''
                    if not code and first_cell and re.match(r'^[A-Z]{2,4}\d{3,4}', first_cell):
                        code = first_cell
                    teacher_name = faculty or name
                    if code and teacher_name:
                        faculty_by_code[code.strip().upper()] = teacher_name.strip()

            # Parse timetable grid
            if timetable_grid:
                # Build time-slot mapping by column from header rows
                def _normalize_time_token(token):
                    t = str(token).strip()
                    t = re.sub(r'\s+', ' ', t)
                    t = re.sub(r'(?i)(\d)(am|pm)\b', r'\1 \2', t)
                    return t
                
                time_re = re.compile(r'\b\d{1,2}:\d{2}\s*(?:[AP]\.?M\.?)?\b', re.IGNORECASE)
                start_by_col = {}
                end_by_col = {}
                time_slot_by_col = {}
                
                header_rows = timetable_grid[:3]
                max_cols = max(len(r) for r in timetable_grid) if timetable_grid else 0
                
                for row in header_rows:
                    for col_idx, cell in enumerate(row):
                        if not cell:
                            continue
                        text = str(cell)
                        matches = time_re.findall(text)
                        if not matches:
                            continue
                        times = [_normalize_time_token(m) for m in matches]
                        
                        # If two times in same cell, treat as complete slot
                        if len(times) >= 2:
                            time_slot_by_col[col_idx] = f"{times[0]} to {times[1]}"
                            continue
                        
                        # If cell says "to" or "-", treat as start time
                        if re.search(r'\bto\b|-', text, re.IGNORECASE):
                            start_by_col.setdefault(col_idx, times[0])
                            continue
                        
                        # Otherwise infer end vs start from am/pm marker
                        if re.search(r'(?i)[ap]\.?m\.?', text):
                            end_by_col.setdefault(col_idx, times[0])
                        else:
                            start_by_col.setdefault(col_idx, times[0])
                
                for col_idx in range(max_cols):
                    if col_idx in time_slot_by_col:
                        continue
                    start = start_by_col.get(col_idx)
                    end = end_by_col.get(col_idx)
                    if start and end:
                        time_slot_by_col[col_idx] = f"{start} to {end}"
                    elif start:
                        time_slot_by_col[col_idx] = start
                    elif end:
                        time_slot_by_col[col_idx] = end

                def _normalize_noon_slot(slot_text):
                    text = str(slot_text or '')
                    text = re.sub(r'\b12:(\d{2})\s*AM\b', r'12:\1 PM', text, flags=re.IGNORECASE)
                    return text

                for col_idx, slot_text in list(time_slot_by_col.items()):
                    time_slot_by_col[col_idx] = _normalize_noon_slot(slot_text)
                
                if not time_slot_by_col:
                    # Fallback: sequential slots if no times found
                    for col_idx in range(1, max_cols):
                        time_slot_by_col[col_idx] = f"Slot {col_idx}"
                
                time_cols_sorted = sorted(time_slot_by_col.keys())
                first_time_col = min(time_cols_sorted) if time_cols_sorted else 1
                
                def _nearest_time_col(col_idx):
                    if col_idx in time_slot_by_col:
                        return col_idx
                    left = [c for c in time_cols_sorted if c < col_idx]
                    if left:
                        return left[-1]
                    right = [c for c in time_cols_sorted if c > col_idx]
                    if right:
                        return right[0]
                    return None
                
                print(f"Time slots found: {time_slot_by_col}")
                
                # Identify break/lunch columns from any row (PDF often stores them only once)
                break_text_by_col = {}
                for row in timetable_grid:
                    for col_idx, cell in enumerate(row):
                        if not cell:
                            continue
                        text = str(cell).strip().replace('\n', ' ')
                        if re.search(r'(BREAK|LUNCH)', text, re.IGNORECASE):
                            if col_idx < first_time_col:
                                continue
                            break_text_by_col[col_idx] = text

                # Parse each row with day names
                for row in timetable_grid:
                    if not row or not row[0]:
                        continue
                    
                    # Check if the row contains a day name in the first few columns.
                    day_name = None
                    day_col_idx = None
                    for idx, cell in enumerate(row[:4]):
                        cell_text = str(cell).strip().upper() if cell else ''
                        for day in days_keywords:
                            if day in cell_text:
                                day_name = day[:3].title()
                                day_col_idx = idx
                                break
                        if day_name:
                            break
                    
                    if not day_name or day_col_idx is None:
                        continue

                    start_col = day_col_idx + 1
                    if start_col < first_time_col:
                        start_col = first_time_col
                    
                    # Add breaks/lunch for every day using shared columns
                    for b_col, b_text in break_text_by_col.items():
                        nearest_col = _nearest_time_col(b_col)
                        if nearest_col is None:
                            continue
                        time_slot = time_slot_by_col.get(nearest_col)
                        if not time_slot:
                            continue
                        key = (day_name, time_slot, b_text)
                        if key not in seen_entries:
                            add_timetable_entry(department, semester, section, day_name, time_slot, b_text, "", "")
                            parsed_count += 1
                            seen_entries.add(key)
                    
                    # Extract subjects for each time slot
                    last_valid_content = None
                    last_valid_col = None
                    
                    for col_idx, cell in enumerate(row[start_col:], start=start_col):
                        cell_text = ""
                        if cell is not None:
                            cell_text = str(cell).strip().replace('\n', ' ')
                        
                        if col_idx not in time_slot_by_col:
                            # Allow break/lunch in non-time columns (map to nearest time)
                            if cell_text and re.search(r'(BREAK|LUNCH)', cell_text, re.IGNORECASE):
                                if col_idx < first_time_col:
                                    continue
                                nearest_col = _nearest_time_col(col_idx)
                                if nearest_col is not None:
                                    time_slot = time_slot_by_col.get(nearest_col)
                                    if time_slot:
                                        key = (day_name, time_slot, cell_text)
                                        if key not in seen_entries:
                                            add_timetable_entry(department, semester, section, day_name, time_slot, cell_text, "", "")
                                            parsed_count += 1
                                            seen_entries.add(key)
                            # Skip columns without time slots (breaks / gaps)
                            last_valid_content = None
                            last_valid_col = None
                            continue
                        
                        content = ""
                        
                        if cell is None:
                            # Handle merged cells only if adjacent time slot
                            if last_valid_content and last_valid_col == col_idx - 1:
                                content = last_valid_content
                                last_valid_col = col_idx
                        else:
                            content = cell_text
                            if content and content != '-':
                                last_valid_content = content
                                last_valid_col = col_idx
                            else:
                                last_valid_content = None
                                last_valid_col = None

                        if not content or content == '-':
                            continue
                        
                        # Skip break periods
                        if 'BREAK' in content.upper() or 'LUNCH' in content.upper():
                            time_slot = time_slot_by_col.get(col_idx)
                            if time_slot:
                                key = (day_name, time_slot, content)
                                if key not in seen_entries:
                                    add_timetable_entry(department, semester, section, day_name, time_slot, content, "", "")
                                    parsed_count += 1
                                    seen_entries.add(key)
                            last_valid_content = None
                            last_valid_col = None
                            continue
                        
                        # Get time slot using column mapping
                        time_slot = time_slot_by_col.get(col_idx)
                        if not time_slot:
                            continue
                        
                        # Extract subject code
                        subject_code = ""
                        code_match = re.match(r'^([A-Z]{2,4}\d{3,4}[A-Z]?)', content)
                        if code_match:
                            subject_code = code_match.group(1)
                        
                        if content and len(content) > 1:
                            teacher_name = faculty_by_code.get(subject_code.upper(), '') if subject_code else ''
                            key = (day_name, time_slot, content)
                            if key not in seen_entries:
                                add_timetable_entry(department, semester, section, day_name, time_slot, content, teacher_name, "")
                                parsed_count += 1
                                seen_entries.add(key)
            
            # Parse faculty details table
            if faculty_table:
                # Find column indices
                header = faculty_table[0] if faculty_table else []
                code_idx = faculty_idx = name_idx = desig_idx = hours_idx = -1
                
                for i, cell in enumerate(header):
                    cell_upper = str(cell).upper() if cell else ''
                    if 'CODE' in cell_upper:
                        code_idx = i
                    elif 'FACULTY' in cell_upper:
                        faculty_idx = i
                    elif 'COURSE' in cell_upper and 'NAME' in cell_upper:
                        name_idx = i
                    elif 'NAME' in cell_upper and name_idx == -1:
                        name_idx = i
                    elif 'DESIGNATION' in cell_upper or 'DESIG' in cell_upper:
                        desig_idx = i
                    elif 'HOUR' in cell_upper or 'WEEK' in cell_upper:
                        hours_idx = i
                    elif 'ACRONYM' in cell_upper:
                        pass  # Skip acronym column
                
                # Parse data rows
                for row in faculty_table[1:]:  # Skip header
                    if not row:
                        continue
                    
                    # Skip empty or header-like rows
                    first_cell = str(row[0]).strip() if row[0] else ''
                    if not first_cell or first_cell == '-' or 'THEORY' in first_cell.upper() or 'LAB' in first_cell.upper():
                        continue
                    
                    code = str(row[code_idx]).strip() if code_idx >= 0 and code_idx < len(row) and row[code_idx] else ""
                    name = str(row[name_idx]).strip() if name_idx >= 0 and name_idx < len(row) and row[name_idx] else ""
                    faculty = str(row[faculty_idx]).strip() if faculty_idx >= 0 and faculty_idx < len(row) and row[faculty_idx] else ""
                    designation = str(row[desig_idx]).strip() if desig_idx >= 0 and desig_idx < len(row) and row[desig_idx] else ""
                    credits = str(row[hours_idx]).strip() if hours_idx >= 0 and hours_idx < len(row) and row[hours_idx] else ""
                    
                    # Handle merged cells - if no code but has name, try first cell
                    if not code and first_cell and re.match(r'^[A-Z]{2,4}\d{3,4}', first_cell):
                        code = first_cell
                    
                    if code and (name or faculty):
                        details_table.append({
                            'code': code[:15],
                            'name': name[:50] if name else "",
                            'faculty': faculty[:40] if faculty else "",
                            'designation': designation[:10] if designation else "",
                            'credits': credits[:5] if credits else ""
                        })
        
        doc.close()
        
        # Store faculty details as JSON
        if details_table:
            full_details = json.dumps(details_table)
            update_timetable_details(department, semester, section, full_details)
            print(f"Stored {len(details_table)} faculty entries")
        else:
            update_timetable_details(department, semester, section, '[]')
        
        print(f"Timetable parsed: {parsed_count} entries")
        return True, f"Successfully parsed {parsed_count} entries."
        
    except Exception as e:
        print(f"Error parse_timetable_pdf: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)

# ...

def resolve_timetable_scope(user, department, semester, requested_section):
    """Resolve and validate timetable semester/section access for current user."""
    user_dept = (user or {}).get('department')
    role = (user or {}).get('role')
    req_section = (requested_section or '').strip().upper()
    sem = str(semester).strip()

    if user_dept and department != user_dept:
        return None, "Access denied for department."

    if role == 'student':
        user_sem = str((user or {}).get('semester') or '').strip()
        user_sec = str((user or {}).get('section') or '').strip().upper()
        if user_sem and sem != user_sem:
            return None, "Access denied for semester."
        return user_sec if user_sec else req_section, None

    if role in ['teacher', 'faculty']:
        teacher_subjects = get_teacher_subjects((user or {}).get('id')) or []
        allowed_semesters = {str(s.get('semester')) for s in teacher_subjects if s.get('semester')}
        if allowed_semesters and sem not in allowed_semesters:
            return None, "Access denied for semester."
        teacher_sections = get_teacher_sections((user or {}).get('id')) or []
        allowed_sections = [str(s.get('section') or '').strip().upper() for s in teacher_sections if str(s.get('semester')) == sem]
        if allowed_sections:
            if req_section and req_section not in allowed_sections:
                return None, "Access denied for section."
            return req_section if req_section else allowed_sections[0], None
        return req_section, None

    # HOD and others: allow requested scope
    return req_section, None

def _build_timetable_payload(department, semester, section):
    """Build standard timetable payload for API responses."""
    if not section:
        return {'success': True, 'entries': [], 'details': '', 'section': ''}

    entries = get_timetable_entries(department, semester, section)
    details = ""
    timetables = get_timetables(department)
    for tt in timetables:
        if str(tt.get('semester')) == str(semester) and str((tt.get('section') or '')).upper() == section:
            details = tt.get('details') or ""
            break
    return {'success': True, 'entries': entries, 'details': details, 'section': section}

@app.route('/api/timetable/<department>/<semester>')
@login_required
def get_timetable_data(department, semester):
    user = session.get('user') or {}
    requested_section = (request.args.get('section') or '').strip().upper()
    section, err = resolve_timetable_scope(user, department, semester, requested_section)
    if err:
        return jsonify({'success': False, 'message': err, 'entries': [], 'details': ''}), 403
    return jsonify(_build_timetable_payload(department, semester, section))

def parse_calendar_pdf(file_path, department, semester):
    """Parse calendar PDF using coordinate sorted blocks."""
    try:
        doc = fitz.open(file_path)
        clear_calendar_events(department, semester)
        parsed_count = 0
        seen_events = set()

        def _parse_date_token(token):
            ds = token.replace('-', '.').replace('/', '.')
            parts = ds.split('.')
            if len(parts) < 2:
                return None
            day = int(parts[0])
            month = int(parts[1])
            year = int(parts[2]) if len(parts) > 2 else datetime.now().year
            if year < 100:
                year += 2000
            return year, month, day

        def _event_type_from_line(line):
            text = line.lower()
            if '(h)' in text or 'holiday' in text:
                return 'holiday'
            if 'exam' in text or 'test' in text or re.search(r'\bia[- ]?\d', text):
                return 'exam'
            if 'ptm' in text or 'committee meeting' in text or 'ccm' in text or 'meeting' in text:
                return 'meeting'
            return 'event'

        for page in doc:
            # Use blocks with sort=True to get reading order top-down, left-right
            blocks = page.get_text("blocks", sort=True)

            for b in blocks:
                text = b[4]
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Regex for date range: DD.MM.YYYY to DD.MM.YYYY
                    range_match = re.search(
                        r'(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\s*(?:to|\u2013|-)\s*(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)',
                        line,
                        re.IGNORECASE
                    )
                    if range_match:
                        start_str = range_match.group(1)
                        end_str = range_match.group(2)
                        desc = line.replace(range_match.group(0), '').strip(' -\u2013:')
                        try:
                            start = _parse_date_token(start_str)
                            end = _parse_date_token(end_str)
                            if start and end:
                                sy, sm, sd = start
                                ey, em, ed = end
                                start_date = datetime(sy, sm, sd)
                                end_date = datetime(ey, em, ed)
                                event_type = _event_type_from_line(line)

                                if desc:
                                    cur = start_date
                                    while cur <= end_date:
                                        event_date = cur.strftime('%Y-%m-%d')
                                        key = (event_date, desc.strip().lower(), event_type)
                                        if key not in seen_events:
                                            create_event(desc, line, event_date, department=department, semester=semester, event_type=event_type)
                                            parsed_count += 1
                                            seen_events.add(key)
                                        cur = cur + timedelta(days=1)
                        except Exception:
                            continue
                        continue

                    # Regex for single date: DD.MM.YYYY or DD.MM
                    match = re.search(r'(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)', line)
                    if match:
                        date_str = match.group(1)
                        # Ensure date is at start or isolated, not inside a phone number
                        if len(date_str) < 12:
                            desc = line.replace(date_str, '').strip(' -\u2013:')

                            try:
                                parsed = _parse_date_token(date_str)
                                if not parsed:
                                    continue
                                year, month, day = parsed
                                event_date = f"{year}-{month:02d}-{day:02d}"

                                event_type = _event_type_from_line(line)

                                if desc:  # Only add if description exists
                                    key = (event_date, desc.strip().lower(), event_type)
                                    if key not in seen_events:
                                        create_event(desc, line, event_date, department=department, semester=semester, event_type=event_type)
                                        parsed_count += 1
                                        seen_events.add(key)
                            except Exception:
                                continue

        print(f"Calendar parsed: {parsed_count} events")
        return True
    except Exception as e:
        print(f"Error parsing calendar: {e}")
        return False

def _parse_roll_numbers(prefix, raw, pad_len=None):
    """Parse roll numbers from a comma/range string and apply prefix/padding."""
    if not raw:
        return []
    tokens = re.split(r'[,\n]+', raw)
    numbers = []
    extras = []
    for token in tokens:
        t = token.strip()
        if not t:
            continue
        if re.search(r'[A-Za-z]', t):
            extras.append(t)
            continue
        if '-' in t:
            parts = t.split('-', 1)
            try:
                start = int(parts[0].strip())
                end = int(parts[1].strip())
                step = 1 if start <= end else -1
                for n in range(start, end + step, step):
                    numbers.append(n)
            except Exception:
                extras.append(t)
        else:
            try:
                numbers.append(int(t))
            except Exception:
                extras.append(t)

    if pad_len is None:
        pad_len = max([len(str(n)) for n in numbers], default=3)
    try:
        pad_len = int(pad_len)
    except Exception:
        pad_len = 3

    rolls = []
    for n in numbers:
        num_str = f"{n:0{pad_len}d}" if pad_len > 0 else str(n)
        rolls.append(f"{prefix}{num_str}" if prefix else num_str)
    rolls.extend(extras)
    return rolls

def _allocate_benches(rooms, groups, seats_per_bench=3):
    """Allocate student roll numbers column-wise with adjacency constraints."""
    from collections import deque

    queues = {g['name']: deque(g['rolls']) for g in groups}
    sem_by_group = {g['name']: g.get('semester') for g in groups}
    branch_by_group = {g['name']: str(g.get('branch') or '').strip().upper() for g in groups}
    section_by_group = {g['name']: str(g.get('section') or '').strip().upper() for g in groups}
    remaining = {g['name']: len(g['rolls']) for g in groups}

    def active_semesters():
        return {sem_by_group.get(g) for g, cnt in remaining.items() if cnt > 0 and sem_by_group.get(g)}

    def group_identity(group_name):
        return (branch_by_group.get(group_name, ''), section_by_group.get(group_name, ''))

    def pick_group(forbidden_sems, forbidden_keys):
        # Prefer a different semester whenever 2+ semesters are still available.
        active_sems = active_semesters()
        strict_alternate = len(active_sems) > 1

        candidates = [
            g for g, cnt in remaining.items()
            if cnt > 0
            and sem_by_group.get(g) not in forbidden_sems
            and group_identity(g) not in forbidden_keys
        ]

        if strict_alternate and candidates:
            # Pick semester with highest remaining load first for better balancing.
            sem_remaining = {}
            for g in candidates:
                sem = sem_by_group.get(g)
                sem_remaining[sem] = sem_remaining.get(sem, 0) + remaining[g]
            best_sem = max(sem_remaining, key=sem_remaining.get)
            sem_candidates = [g for g in candidates if sem_by_group.get(g) == best_sem]
            return max(sem_candidates, key=lambda g: remaining[g])

        if candidates:
            return max(candidates, key=lambda g: remaining[g])

        # If all candidates violate adjacency, only then relax constraint.
        fallback = [g for g, cnt in remaining.items() if cnt > 0]
        if not fallback:
            return None
        return max(fallback, key=lambda g: remaining[g])

    room_layouts = []
    for room in rooms:
        rows = int(room.get('rows') or 0)
        cols = int(room.get('cols') or 0)
        layout = [[[None for _ in range(seats_per_bench)] for _ in range(cols)] for _ in range(rows)]

        # Column-wise fill: top-to-bottom per column, then move to next column.
        for c in range(cols):
            for r in range(rows):
                bench_seats = []
                for s in range(seats_per_bench):
                    forbidden_sems = set()
                    forbidden_keys = set()

                    # Prevent adjacent same-sem in the same bench.
                    if s > 0 and bench_seats[s - 1]:
                        forbidden_sems.add(bench_seats[s - 1]['semester'])
                        forbidden_keys.add(group_identity(bench_seats[s - 1]['group']))

                    # Prevent same-sem with left bench edge and bench directly above.
                    if c > 0:
                        left_bench = layout[r][c - 1]
                        left_edge = next((x for x in reversed(left_bench) if x), None)
                        if left_edge and left_edge.get('semester'):
                            forbidden_sems.add(left_edge['semester'])
                            forbidden_keys.add(group_identity(left_edge['group']))
                    if r > 0:
                        up_bench = layout[r - 1][c]
                        up_same_seat = up_bench[s] if s < len(up_bench) else None
                        if up_same_seat and up_same_seat.get('semester'):
                            forbidden_sems.add(up_same_seat['semester'])
                            forbidden_keys.add(group_identity(up_same_seat['group']))

                    group = pick_group(forbidden_sems, forbidden_keys)
                    if not group:
                        bench_seats.append(None)
                        continue

                    roll = queues[group].popleft()
                    remaining[group] -= 1
                    bench_seats.append({
                        'group': group,
                        'semester': sem_by_group.get(group),
                        'roll': roll
                    })

                layout[r][c] = bench_seats

        room_layouts.append({
            'room': room.get('room'),
            'rows': rows,
            'cols': cols,
            'layout': layout
        })
    return room_layouts

# --- HOD Upload Routes ---


@app.route('/hod/upload-timetable', methods=['POST'])
@login_required
@hod_required
def upload_timetable():
    if 'timetable_pdf' not in request.files:
        flash("No file selected", "error")
        return redirect(url_for('hod_dashboard'))

    file = request.files['timetable_pdf']
    if file.filename == '':
        flash("No file selected", "error")
        return redirect(url_for('hod_dashboard'))

    if file and allowed_file(file.filename):
        department = request.form.get('department')
        semester = request.form.get('semester', 'General')
        section = (request.form.get('section') or '').strip().upper()
        if not section:
            flash("Please select a section for timetable upload.", "error")
            return redirect(url_for('hod_dashboard'))
        valid_section = any(
            str(s.get('semester')) == str(semester) and str(s.get('section')).upper() == section
            for s in (get_section_catalog(department) or [])
        )
        if not valid_section:
            flash("Invalid section for selected semester.", "error")
            return redirect(url_for('hod_dashboard'))

        import tempfile
        filename = secure_filename(file.filename)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', dir=tempfile.gettempdir())
        file.save(tmp.name)
        tmp.close()
        tmp_path = tmp.name

        try:
            # Parse first (so user gets immediate feedback if it fails)
            success, msg = parse_timetable_pdf(tmp_path, department, semester, section)

            # Store locally
            with open(tmp_path, 'rb') as f:
                save_name = f"{department}_{semester}_{section}_{int(datetime.now().timestamp())}_{filename}"
                file_url = cloud_storage.upload_bytes(f.read(), filename=save_name, subfolder='timetables', resource_type='auto')
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        create_timetable(department, semester, section, f"Timetable {semester}-{section}", file_url or filename, filename)

        if success:
            flash(msg, "success")
        else:
            flash(f"Timetable uploaded but parsing failed: {msg}", "warning")

    return redirect(url_for('hod_dashboard'))

@app.route('/hod/upload-calendar', methods=['POST'])
@login_required
@hod_required
def upload_calendar():
    if 'calendar_pdf' not in request.files:
        flash("No file selected", "error")
        return redirect(url_for('hod_dashboard'))

    file = request.files['calendar_pdf']
    if file and allowed_file(file.filename):
        department = request.form.get('department')
        semester = (request.form.get('semester') or '').strip()
        if not semester:
            flash("Please select a semester for calendar upload.", "error")
            return redirect(url_for('hod_dashboard'))

        import tempfile
        filename = secure_filename(file.filename)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', dir=tempfile.gettempdir())
        file.save(tmp.name)
        tmp.close()
        tmp_path = tmp.name

        try:
            result = parse_calendar_pdf(tmp_path, department, semester)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if result:
            flash(f"Calendar of Events for Semester {semester} uploaded and parsed!", "success")
        else:
            flash("Calendar uploaded but parsing failed.", "warning")

    return redirect(url_for('hod_dashboard'))

@app.route('/hod/clear-calendar', methods=['POST'])
@login_required
@hod_required
def clear_calendar():
    department = request.form.get('department')
    semester = (request.form.get('semester') or '').strip()
    if not semester:
        flash("Please select a semester to clear calendar events.", "error")
        return redirect(url_for('hod_dashboard'))
    clear_calendar_events(department, semester)
    flash(f"Calendar events cleared for Semester {semester}.", "success")
    return redirect(url_for('hod_dashboard'))

@app.route('/hod/bench-allotment', methods=['GET', 'POST'])
@login_required
@hod_required
def bench_allotment():
    user = session.get('user') or {}
    if request.method == 'GET':
        rooms = [
            {'room': '203', 'rows': 5, 'cols': 4},
        ]
        groups = [
            {'name': 'Sem 6 - CS - A', 'semester': '6', 'branch': 'CS', 'section': 'A', 'prefix': '1GD23CS', 'rolls_raw': '001-060', 'pad_len': '3'},
            {'name': 'Sem 6 - CS - B', 'semester': '6', 'branch': 'CS', 'section': 'B', 'prefix': '1GD23CS', 'rolls_raw': '001-045', 'pad_len': '3'}
        ]
        return render_template(
            'bench_allotment.html',
            user=user,
            rooms=rooms,
            groups=groups,
            seats_per_bench=3,
            result=None
        )

    # POST
    seats_per_bench = int(request.form.get('seats_per_bench') or 3)
    room_names = request.form.getlist('room_name[]')
    room_rows = request.form.getlist('room_rows[]')
    room_cols = request.form.getlist('room_cols[]')
    rooms = []
    for idx, name in enumerate(room_names):
        name = (name or '').strip()
        if not name:
            continue
        rooms.append({
            'room': name,
            'rows': int(room_rows[idx] or 0),
            'cols': int(room_cols[idx] or 0)
        })

    group_names = request.form.getlist('group_name[]')
    group_semesters = request.form.getlist('group_semester[]')
    group_branches = request.form.getlist('group_branch[]')
    group_sections = request.form.getlist('group_section[]')
    group_prefixes = request.form.getlist('group_prefix[]')
    group_rolls = request.form.getlist('group_rolls[]')
    group_pad = request.form.getlist('group_pad[]')

    groups = []
    for idx, name in enumerate(group_names):
        label = (name or '').strip() or f"Group {idx + 1}"
        sem = (group_semesters[idx] or '').strip()
        prefix = (group_prefixes[idx] or '').strip()
        rolls_raw = group_rolls[idx] if idx < len(group_rolls) else ''
        pad_len = group_pad[idx] if idx < len(group_pad) else ''
        rolls = _parse_roll_numbers(prefix, rolls_raw, pad_len)
        if not rolls:
            continue
        groups.append({
            'name': label,
            'semester': sem,
            'branch': (group_branches[idx] or '').strip().upper(),
            'section': (group_sections[idx] or '').strip().upper(),
            'prefix': prefix,
            'rolls_raw': rolls_raw,
            'pad_len': pad_len,
            'rolls': rolls
        })

    if not rooms:
        flash("Add at least one classroom to generate blueprint.", "error")
        return render_template(
            'bench_allotment.html',
            user=user,
            rooms=[{'room': '203', 'rows': 5, 'cols': 4}],
            groups=groups if groups else [{'name': 'Sem 6 - CS', 'semester': '6', 'branch': 'CS', 'section': 'A', 'prefix': '1GD23CS', 'rolls_raw': '', 'pad_len': '3'}],
            seats_per_bench=seats_per_bench,
            result=None
        )
    if not groups:
        flash("Add at least one student group with roll numbers.", "error")
        return render_template(
            'bench_allotment.html',
            user=user,
            rooms=rooms,
            groups=[{'name': 'Sem 6 - CS', 'semester': '6', 'branch': 'CS', 'section': 'A', 'prefix': '1GD23CS', 'rolls_raw': '', 'pad_len': '3'}],
            seats_per_bench=seats_per_bench,
            result=None
        )

    room_layouts = _allocate_benches(rooms, groups, seats_per_bench)

    summary = {}
    for room in room_layouts:
        room_key = room['room']
        summary[room_key] = {}
        rows = room.get('rows') or 0
        cols = room.get('cols') or 0
        for c in range(cols):
            for r in range(rows):
                bench = room['layout'][r][c]
                for seat in bench:
                    if not seat:
                        continue
                    g = seat['group']
                    summary[room_key].setdefault(g, [])
                    summary[room_key][g].append(seat['roll'])

    group_totals = {g['name']: len(g['rolls']) for g in groups}
    assigned_counts = {k: 0 for k in group_totals}
    for room in room_layouts:
        for row in room['layout']:
            for bench in row:
                for seat in bench:
                    if seat and seat['group'] in assigned_counts:
                        assigned_counts[seat['group']] += 1

    unallocated = []
    for g in groups:
        cnt = assigned_counts.get(g['name'], 0)
        remaining = g['rolls'][cnt:] if cnt < len(g['rolls']) else []
        if remaining:
            unallocated.append({
                'group': g['name'],
                'semester': g.get('semester'),
                'remaining': remaining
            })

    total_capacity = sum((int(r.get('rows', 0)) * int(r.get('cols', 0)) * seats_per_bench) for r in rooms)
    total_students = sum(group_totals.values())
    total_assigned = sum(assigned_counts.values())

    result = {
        'layouts': room_layouts,
        'summary': summary,
        'seats_per_bench': seats_per_bench,
        'capacity': total_capacity,
        'students': total_students,
        'assigned': total_assigned,
        'unallocated': unallocated
    }

    return render_template(
        'bench_allotment.html',
        user=user,
        rooms=rooms,
        groups=groups,
        seats_per_bench=seats_per_bench,
        result=result
    )

# --- API Routes for Display ---

@app.route('/api/calendar-events')
@login_required
def get_calendar_events():
    user = session.get('user') or {}
    dept = user.get('department')
    role = user.get('role')
    requested_sem = (request.args.get('semester') or '').strip()

    sem = None
    if role == 'student':
        sem = str(user.get('semester') or '').strip() or None
    elif role in ['teacher', 'faculty']:
        allowed = sorted({str(s.get('semester')) for s in get_teacher_subjects(user.get('id')) if s.get('semester')})
        if requested_sem and requested_sem in allowed:
            sem = requested_sem
        elif allowed:
            sem = allowed[0]
    elif role == 'hod':
        sem = requested_sem or None

    events = get_all_events(dept, sem)
    return jsonify({'success': True, 'events': events})

# --- My Resources Route ---

@app.route('/my-resources')
@login_required
@academic_staff_required
def my_resources():
    user = (session.get('user') or {})
    notes = get_notes_by_teacher(user.get('id'))
    question_banks = get_question_banks_by_teacher(user.get('id'))
    
    return render_template('my_resources.html',
                         notes=notes,
                         question_banks=question_banks,
                         current_user=user,
                         show_navbar=True)

@app.route('/my-papers')
@login_required
@teacher_required
def my_papers():
    user = (session.get('user') or {})
    papers = get_papers_by_teacher(user.get('id'))
    return render_template('my_papers.html',
                         papers=papers,
                         current_user=user,
                         show_navbar=True)

@app.route('/hod/my-papers')
@login_required
@hod_required
def hod_my_papers():
    user = (session.get('user') or {})
    papers = get_papers_by_teacher(user.get('id'))
    return render_template('my_papers.html',
                         papers=papers,
                         current_user=user,
                         show_navbar=True)

# ── NEW: Teacher Examination Duty Allotment ──────────────────────────────────
@app.route('/hod/teacher-duty')
@login_required
@hod_required
def hod_teacher_duty():
    user = session.get('user') or {}
    return render_template('hod_teacher_duty.html',
                           user=user,
                           current_user=user,
                           show_navbar=True)

# ── NEW: Student Smart Bench Allotment ───────────────────────────────────────
@app.route('/hod/smart-bench')
@login_required
@hod_required
def hod_smart_bench():
    user = session.get('user') or {}
    return render_template('hod_smart_bench.html',
                           user=user,
                           current_user=user,
                           show_navbar=True)

if __name__ == '__main__':
    app.run(debug=True, port=8080)
