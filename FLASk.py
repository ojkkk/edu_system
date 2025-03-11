@app.route('/teacher')
def teacher_dashboard():
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT 
                    c.id,
                    c.name,
                    c.time,
                    c.location,
                    c.credit,
                    COUNT(e.student_id) AS student_count
                FROM courses c
                LEFT JOIN enrollments e ON c.id = e.course_id
                WHERE c.teacher_id = %s
                GROUP BY c.id
            ''', (session['user_id'],))
            courses = cursor.fetchall()
        return render_template('teacher.html', courses=courses)
    except pymysql.Error as e:
        # ...错误处理...

        @app.route('/teacher')
        def teacher_dashboard():
            if 'user_id' not in session or session['role'] != 'teacher':
                return redirect(url_for('login'))

            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
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

                return render_template('teacher.html', courses=courses)
            except pymysql.Error as e:
                print("Database error:", e)
                return "Error loading dashboard"
            finally:
                conn.close()