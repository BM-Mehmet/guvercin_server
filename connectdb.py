import mysql.connector

def get_connection():
    db_config = {
        'host': 'localhost',
        'user': 'guvercin',
        'password': '',
        'database': 'guvercin'
    }
    db_connection = mysql.connector.connect(**db_config)
    cursor = db_connection.cursor(dictionary=True)
    return db_connection, cursor

