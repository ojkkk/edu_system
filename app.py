from flask import Flask, render_template, request, redirect, url_for, session, flash
import pymysql.cursors
import os




app = Flask(__name__)
app.secret_key = 'your_secret_key'

# 数据库配置
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',
    'database': 'edu_system',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


def get_db_connection():
    return pymysql.connect(**db_config)


@app.route('/')
def home():
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        fullname = request.form['fullname']
        email = request.form['email']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
                if cursor.fetchone():
                    return 'Username exists!'
                cursor.execute('''
                    INSERT INTO users (username, password, role, fullname, email)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (username, password, role, fullname, email))
            conn.commit()
        except pymysql.Error as e:
            print("Database error:", e)
            return "Registration failed"
        finally:
            conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT * FROM users 
                    WHERE username = %s AND password = %s
                ''', (username, password))
                user = cursor.fetchone()
        except pymysql.Error as e:
            print("Database error:", e)
            return "Login failed"
        finally:
            conn.close()

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
        flash("用户名或密码错误", "error")


    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# 学生功能
@app.route('/student')
def student_dashboard():
    if 'user_id' not in session or session['role'] != 'student':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 获取学生信息
            cursor.execute('SELECT fullname, email FROM users WHERE id = %s', (session['user_id'],))
            student_info = cursor.fetchone()

            # 查询成绩时获取两个分数
            cursor.execute(
                ''' SELECT c.id, c.name,c.time, c.location, c.credit, e.usual_grade, e.final_grade, (e.usual_grade * 0.3 + e.final_grade * 0.7) AS total_grade 
                FROM enrollments e 
                JOIN courses c ON e.course_id = c.id 
                WHERE e.student_id = %s 
                ''',(session['user_id'],))
            enrolled = cursor.fetchall()



            # 可选课程
            cursor.execute('''
                SELECT 
                    c.id AS course_id,
                    c.name AS course_name,
                    c.credit,
                    c.time,
                    c.location,
                    u.fullname AS teacher_name  # 新增教师姓名字段
                FROM courses c
                JOIN users u ON c.teacher_id = u.id  # 关键关联语句
                WHERE c.id NOT IN (
                    SELECT course_id 
                    FROM enrollments 
                    WHERE student_id = %s
                )
            ''', (session['user_id'],))
            available = cursor.fetchall()
    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading dashboard"
    finally:
        conn.close()

    return render_template('student.html',
                           student=student_info,
                           enrolled=enrolled,
                           available=available)


@app.route('/student/enroll', methods=['POST'])
def enroll():
    if 'user_id' not in session or session['role'] != 'student':
        return redirect(url_for('login'))

    course_id = request.form['course_id']

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO enrollments (student_id, course_id)
                VALUES (%s, %s)
            ''', (session['user_id'], course_id))
        conn.commit()
    except pymysql.IntegrityError:
        return "Already enrolled"
    except pymysql.Error as e:
        print("Database error:", e)
        return "Enrollment failed"
    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))


# 教师功能
@app.route('/teacher')
def teacher_dashboard():
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 教师信息
            cursor.execute('SELECT fullname, email FROM users WHERE id = %s', (session['user_id'],))
            teacher_info = cursor.fetchone()

            # 所授课程
            cursor.execute('''
                                   SELECT 
                                       c.id,
                                       c.name,
                                       c.time,
                                       c.location,
                                       c.credit,
                                       u.fullname AS teacher_name,
                                       COUNT(e.student_id) AS student_count
                                   FROM courses c
                                   JOIN users u ON c.teacher_id = u.id
                                   LEFT JOIN enrollments e ON c.id = e.course_id
                                   WHERE c.teacher_id = %s
                                   GROUP BY c.id
                               ''', (session['user_id'],))
            courses = cursor.fetchall()
    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading dashboard"
    finally:
        conn.close()

    return render_template('teacher.html',
                           teacher=teacher_info,
                           courses=courses)

@app.route('/teacher/add_student', methods=['POST'])
def add_student_to_course():
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))

    student_username = request.form['username']
    course_id = request.form['course_id']

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 验证学生存在且属于当前教师课程
            cursor.execute('''
                SELECT c.id 
                FROM courses c
                WHERE c.id = %s AND c.teacher_id = %s
            ''', (course_id, session['user_id']))
            if not cursor.fetchone():
                return "无权限操作该课程"

            cursor.execute('SELECT id FROM users WHERE username = %s AND role = "student"',
                           (student_username,))
            student = cursor.fetchone()
            if not student:
                return "学生不存在"

            cursor.execute('''
                INSERT INTO enrollments (student_id, course_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE course_id = course_id
            ''', (student['id'], course_id))
        conn.commit()
    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading dashboard"
    return redirect(url_for('course_detail', course_id=course_id))

@app.template_filter('get_grade_status')
def get_grade_status(usual_grade, final_grade):
    if not all([usual_grade, final_grade]):
        return ''
    total = usual_grade * 0.3 + final_grade * 0.7
    if total >= 90: return 'Excellent'
    if total >= 80: return 'Good'
    if total >= 70: return 'Medium'
    if total >= 60: return 'Pass'
    return 'Fail'
@app.route('/teacher/course/<int:course_id>')
def course_detail(course_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT u.id, u.fullname, e.grade 
                FROM enrollments e 
                JOIN users u ON e.student_id = u.id 
                WHERE e.course_id = %s
            ''', (course_id,))
            students = cursor.fetchall()

    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading course details"

    finally:
        conn.close()

    return render_template('course_students.html',
                           students=students,
                           course_id=course_id)


