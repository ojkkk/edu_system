from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import pymysql.cursors
import os
from datetime import datetime, time



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
        # 获取基础信息
        username = request.form['username']
        password = request.form['password']  # 建议后续增加密码加密
        role = request.form['role']
        fullname = request.form['fullname']
        email = request.form['email']
        department_id = request.form.get('department_id')

        # 验证学院选择（学生/教师必须选择）
        if role in ['student', 'teacher'] and not department_id:
            return render_template('register.html',
                                   error="必须选择所属学院",
                                   departments=get_departments())

        # 验证管理员不需要学院
        if role == 'admin' and department_id:
            return render_template('register.html',
                                   error="管理员无需选择学院",
                                   departments=get_departments())

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # 检查用户名唯一性
                cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
                if cursor.fetchone():
                    return render_template('register.html',
                                           error="用户名已存在",
                                           departments=get_departments())

                # 构建插入语句
                insert_sql = '''
                    INSERT INTO users 
                    (username, password, role, fullname, email, department_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''' if role != 'admin' else '''
                    INSERT INTO users 
                    (username, password, role, fullname, email,department_id)
                    VALUES (%s, %s, %s, %s, %s, 2)
                '''

                # 执行插入
                if role == 'admin':
                    cursor.execute(insert_sql,
                                   (username, password, role, fullname, email))
                else:
                    # 验证学院有效性
                    cursor.execute('SELECT id FROM departments WHERE id = %s', (department_id,))
                    if not cursor.fetchone():
                        return render_template('register.html',
                                               error="无效的学院选择",
                                               departments=get_departments())

                    cursor.execute(insert_sql,
                                   (username, password, role, fullname, email, department_id))

                conn.commit()
                return redirect(url_for('login'))

        except pymysql.Error as e:
            print("Database error:", e)
            return render_template('register.html',
                                   error="注册失败，请检查输入",
                                   departments=get_departments())
        finally:
            conn.close()

    # GET请求获取学院列表
    return render_template('register.html', departments=get_departments())


