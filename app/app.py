import os
import psycopg2
import psycopg2.extras
import json
import pandas as pd
from datetime import datetime, timedelta
import secrets
import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from .models import db, User, Exam, Question, ExamSubmission, StudentAnswer, PasswordResetToken
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_migrate import Migrate
from sqlalchemy import or_
from fpdf import FPDF
import xlsxwriter
from io import BytesIO
import click
import random
import requests
from google.oauth2 import credentials
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from cachecontrol import CacheControl

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key')
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    raise ValueError("FATAL: DATABASE_URL environment variable is not set.")
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'app/static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) # Create upload folder if it doesn't exist
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) # Session timeout

db.init_app(app)
migrate = Migrate(app, db)

# Mail configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

# Google OAuth Configuration
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET')
app.config['REDIRECT_URI'] = '/google/callback'

# Allow insecure transport for development only.
if os.environ.get('FLASK_DEBUG') == '1':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'student_login'

def get_wat_now():
    """Returns the current time in WAT (UTC+1) as a timezone-aware datetime object."""
    utc_now = pytz.utc.localize(datetime.utcnow())
    wat = pytz.timezone('Africa/Lagos')
    return utc_now.astimezone(wat)

def from_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value
app.jinja_env.filters['fromjson'] = from_json

@app.template_filter('strftime_wat')
def _jinja2_filter_datetime(date, fmt=None):
    if fmt is None:
        fmt = '%B %d, %Y at %I:%M %p' # e.g., November 04, 2025 at 03:45 PM

    wat_tz = pytz.timezone('Africa/Lagos')

    if date.tzinfo is None:
        # If the date is naive, assume it is in WAT
        date = wat_tz.localize(date)
    else:
        # If it is aware, convert it to WAT
        date = date.astimezone(wat_tz)

    return date.strftime(fmt)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def before_request():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=30)
    session.modified = True

@app.cli.command('create-admin')
@click.argument('name')
@click.argument('email')
@click.argument('password')
def create_admin_command(name, email, password):
    """Creates a new admin user."""
    if User.query.filter_by(email=email).first():
        print(f'Error: Admin user with email {email} already exists.')
        return

    password_hash = generate_password_hash(password)
    new_admin = User(
        fullname=name,
        email=email,
        password_hash=password_hash,
        role='admin',
        status='approved'
    )
    db.session.add(new_admin)
    db.session.commit()
    print(f'Admin user {name} created successfully.')

@app.route('/')
def index():
    return render_template('index.html')

def send_email(subject, recipients, body):
    msg = Message(subject, recipients=recipients)
    msg.body = body
    try:
        mail.send(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

# Teacher routes
@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, role='teacher', status='approved').first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid email or password, or account not approved.')

    return render_template('teacher_login.html')

