# UCH Staff Secondary School CBT Platform - Comprehensive Documentation

## 1. Project Overview

This document provides a comprehensive overview of the UCH Staff Secondary School Computer-Based Test (CBT) platform. The platform is a robust, scalable, and user-friendly solution designed to manage and conduct online examinations.

### 1.1. Core Features

-   **Modern User Interface:** A professional and responsive landing page with a clean, academic-inspired design.
-   **Distinct User Roles:** Separate interfaces and functionalities for Students, Teachers, and Administrators.
-   **Comprehensive Exam Management:** Teachers can create exams, add questions manually or through bulk uploads (CSV/Excel), and view detailed analytics on exam performance.
-   **Interactive Student Experience:** Students can view available exams, take them through a timed interface, and access their results and performance feedback.
-   **Administrative Control:** Administrators have oversight over the platform, with the ability to approve teacher signups and manage all user accounts.

### 1.2. Technical Stack

-   **Backend:** Python (Flask)
-   **Database:** PostgreSQL
-   **Frontend:** HTML, CSS, JavaScript
-   **Deployment:** Railway

## 2. Getting Started

This section guides you through setting up the project for local development.

### 2.1. Prerequisites

-   Python 3.12
-   PostgreSQL
-   Git

### 2.2. Installation and Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd cbt_platform
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Set up the database:**
    -   Ensure PostgreSQL is installed and running.
    -   Create a new database for the project.
    -   Create a `.env` file in the project's root directory and add your database URL and other configuration variables:
        ```
        DATABASE_URL="postgresql://user:password@localhost/your_db_name"
        SECRET_KEY="a-very-secret-key"
        # Add mail server credentials for notifications
        MAIL_SERVER="smtp.gmail.com"
        MAIL_PORT=587
        MAIL_USE_TLS=True
        MAIL_USERNAME="your-email@gmail.com"
        MAIL_PASSWORD="your-password"
        ```

4.  **Initialize the database:**
    ```bash
    cd app
    flask initdb
    ```

### 2.3. Running the Application

From the `cbt_platform/app` directory, run:

```bash
flask run
```

The application will be accessible at `http://127.0.0.1:5000`.

### 2.4. Creating an Admin User

To create an admin user, run the following command from the `cbt_platform/app` directory:

```bash
flask create-admin "Admin Name" "admin@example.com" "password"
```

You can then log in as the admin at `/admin/login`.

## 3. Deployment to Railway

This project is configured for easy deployment to Railway.

### 3.1. Railway Configuration Files

-   **`Procfile`:** Specifies the command to run the application on the production server.
-   **`runtime.txt`:** Defines the Python version to be used.
-   **`requirements.txt`:** Lists all the Python dependencies required for the project.

### 3.2. Deployment Steps

1.  **Create a new project on Railway.**
2.  **Connect your GitHub repository to the Railway project.**
3.  **Configure the environment variables** in the Railway project settings, similar to the `.env` file.
4.  **Railway will automatically build and deploy the application.**

## 4. Question Upload Format

You can upload questions in bulk using a CSV or Excel file. The file must have the following columns:

*   `question_text`: The text of the question.
*   `question_type`: Must be one of `single-choice`, `multiple-choice`, or `short-answer`.
*   `option1`, `option2`, `option3`, `option4`: The options for single-choice or multiple-choice questions.
*   `correct_answer`:
    *   For `single-choice`, this should be the number of the correct option (e.g., `0` for `option1`, `1` for `option2`, `2` for `option3`, `3` for `option4`).
    *   For `multiple-choice`, this should be a comma-separated list of the correct option numbers (e.g., `1,3`).
    *   For `short-answer`, this should be the exact correct answer.

Sample: `sample_questions CSV.csv` and `sample_questions EXCEL.xlsx` files are provided in the `cbt_platform` directory.
Sample: `sample_user UPLOAD.xlsx` file is provided in the `cbt_platform` directory for sample user upload by admin.


## Exam Instructions sample

1. You are required to read each question carefully before selecting your answer.  
2. Ensure that your internet connection is stable throughout the duration of the test.  
3. Do not refresh or close the browser window while the exam is in progress.  
4. Each question carries equal marks unless otherwise stated.  
5. Click Next to move to next question, and previous to return to the previous question.  
6. The timer will begin immediately when you start the exam.  
7. You must submit your answers before the time runs out, if not, it would submit automatically.  
8. Any attempt to open other browser tabs, switch screens, or use unauthorised materials will lead to disqualification.  
9. Click Submit once you have answered all questions or when the timer reaches zero.  
10. Your score will be displayed automatically after submission (if enabled by the administrator).  