def get_departments():
    """获取所有学院信息的工具函数"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, name FROM departments')
            return cursor.fetchall()
    except pymysql.Error:
        return []
    finally:
        conn.close()


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
            # 获取学生学院信息
            cursor.execute('''
                SELECT 
                    u.fullname, 
                    u.email, 
                    u.department_id,
                    d.name AS department_name
                FROM users u
                JOIN departments d ON u.department_id = d.id
                WHERE u.id = %s
            ''', (session['user_id'],))
            student_info = cursor.fetchone()

            if not student_info or not student_info['department_id']:
                return render_template('error.html',
                                    message="未分配学院，请联系管理员")

            # 已选课程查询（包含详细成绩信息）
            cursor.execute('''
                SELECT 
                    c.id,
                    c.name,
                    c.credit,
                    cl.building,
                    cl.room_number,
                    ts.weekday,
                    DATE_FORMAT(ts.start_time, '%%H:%%i') AS start_time,
                    DATE_FORMAT(ts.end_time, '%%H:%%i') AS end_time,
                    e.usual_grade,
                    e.final_grade,
                    ROUND((e.usual_grade * 0.3 + e.final_grade * 0.7), 1) AS total_grade
                FROM enrollments e
                JOIN courses c ON e.course_id = c.id
                JOIN classrooms cl ON c.classroom_id = cl.id
                JOIN time_slots ts ON c.time_slot_id = ts.id
                WHERE e.student_id = %s
            ''', (session['user_id'],))
            enrolled = cursor.fetchall()

            # 可选课程查询（学院限制+容量验证）
            cursor.execute('''
                SELECT 
                    c.id AS course_id,
                    c.name AS course_name,
                    c.credit,
                    cl.building,
                    cl.room_number,
                    ts.weekday,
                    DATE_FORMAT(ts.start_time, '%%H:%%i') AS start_time,
                    DATE_FORMAT(ts.end_time, '%%H:%%i') AS end_time,
                    u.fullname AS teacher_name,
                    cl.capacity,
                    (SELECT COUNT(*) FROM enrollments WHERE course_id = c.id) AS enrolled_count,
                    cl.capacity - (SELECT COUNT(*) FROM enrollments WHERE course_id = c.id) AS remaining
                FROM courses c
                JOIN users u ON c.teacher_id = u.id
                JOIN classrooms cl ON c.classroom_id = cl.id
                JOIN time_slots ts ON c.time_slot_id = ts.id
                WHERE c.department_id = %s
                AND c.id NOT IN (
                    SELECT course_id 
                    FROM enrollments 
                    WHERE student_id = %s
                )
                AND (SELECT COUNT(*) FROM enrollments WHERE course_id = c.id) < cl.capacity
            ''', (student_info['department_id'], session['user_id']))
            available = cursor.fetchall()

    except pymysql.Error as e:
        print("Database error:", e)
        return render_template('error.html', message="数据加载失败")
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
            # 获取教师完整信息（含学院）
            cursor.execute('''
                SELECT 
                    u.fullname,
                    u.email,
                    d.name AS department_name
                FROM users u
                JOIN departments d ON u.department_id = d.id
                WHERE u.id = %s
            ''', (session['user_id'],))
            teacher_info = cursor.fetchone()

            # 获取教师所授课程（包含详细时间地点）
            cursor.execute('''
                    SELECT 
                        c.id,
                        c.name,
                        c.credit,
                        d.name AS department_name,
                        ts.weekday,
                        DATE_FORMAT(ts.start_time, '%%H:%%i') AS start_time,
                        DATE_FORMAT(ts.end_time, '%%H:%%i') AS end_time,
                        cl.building,
                        cl.room_number,
                        cl.capacity,
                        (SELECT COUNT(*) 
                         FROM enrollments 
                         WHERE course_id = c.id) AS student_count
                    FROM courses c
                    JOIN departments d ON c.department_id = d.id
                    JOIN classrooms cl ON c.classroom_id = cl.id
                    JOIN time_slots ts ON c.time_slot_id = ts.id
                    WHERE c.teacher_id = %s
                ''', (session['user_id'],))
            courses = cursor.fetchall()

    except pymysql.Error as e:
        print("Database error:", e)
        return render_template('error.html', message="数据加载失败")
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
                            SELECT 
                                c.id,
                                c.name,
                                c.credit,
                                d.name AS department_name,
                                u.fullname AS teacher_name,
                                ts.weekday,
                                ts.start_time,
                                ts.end_time,
                                cl.building,
                                cl.room_number
                            FROM courses c
                            JOIN departments d ON c.department_id = d.id
                            JOIN users u ON c.teacher_id = u.id
                            JOIN time_slots ts ON c.time_slot_id = ts.id
                            JOIN classrooms cl ON c.classroom_id = cl.id
                            ORDER BY c.id DESC
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

    conn = get_db_connection()
    try:
        if request.method == 'POST':
            # 获取表单数据
            name = request.form['name']
            teacher_id = request.form['teacher_id']
            classroom_id = request.form['classroom_id']
            time_slot_id = request.form['time_slot_id']
            credit = request.form['credit']
            department_id = request.form['department_id']

            # 验证教师有效性
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT id, department_id 
                    FROM users 
                    WHERE id = %s AND role = 'teacher'
                ''', (teacher_id,))
                teacher = cursor.fetchone()
                if not teacher:
                    return "教师不存在", 400

                # 验证教师学院匹配
                if teacher['department_id'] != int(department_id):
                    return "教师所属学院与课程学院不匹配", 400

            # 验证学院有效性
            with conn.cursor() as cursor:
                cursor.execute('SELECT id FROM departments WHERE id = %s', (department_id,))
                if not cursor.fetchone():
                    return "无效的学院选择", 400

            # 检查时间冲突（保持原有逻辑）
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT c.name, u.fullname 
                    FROM courses c
                    JOIN users u ON c.teacher_id = u.id
                    WHERE c.classroom_id = %s AND c.time_slot_id = %s
                ''', (classroom_id, time_slot_id))
                if conflict := cursor.fetchone():
                    return jsonify(
                        available=False,
                        conflict_course=conflict['name'],
                        teacher=conflict['fullname']
                    ), 409

            # 插入课程数据
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO courses 
                    (name, teacher_id, classroom_id, time_slot_id, credit, department_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (name, teacher_id, classroom_id, time_slot_id, credit, department_id))
                conn.commit()
            return redirect(url_for('admin_dashboard'))

        # GET请求获取数据
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 教师列表（带学院信息）
            cursor.execute('''
                SELECT u.id, u.fullname, d.name AS department 
                FROM users u
                JOIN departments d ON u.department_id = d.id
                WHERE u.role = 'teacher'
            ''')
            teachers = cursor.fetchall()

            # 教室列表
            cursor.execute('''
                SELECT id, 
                       CONCAT(building, ' ', room_number) AS name,
                       capacity
                FROM classrooms
            ''')
            classrooms = cursor.fetchall()

            # 时间段列表
            cursor.execute('''
                SELECT id,
                       CONCAT(weekday, ' ', 
                              DATE_FORMAT(start_time, '%H:%i'), '-',
                              DATE_FORMAT(end_time, '%H:%i')) AS time_slot
                FROM time_slots
            ''')
            time_slots = cursor.fetchall()

            # 学院列表
            cursor.execute('SELECT id, name FROM departments')
            departments = cursor.fetchall()



    except pymysql.Error as e:
        print("Database error:", e)
        conn.rollback()
        return "操作失败，请稍后再试", 500
    finally:
        conn.close()
    return render_template('admin_add_course.html',
                           teachers=teachers,
                           classrooms=classrooms,
                           time_slots=time_slots,
                           departments=departments)



@app.route('/check_availability')
def check_availability():
    classroom_id = request.args.get('classroom')
    time_slot_id = request.args.get('timeslot')

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
                        SELECT
                            co.name AS course_name,
                            u.fullname AS teacher_name
                        FROM courses co
                        JOIN users u ON co.teacher_id = u.id
                        WHERE co.classroom_id = %s
                        AND co.time_slot_id = %s
                        LIMIT 1
                    ''', (classroom_id, time_slot_id))

            conflict = cursor.fetchone()

            if conflict:
                return jsonify({
                'available': False,
                'conflict_course': conflict['course_name'],
                'teacher': conflict['teacher_name']
            })
            else:
                return jsonify({'available': True})
    except pymysql.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


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

    conn = get_db_connection()
    try:
        if request.method == 'POST':
            # 获取表单数据
            username = request.form['username']
            password = request.form['password']
            role = request.form['role']
            fullname = request.form['fullname']
            email = request.form['email']
            department_id = request.form.get('department_id')

            # 验证学院选择
            if role in ['student', 'teacher'] and not department_id:
                return render_template('admin_add_user.html',
                                     departments=get_departments(),
                                     error="必须选择所属学院")

            # 验证管理员无学院
            if role == 'admin' and department_id:
                return render_template('admin_add_user.html',
                                     departments=get_departments(),
                                     error="管理员无需选择学院")

            with conn.cursor() as cursor:
                # 检查用户名唯一性
                cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
                if cursor.fetchone():
                    return render_template('admin_add_user.html',
                                         departments=get_departments(),
                                         error="用户名已存在")

                # 验证学院有效性
                if role in ['student', 'teacher']:
                    cursor.execute('SELECT id FROM departments WHERE id = %s', (department_id,))
                    if not cursor.fetchone():
                        return render_template('admin_add_user.html',
                                             departments=get_departments(),
                                             error="无效的学院选择")

                # 构建插入语句
                if role == 'admin':
                    insert_sql = '''
                        INSERT INTO users 
                        (username, password, role, fullname, email)
                        VALUES (%s, %s, %s, %s, %s)
                    '''
                    params = (username, password, role, fullname, email)
                else:
                    insert_sql = '''
                        INSERT INTO users 
                        (username, password, role, fullname, email, department_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    '''
                    params = (username, password, role, fullname, email, department_id)

                # 执行插入
                cursor.execute(insert_sql, params)
                conn.commit()
                return redirect(url_for('manage_users'))

        # GET请求获取学院数据
        return render_template('admin_add_user.html',
                             departments=get_departments())

    except pymysql.Error as e:
        print("Database error:", e)
        return render_template('admin_add_user.html',
                             departments=get_departments(),
                             error="数据库操作失败")
    finally:
        conn.close()








# 自定义时间格式化过滤器
@app.template_filter('format_time')
def format_time_filter(value):
    """将时间值格式化为 HH:MM 格式"""
    try:
        # 处理数据库返回的time对象
        if isinstance(value, time):
            return value.strftime('%H:%M')

        # 处理字符串格式的时间（如MySQL返回的字符串）

        if str(value)[4] == ':':  # 处理 'HH:MM:SS' 或 'HH:MM' 格式
            return str(value)[:4]
        else: return str(value)[:5]

        # 处理其他意外类型
        #return str(value)[:4]  # 保险措施
    except Exception as e:
        print(f"时间格式化错误：{str(e)}")
        return value  # 保持原始值不变


@app.route('/unenroll', methods=['POST'])
def unenroll():




    student_id = session['user_id']
    course_id = request.form.get('course_id')

    # 基本参数验证
    if not course_id or not course_id.isdigit():
        flash('无效的课程ID', 'danger')
        return redirect(url_for('student_dashboard'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 验证选课关系
            cursor.execute('''
                SELECT id 
                FROM enrollments 
                WHERE student_id = %s 
                AND course_id = %s
                AND final_grade IS NULL  # 仅允许退未结课课程
            ''', (student_id, course_id))
            enrollment = cursor.fetchone()

            if not enrollment:
                flash('未找到选课记录或课程已结课', 'warning')
                return redirect(url_for('student_dashboard'))

            # 执行退课
            cursor.execute('''
                DELETE FROM enrollments 
                WHERE id = %s
            ''', (enrollment['id'],))

            conn.commit()
            flash('退课成功', 'success')

    except pymysql.Error as e:
        print(f"退课失败: {e}")
        flash('退课操作失败，请联系管理员', 'danger')
        conn.rollback()
    finally:
        if conn:
            conn.close()


    return redirect(url_for('student_dashboard'))
if __name__ == '__main__':
    app.run(debug=True)