@app.route('/teacher/register', methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        gender = request.form['gender']

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
        else:
            password_hash = generate_password_hash(password)
            new_teacher = User(
                fullname=fullname,
                email=email,
                password_hash=password_hash,
                role='teacher',
                gender=gender,
                status='pending'
            )
            db.session.add(new_teacher)
            db.session.commit()
            flash('Registration successful. Please wait for admin approval.')
            return redirect(url_for('teacher_login'))

    return render_template('teacher_register.html')

@app.route('/teacher/documentation')
@login_required
def teacher_documentation():
    return render_template('teacher_documentation.html')

@app.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    now = get_wat_now()

    exams_data = db.session.query(
        Exam,
        db.func.count(ExamSubmission.id).label('submission_count')
    ).outerjoin(ExamSubmission, Exam.id == ExamSubmission.exam_id)\
    .filter(Exam.teacher_id == current_user.id)\
    .group_by(Exam.id)\
    .order_by(Exam.created_at.desc())\
    .all()

    exams = []
    for exam, submission_count in exams_data:
        is_active = False
        if exam.start_time:
            if exam.end_time:
                is_active = exam.start_time <= now <= exam.end_time
            else:
                is_active = exam.start_time <= now

        total_students_in_class = User.query.filter_by(role='student', class_=exam.class_).count()
        completion_rate = (submission_count / total_students_in_class) * 100 if total_students_in_class > 0 else 0

        exams.append({
            'id': exam.id,
            'title': exam.title,
            'class': exam.class_,
            'duration': exam.duration,
            'start_time': exam.start_time,
            'end_time': exam.end_time,
            'delay_results': exam.delay_results,
            'submission_count': submission_count,
            'is_active': is_active,
            'completion_rate': completion_rate
        })

    # --- DYNAMIC ACTIVITY FEED LOGIC ---
    activities = []
    wat_tz = pytz.timezone('Africa/Lagos')

    # 1. Fetch recent exam creations
    recent_exams = Exam.query.filter_by(teacher_id=current_user.id).order_by(Exam.created_at.desc()).limit(5).all()
    for exam in recent_exams:
        # Ensure datetime is timezone-aware before appending
        aware_time = exam.created_at.astimezone(wat_tz) if exam.created_at.tzinfo else wat_tz.localize(exam.created_at)
        activities.append({
            'type': 'exam_created',
            'title': f"New exam created: {exam.title}",
            'time': aware_time,
            'icon': '📝'
        })

    # 2. Fetch recent student submissions for this teacher's exams
    recent_submissions = db.session.query(
        User.fullname,
        Exam.title,
        ExamSubmission.end_time
    ).join(User, ExamSubmission.student_id == User.id)\
    .join(Exam, ExamSubmission.exam_id == Exam.id)\
    .filter(Exam.teacher_id == current_user.id, ExamSubmission.status == 'submitted')\
    .order_by(ExamSubmission.end_time.desc())\
    .limit(5).all()

    for fullname, title, end_time in recent_submissions:
        if end_time:
            # Ensure datetime is timezone-aware before appending
            aware_time = end_time.astimezone(wat_tz) if end_time.tzinfo else wat_tz.localize(end_time)
            activities.append({
                'type': 'submission',
                'title': f"{fullname} completed the exam: {title}",
                'time': aware_time,
                'icon': '📊'
            })

    # 3. Fetch new student registrations in the teacher's classes.
    teacher_classes = [c[0] for c in db.session.query(Exam.class_).filter_by(teacher_id=current_user.id).distinct().all()]
    if teacher_classes:
        new_students = User.query.filter(User.role == 'student', User.class_.in_(teacher_classes)).order_by(User.created_at.desc()).limit(5).all()
        for student in new_students:
            # Ensure datetime is timezone-aware before appending
            aware_time = student.created_at.astimezone(wat_tz) if student.created_at.tzinfo else wat_tz.localize(student.created_at)
            activities.append({
                'type': 'new_student',
                'title': f"New student registered: {student.fullname}",
                'time': aware_time,
                'icon': '👤'
            })

    # Sort all activities by time (now that they are all timezone-aware)
    activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = activities[:5]
    # --- END ACTIVITY FEED LOGIC ---

    return render_template('teacher_dashboard.html', exams=exams, activities=recent_activities)

@app.route('/teacher/exam/create', methods=['GET', 'POST'])
@login_required
def create_exam():
    if request.method == 'POST':
        title = request.form['title']
        exam_class = request.form['class_']
        duration = request.form['duration']
        description = request.form['description']
        start_time_str = request.form.get('start_time') or None
        end_time_str = request.form.get('end_time') or None
        randomize_questions = 'randomize_questions' in request.form
        delay_results = 'delay_results' in request.form

        wat_tz = pytz.timezone('Africa/Lagos')
        date_format = '%Y-%m-%dT%H:%M'
        start_time = wat_tz.localize(datetime.strptime(start_time_str, date_format)) if start_time_str else None
        end_time = wat_tz.localize(datetime.strptime(end_time_str, date_format)) if end_time_str else None

        new_exam = Exam(
            title=title,
            class_=exam_class,
            duration=duration,
            description=description,
            teacher_id=current_user.id,
            start_time=start_time,
            end_time=end_time,
            randomize_questions=randomize_questions,
            delay_results=delay_results
        )
        db.session.add(new_exam)
        db.session.commit()

        flash('Exam created successfully. Now add questions.')
        return redirect(url_for('manage_exam', exam_id=new_exam.id))

    now_wat = get_wat_now().strftime('%Y-%m-%d %H:%M:%S')
    return render_template('create_exam.html', current_time=now_wat)


@app.route('/teacher/exam/edit/<int:exam_id>', methods=['GET', 'POST'])
@login_required
def edit_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id, teacher_id=current_user.id).first_or_404()

    if request.method == 'POST':
        exam.title = request.form['title']
        exam.class_ = request.form['class_']
        exam.duration = request.form['duration']
        exam.description = request.form['description']
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')

        wat_tz = pytz.timezone('Africa/Lagos')
        date_format = '%Y-%m-%dT%H:%M'
        if start_time_str:
            exam.start_time = wat_tz.localize(datetime.strptime(start_time_str, date_format))
        else:
            exam.start_time = None

        if end_time_str:
            exam.end_time = wat_tz.localize(datetime.strptime(end_time_str, date_format))
        else:
            exam.end_time = None

        exam.randomize_questions = 'randomize_questions' in request.form
        exam.delay_results = 'delay_results' in request.form

        db.session.commit()
        flash('Exam updated successfully.')
        return redirect(url_for('teacher_dashboard'))

    return render_template('edit_exam.html', exam=exam)