@app.route('/teacher/update_grades', methods=['POST'])
def update_grades():
    student_id = request.form['student_id']
    course_id = request.form['course_id']
    usual_grade = request.form.get('usual_grade', 0)
    final_grade = request.form.get('final_grade', 0)

    try:
        conn = get_db_connection()
        # 验证教师课程权限
        with conn.cursor() as cursor:
            cursor.execute('''
             SELECT c.id 
             FROM courses c
             WHERE c.id = %s AND c.teacher_id = %s
          ''', (course_id, session['user_id']))
            if not cursor.fetchone():
             return "无权限操作该课程"

            cursor.execute('''
                UPDATE enrollments 
                SET usual_grade = %s, final_grade = %s
                WHERE student_id = %s AND course_id = %s
            ''', (usual_grade, final_grade, student_id, course_id))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for('course_detail', course_id=course_id))


# 管理员功能
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT c.*, u.fullname AS teacher_name 
                FROM courses c 
                JOIN users u ON c.teacher_id = u.id
            ''')
            courses = cursor.fetchall()
    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading dashboard"
    finally:
        conn.close()

    return render_template('admin.html', courses=courses)


@app.route('/admin/users')
def manage_users():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, username, role, fullname FROM users')
            users = cursor.fetchall()
        return render_template('admin_users.html', users=users)
    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading users"
    finally:
        conn.close()
@app.route('/admin/add_course', methods=['GET', 'POST'])
def admin_add_course():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        teacher_id = request.form['teacher_id']
        time = request.form['time']
        location = request.form['location']
        credit = request.form['credit']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO courses 
                    (name, teacher_id, time, location, credit)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (name, teacher_id, time, location, credit))
            conn.commit()
        except pymysql.Error as e:
            print("Database error:", e)
            return "Course creation failed"
        finally:
            conn.close()
        return redirect(url_for('admin_dashboard'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, fullname FROM users WHERE role = "teacher"')
            teachers = cursor.fetchall()
    except pymysql.Error as e:
        print("Database error:", e)
        return "Error loading teachers"
    finally:
        conn.close()

    return render_template('admin_add_course.html', teachers=teachers)


@app.route('/admin/delete_course', methods=['POST'])
def delete_course():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    course_id = request.form['course_id']

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM courses WHERE id = %s', (course_id,))
        conn.commit()
    except pymysql.Error as e:
        print("Database error:", e)
        return "Delete failed"
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))


# 管理员删除用户
@app.route('/admin/delete_user', methods=['POST'])
def admin_delete_user():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    user_id = request.form['user_id']

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查是否是最后一个管理员
            cursor.execute('''
                SELECT COUNT(*) as admin_count 
                FROM users 
                WHERE role = 'admin'
            ''')
            admin_count = cursor.fetchone()['admin_count']

            if admin_count <= 1 and request.form.get('role') == 'admin':

                return redirect(url_for('manage_users'))

            cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
        conn.commit()

    except pymysql.Error as e:
        print("Database error:", e)

    finally:
        conn.close()
    return redirect(url_for('manage_users'))


# 管理员添加用户
@app.route('/admin/add_user', methods=['GET', 'POST'])
def admin_add_user():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        fullname = request.form['fullname']
        email = request.form['email']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # 检查用户名是否已存在
                cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
                if cursor.fetchone():

                    return redirect(url_for('admin_add_user'))

                cursor.execute('''
                    INSERT INTO users 
                    (username, password, role, fullname, email)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (username, password, role, fullname, email))
                conn.commit()

                return redirect(url_for('manage_users'))
        except pymysql.Error as e:
            print("Database error:", e)

        finally:
            conn.close()

    return render_template('admin_add_user.html')

if __name__ == '__main__':
    app.run(debug=True)