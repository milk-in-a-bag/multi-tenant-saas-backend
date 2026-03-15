import os, django
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'test_neondb' AND pid <> pg_backend_pid()")
    rows = cursor.fetchall()
    print(f'Terminated {len(rows)} connections')
try:
    from django.db import connections
    conn = connections['default']
    conn.ensure_connection()
    conn.connection.autocommit = True
    with conn.connection.cursor() as cursor:
        cursor.execute('DROP DATABASE IF EXISTS test_neondb')
    print('Dropped test_neondb')
except Exception as e:
    print(f'Error: {e}')