@app.route('/teacher/exam/<int:exam_id>/manage')
@login_required
def manage_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id, teacher_id=current_user.id).first_or_404()
    questions = Question.query.filter_by(exam_id=exam_id).order_by(Question.id).all()
    return render_template('manage_exam.html', exam=exam, questions=questions)

@app.route('/teacher/exam/<int:exam_id>/add_question', methods=['GET', 'POST'])
@login_required
def add_question(exam_id):
    if request.method == 'POST':
        question_text = request.form['question_text']
        question_type = request.form['question_type']

        options = None
        correct_answer = ''
        question_image = None

        if 'question_image' in request.files:
            file = request.files['question_image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                question_image = filename

        if question_type in ['single-choice', 'multiple-choice']:
            form_options = [request.form[key] for key in request.form if key.startswith('option_')]
            correct_indices = request.form.getlist('correct_option')

            options_data = [{'text': text, 'correct': str(i) in correct_indices} for i, text in enumerate(form_options)]
            options = json.dumps(options_data)
            correct_answer = json.dumps(correct_indices)

        else:
            correct_answer = request.form['correct_answer']

        new_question = Question(
            exam_id=exam_id,
            question_text=question_text,
            question_image=question_image,
            question_type=question_type,
            options=options,
            correct_answer=correct_answer
        )
        db.session.add(new_question)
        db.session.commit()

        flash('Question added successfully.')
        return redirect(url_for('manage_exam', exam_id=exam_id))

    exam = Exam.query.get_or_404(exam_id)
    return render_template('add_question.html', exam=exam)

@app.route('/teacher/exam/delete/<int:exam_id>')
@login_required
def delete_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id, teacher_id=current_user.id).first()
    if exam:
        db.session.delete(exam)
        db.session.commit()
        flash('Exam deleted.')
    else:
        flash('Exam not found or you do not have permission to delete it.')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/exam/<int:exam_id>/release_results', methods=['POST'])
@login_required
def release_exam_results(exam_id):
    exam = Exam.query.filter_by(id=exam_id, teacher_id=current_user.id).first()
    if exam:
        exam.delay_results = False
        db.session.commit()
        flash('Results released successfully.')
    else:
        flash('Exam not found or you do not have permission to release results.')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/question/delete/<int:question_id>')
@login_required
def delete_question(question_id):
    question = Question.query.get(question_id)
    if question and question.exam.teacher_id == current_user.id:
        exam_id = question.exam_id
        db.session.delete(question)
        db.session.commit()
        flash('Question deleted.')
        return redirect(url_for('manage_exam', exam_id=exam_id))

    flash('Permission denied.')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/exam/<int:exam_id>/upload_questions', methods=['POST'])
