import sqlite3

con = sqlite3.connect('student_support.db')
cur = con.cursor()
print('--- USERS ---')
for row in cur.execute('SELECT id, email, role, is_active FROM users'):
    print(row)

print('\n--- STUDENTS ---')
for row in cur.execute('SELECT id, user_id, enrollment_number FROM students'):
    print(row)

print('\n--- ENROLLMENTS ---')
for row in cur.execute('SELECT id, student_id, code_module, code_presentation, is_active FROM enrollments'):
    print(row)

print('\n--- BEHAVIORAL CLUSTERS ---')
for row in cur.execute('SELECT id, enrollment_id, cluster_id FROM behavioral_clusters'):
    print(row)
