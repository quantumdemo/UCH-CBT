import pytz
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    gender = db.Column(db.String(10))
    class_ = db.Column('class', db.String(50))
    status = db.Column(db.String(10), default='approved')
    profile_image = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.utc))

    exams = db.relationship('Exam', backref='teacher', lazy=True)
    submissions = db.relationship('ExamSubmission', backref='student', lazy=True)

class Exam(db.Model):
    __tablename__ = 'exams'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.DateTime(timezone=True))
    end_time = db.Column(db.DateTime(timezone=True))
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    class_ = db.Column('class', db.String(50))
    randomize_questions = db.Column(db.Boolean, default=False)
    delay_results = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(pytz.utc))

    questions = db.relationship('Question', backref='exam', lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship('ExamSubmission', backref='exam', lazy=True, cascade="all, delete-orphan")

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_image = db.Column(db.String(255))
    question_type = db.Column(db.String(20), nullable=False)
    options = db.Column(JSONB)
    correct_answer = db.Column(JSONB)

    answers = db.relationship('StudentAnswer', backref='question', lazy=True, cascade="all, delete-orphan")

class ExamSubmission(db.Model):
    __tablename__ = 'exam_submissions'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    start_time = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(pytz.utc))
    end_time = db.Column(db.DateTime(timezone=True))
    score = db.Column(db.Integer)
    status = db.Column(db.String(20), default='in-progress', nullable=False)

    answers = db.relationship('StudentAnswer', backref='submission', lazy=True, cascade="all, delete-orphan")

class StudentAnswer(db.Model):
    __tablename__ = 'student_answers'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('exam_submissions.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    answer_text = db.Column(db.Text)

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)