@login_required
def upload_questions(exam_id):
    file = request.files['file']
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        if filename.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)

        for index, row in df.iterrows():
            question_text = row['question_text']
            question_type = row['question_type']
            options = None
            correct_answer = ''

            if question_type in ['single-choice', 'multiple-choice']:
                opts = []
                for i in range(1, 5):
                    if f'option{i}' in row and pd.notna(row[f'option{i}']):
                        opts.append(row[f'option{i}'])

                options_data = [{'text': text, 'correct': str(i+1) in str(row['correct_answer']).split(',')} for i, text in enumerate(opts)]
                options = options_data
                correct_answer = str(row['correct_answer']).split(',')
            else:
                correct_answer = row['correct_answer']

            new_question = Question(
                exam_id=exam_id,
                question_text=question_text,
                question_type=question_type,
                options=options,
                correct_answer=correct_answer
            )
            db.session.add(new_question)

        db.session.commit()
        flash('Questions uploaded successfully.')

    return redirect(url_for('manage_exam', exam_id=exam_id))

@app.route('/teacher/question/edit/<int:question_id>', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)

    if request.method == 'POST':
        question.question_text = request.form['question_text']

        if 'question_image' in request.files:
            file = request.files['question_image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                question.question_image = filename

        if question.question_type in ['single-choice', 'multiple-choice']:
            form_options = [request.form[key] for key in sorted(request.form.keys()) if key.startswith('option_')]
            correct_indices = request.form.getlist('correct_option')

            options_data = [{'text': text, 'correct': str(i) in correct_indices} for i, text in enumerate(form_options)]
            question.options = options_data
            question.correct_answer = correct_indices
        else:
            question.correct_answer = request.form['correct_answer']

        db.session.commit()
        flash('Question updated successfully.')
        return redirect(url_for('manage_exam', exam_id=question.exam_id))

    return render_template('edit_question.html', question=question)

def calculate_score(submission_id):
    submission = ExamSubmission.query.get(submission_id)
    if not submission:
        return

    total_objective_questions = Question.query.filter(
        Question.exam_id == submission.exam_id,
        Question.question_type.in_(['single-choice', 'multiple-choice'])
    ).count()

    score = 0
    answers = StudentAnswer.query.filter_by(submission_id=submission_id).all()

    for answer in answers:
        question = Question.query.get(answer.question_id)
        if question.question_type in ['single-choice', 'multiple-choice']:
            student_answer_indices = set(answer.answer_text.split(','))
            correct_answer_indices = set(question.correct_answer)
            if student_answer_indices == correct_answer_indices:
                score += 1

    final_score = (score / total_objective_questions) * 100 if total_objective_questions > 0 else 0
    submission.score = final_score
    db.session.commit()

@app.route('/student/exam/submit', methods=['POST'])
@login_required
def submit_exam_route():
    data = request.json
    submission_id = data['submission_id']

    submission = ExamSubmission.query.get(submission_id)
    if submission:
        submission.status = 'submitted'
        submission.end_time = get_wat_now()
        db.session.commit()
        calculate_score(submission_id)
        flash('Exam submitted successfully!')
        return jsonify({'status': 'success'})

    return jsonify({'status': 'error', 'message': 'Submission not found'}), 404

@app.route('/student/results/<int:submission_id>')
@login_required
def view_results(submission_id):
    submission = ExamSubmission.query.filter_by(id=submission_id, student_id=current_user.id).first_or_404()
    exam = submission.exam
    all_questions = exam.questions
    total_questions = len(all_questions)

    answers_query = db.session.query(
        Question,
        StudentAnswer.answer_text
    ).outerjoin(StudentAnswer, (StudentAnswer.question_id == Question.id) & (StudentAnswer.submission_id == submission_id))\
    .filter(Question.exam_id == exam.id).all()

    results = []
    answered_questions = 0
    correct_answers = 0

    for question, answer_text in answers_query:
        is_correct = False
        if answer_text is not None:
            answered_questions += 1
            if question.question_type in ['single-choice', 'multiple-choice']:
                student_ans = set(answer_text.split(','))
                correct_ans = set(question.correct_answer)
                if student_ans == correct_ans:
                    is_correct = True
            else:
                if answer_text.lower() == question.correct_answer.lower():
                    is_correct = True

        if is_correct:
            correct_answers += 1

        results.append({
            'question': question,
            'student_answer': {'answer_text': answer_text},
            'is_correct': is_correct
        })

    incorrect_answers = answered_questions - correct_answers
    time_taken = submission.end_time - submission.start_time if submission.end_time and submission.start_time else None

    return render_template('view_results.html', exam=exam, submission=submission, results=results,
                           total_questions=total_questions, answered_questions=answered_questions,
                           correct_answers=correct_answers, incorrect_answers=incorrect_answers,
                           time_taken=time_taken)

def get_exam_analytics(exam_id):
    all_questions = Question.query.filter_by(exam_id=exam_id).all()
    total_questions = len(all_questions)

    submissions_query = ExamSubmission.query.filter_by(exam_id=exam_id, status='submitted').all()

    submissions = []
    for sub in submissions_query:
        answered_questions = len(sub.answers)
        correct_answers = 0
        for ans in sub.answers:
            question = Question.query.get(ans.question_id)
            if question:
                if question.question_type in ['single-choice', 'multiple-choice']:
                    student_ans = set(ans.answer_text.split(','))
                    correct_ans = set(question.correct_answer)
                    if student_ans == correct_ans:
                        correct_answers += 1
                else:
                    if ans.answer_text.lower() == question.correct_answer.lower():
                        correct_answers += 1

        time_taken = sub.end_time - sub.start_time if sub.end_time and sub.start_time else None

        submissions.append({
            'fullname': sub.student.fullname,
            'score': sub.score,
            'total_questions': total_questions,
            'answered_questions': answered_questions,
            'unanswered_questions': total_questions - answered_questions,
            'correct_answers': correct_answers,
            'incorrect_answers': answered_questions - correct_answers,
            'time_taken': time_taken
        })

    question_analysis = []
    for q in all_questions:
        q_answers = StudentAnswer.query.filter_by(question_id=q.id).all()
        q_correct_count = 0
        for ans in q_answers:
            if q.question_type in ['single-choice', 'multiple-choice']:
                student_ans = set(ans.answer_text.split(','))
                correct_ans = set(q.correct_answer)
                if student_ans == correct_ans:
                    q_correct_count += 1
            else:
                if ans.answer_text.lower() == q.correct_answer.lower():
                    q_correct_count += 1

        question_analysis.append({
            'question_text': q.question_text,
            'correct_count': q_correct_count,
            'incorrect_count': len(q_answers) - q_correct_count
        })

    average_score = sum(s['score'] for s in submissions if s['score'] is not None) / len(submissions) if submissions else 0

    return {
        'submissions': submissions,
        'question_analysis': question_analysis,
        'average_score': average_score
    }

@app.route('/teacher/analytics/', defaults={'exam_id': None})
@app.route('/teacher/analytics/<int:exam_id>')
@login_required
def teacher_analytics(exam_id):
    exam = None
    analytics_data = {
        'submissions': [],
        'question_analysis': [],
        'average_score': 0,
        'completion_rate': 0
    }

    if exam_id:
        exam = Exam.query.filter_by(id=exam_id, teacher_id=current_user.id).first()
        if exam:
            analytics_data = get_exam_analytics(exam_id)

    teacher_exam_ids = [e.id for e in Exam.query.filter_by(teacher_id=current_user.id).all()]
    total_students_with_submissions = db.session.query(db.func.count(db.distinct(ExamSubmission.student_id))).filter(ExamSubmission.exam_id.in_(teacher_exam_ids)).scalar()

    teacher_classes = [c[0] for c in db.session.query(Exam.class_).filter_by(teacher_id=current_user.id).distinct().all()]
    total_students_in_classes = User.query.filter(User.role == 'student', User.class_.in_(teacher_classes)).count()

    analytics_data['completion_rate'] = (total_students_with_submissions / total_students_in_classes) * 100 if total_students_in_classes > 0 else 0

    return render_template('teacher_analytics.html', exam=exam, **analytics_data)

@app.route('/teacher/exam/<int:exam_id>/export/<format>')
@login_required
def export_results(exam_id, format):
    exam = Exam.query.filter_by(id=exam_id, teacher_id=current_user.id).first()
    if not exam:
        flash('Exam not found.')
        return redirect(url_for('teacher_dashboard'))

    analytics_data = get_exam_analytics(exam_id)
    submissions = analytics_data['submissions']

    # Format time_taken for export
    for sub in submissions:
        time_taken = sub['time_taken']
        sub['time_taken'] = f"{int(time_taken.total_seconds() // 60)}m {int(time_taken.total_seconds() % 60)}s" if time_taken else "N/A"

    if format == 'csv':
        output = BytesIO()
        df = pd.DataFrame(submissions)
        df.to_csv(output, index=False)
        output.seek(0)
        return make_response(output.getvalue(), 200, {'Content-Disposition': f'attachment; filename=results_{exam_id}.csv', 'Content-Type': 'text/csv'})

    elif format == 'pdf':
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, txt=f"Exam Results: {exam.title}", ln=1, align='C')

        col_widths = [40, 20, 25, 25, 25, 30, 25]
        headers = ['Student', 'Score', 'Answered', 'Correct', 'Incorrect', 'Unanswered', 'Time Taken']

        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 10, header, 1, 0, 'C')
        pdf.ln()

        pdf.set_font('Arial', '', 10)
        for sub in submissions:
            pdf.cell(col_widths[0], 10, str(sub['fullname']), 1)
            pdf.cell(col_widths[1], 10, f"{sub['score']:.2f}%", 1)
            pdf.cell(col_widths[2], 10, str(sub['answered_questions']), 1)
            pdf.cell(col_widths[3], 10, str(sub['correct_answers']), 1)
            pdf.cell(col_widths[4], 10, str(sub['incorrect_answers']), 1)
            pdf.cell(col_widths[5], 10, str(sub['unanswered_questions']), 1)
            pdf.cell(col_widths[6], 10, str(sub['time_taken']), 1)
            pdf.ln()

        output = BytesIO(pdf.output(dest='S').encode('latin-1'))
        return make_response(output.getvalue(), 200, {'Content-Disposition': f'attachment; filename=results_{exam_id}.pdf', 'Content-Type': 'application/pdf'})

    return redirect(url_for('teacher_analytics', exam_id=exam_id))

# Student routes
@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, role='student').first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password.')

    return render_template('student_login.html')

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        gender = request.form['gender']
        student_class = request.form['class_']

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
        else:
            password_hash = generate_password_hash(password)
            new_student = User(
                fullname=fullname,
                email=email,
                password_hash=password_hash,
                role='student',
                gender=gender,
                class_=student_class
            )
            db.session.add(new_student)
            db.session.commit()
            flash('Registration successful. Please login.')
            return redirect(url_for('student_login'))

    return render_template('student_register.html')

@app.route('/student/exam/<int:exam_id>/instructions')
@login_required
def exam_instructions(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    return render_template('exam_instructions.html', exam=exam)

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    now = get_wat_now()

    submitted_exam_ids = [s.exam_id for s in current_user.submissions]

    available_exams = Exam.query.filter(
        Exam.id.notin_(submitted_exam_ids),
        or_(
            # Case 1: Exam is currently active within a defined time window
            (Exam.start_time != None) & (Exam.end_time != None) & (Exam.start_time <= now) & (Exam.end_time >= now),
            # Case 2: Exam has no start or end time, making it always available
            (Exam.start_time == None) & (Exam.end_time == None)
        )
    ).all()

    upcoming_exams = Exam.query.filter(Exam.start_time > now).all()

    completed_exams = db.session.query(
        Exam.id, Exam.title, Exam.class_, ExamSubmission.id.label('submission_id'), ExamSubmission.score, Exam.delay_results
    ).join(ExamSubmission).filter(
        ExamSubmission.student_id == current_user.id,
        ExamSubmission.status == 'submitted'
    ).all()

    return render_template('student_dashboard.html', available_exams=available_exams, upcoming_exams=upcoming_exams, completed_exams=completed_exams, now=now)

@app.route('/student/exam/start/<int:exam_id>')
@login_required
def start_exam(exam_id):
    submission = ExamSubmission.query.filter_by(student_id=current_user.id, exam_id=exam_id).first()
    if not submission:
        submission = ExamSubmission(student_id=current_user.id, exam_id=exam_id, start_time=get_wat_now())
        db.session.add(submission)
        db.session.commit()

    exam = Exam.query.get_or_404(exam_id)
    if exam.randomize_questions:
        questions = sorted(exam.questions, key=lambda k: random.random())
    else:
        questions = sorted(exam.questions, key=lambda k: k.id)

    return render_template('take_exam.html', exam=exam, questions=questions, submission_id=submission.id)

@app.route('/student/exam/save_answer', methods=['POST'])
@login_required
def save_answer():
    data = request.json
    submission_id = data['submission_id']
    question_id = data['question_id']
    answer_text = data['answer_text']

    answer = StudentAnswer.query.filter_by(submission_id=submission_id, question_id=question_id).first()
    if answer:
        answer.answer_text = answer_text
    else:
        answer = StudentAnswer(submission_id=submission_id, question_id=question_id, answer_text=answer_text)
        db.session.add(answer)

    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email, role='admin').first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password.')

    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    pending_teachers = User.query.filter_by(role='teacher', status='pending').all()
    return render_template('admin_dashboard.html', pending_teachers=pending_teachers)

@app.route('/admin/teacher/approve/<int:teacher_id>')
@login_required
def approve_teacher(teacher_id):
    teacher = User.query.get(teacher_id)
    if teacher and teacher.role == 'teacher':
        teacher.status = 'approved'
        db.session.commit()
        flash('Teacher approved.')
    else:
        flash('Teacher not found.')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/teacher/decline/<int:teacher_id>')
@login_required
def decline_teacher(teacher_id):
    teacher = User.query.get(teacher_id)
    if teacher and teacher.role == 'teacher':
        db.session.delete(teacher)
        db.session.commit()
        flash('Teacher declined.')
    else:
        flash('Teacher not found.')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@login_required
def manage_users():
    users = User.query.all()
    return render_template('manage_users.html', users=users)

@app.route('/admin/analytics')
@login_required
def admin_analytics():
    total_users = User.query.count()
    total_teachers = User.query.filter_by(role='teacher').count()
    total_students = User.query.filter_by(role='student').count()
    total_exams = Exam.query.count()
    total_submissions = ExamSubmission.query.count()
    average_score = db.session.query(db.func.avg(ExamSubmission.score)).scalar() or 0

    stats = {
        'total_users': total_users,
        'total_teachers': total_teachers,
        'total_students': total_students,
        'total_exams': total_exams,
        'total_submissions': total_submissions,
        'average_score': average_score
    }
    return render_template('admin_analytics.html', stats=stats)

@app.route('/admin/users/bulk_import', methods=['POST'])
@login_required
def bulk_import_users():
    file = request.files['file']
    if not file:
        flash('No file selected for upload.')
        return redirect(url_for('manage_users'))

    if file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
        for index, row in df.iterrows():
            if not User.query.filter_by(email=row['email']).first():
                password_hash = generate_password_hash(row['password'])
                new_user = User(
                    fullname=row['fullname'],
                    email=row['email'],
                    password_hash=password_hash,
                    role=row['role'],
                    gender=row['gender'],
                    class_=row['class']
                )
                db.session.add(new_user)
        db.session.commit()
        flash('Bulk user import completed.')
    else:
        flash('Invalid file format. Please upload an Excel file (.xlsx).')

    return redirect(url_for('manage_users'))

@app.route('/admin/users/export')
@login_required
def export_users():
    users = User.query.all()
    users_data = [{
        'fullname': user.fullname,
        'email': user.email,
        'role': user.role,
        'gender': user.gender,
        'class': user.class_
    } for user in users]

    df = pd.DataFrame(users_data)
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Users')
    writer.close()
    output.seek(0)

    return make_response(output.getvalue(), 200, {
        'Content-Disposition': 'attachment; filename=all_users.xlsx',
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    })

@app.route('/admin/user/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.fullname = request.form['fullname']
        user.email = request.form['email']
        user.role = request.form['role']
        db.session.commit()
        flash('User updated successfully.')
        return redirect(url_for('manage_users'))

    return render_template('edit_user.html', user=user)

@app.route('/admin/user/reset_password/<int:user_id>')
@login_required
def admin_reset_password(user_id):
    user = User.query.get(user_id)
    if user:
        token = secrets.token_urlsafe(16)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        new_token = PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at)
        db.session.add(new_token)
        db.session.commit()

        reset_link = url_for('reset_password', token=token, _external=True)
        send_email(
            subject='Password Reset Initiated by Admin',
            recipients=[user.email],
            body=f'An admin has initiated a password reset for your account. Click the following link to reset your password: {reset_link}'
        )
        flash(f"A password reset link has been sent to {user.email}.")
    else:
        flash('User not found.')
    return redirect(url_for('manage_users'))

@app.route('/admin/user/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully.')
    else:
        flash('User not found.')
    return redirect(url_for('manage_users'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        user = User.query.get(current_user.id)
        user.fullname = request.form['fullname']
        user.email = request.form['email']

        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '':
                # Create a secure, unique filename
                filename = secure_filename(f"{current_user.id}_{file.filename}")

                # Ensure the 'profiles' subdirectory exists
                profiles_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles')
                os.makedirs(profiles_folder, exist_ok=True)

                filepath = os.path.join(profiles_folder, filename)
                file.save(filepath)
                user.profile_image = filename

        db.session.commit()
        flash('Profile updated successfully.')
        return redirect(url_for('profile'))

    return render_template('profile.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()

        if user:
            token = secrets.token_urlsafe(16)
            expires_at = datetime.utcnow() + timedelta(hours=1)
            new_token = PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at)
            db.session.add(new_token)
            db.session.commit()

            reset_link = url_for('reset_password', token=token, _external=True)
            send_email(
                subject='Password Reset Request',
                recipients=[user.email],
                body=f'Click the following link to reset your password: {reset_link}'
            )
            flash('A password reset link has been sent to your email.')
        else:
            flash('Email address not found.')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_data = PasswordResetToken.query.filter(PasswordResetToken.token == token, PasswordResetToken.expires_at > datetime.utcnow()).first()

    if not token_data:
        flash('Invalid or expired password reset link.')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.')
            return render_template('reset_password.html', token=token)

        user = User.query.get(token_data.user_id)
        user.password_hash = generate_password_hash(password)
        db.session.delete(token_data)
        db.session.commit()

        flash('Your password has been reset successfully.')
        return redirect(url_for('student_login'))

    return render_template('reset_password.html', token=token)

def get_google_flow():
    """Initializes and returns the Google OAuth Flow object."""
    client_secrets_file = os.path.join(os.path.dirname(__file__), 'client_secret.json')
    return Flow.from_client_secrets_file(
        client_secrets_file,
        scopes=['https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email', 'openid'],
        redirect_uri=url_for('google_callback', _external=True)
    )

@app.route('/google/login')
def google_login():
    try:
        flow = get_google_flow()
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        return redirect(authorization_url)
    except FileNotFoundError:
        flash("Google OAuth is not configured. Please add client_secret.json.")
        return redirect(url_for('student_login'))

@app.route('/google/callback')
def google_callback():
    flow = get_google_flow()
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    request_session = requests.session()
    cached_session = CacheControl(request_session)
    token_request = google_requests.Request(session=cached_session)

    id_info = id_token.verify_oauth2_token(
        id_token=credentials._id_token,
        request=token_request,
        audience=app.config['GOOGLE_CLIENT_ID']
    )

    email = id_info.get('email')
    name = id_info.get('name')

    user = User.query.filter_by(email=email).first()

    if not user:
        password_hash = generate_password_hash(secrets.token_hex(16))
        user = User(
            fullname=name,
            email=email,
            password_hash=password_hash,
            role='student',
            status='approved'
        )
        db.session.add(user)
        db.session.commit()

    login_user(user)
    return redirect(url_for('student_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)