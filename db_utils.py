import psycopg2
import os
from contextlib import contextmanager

DB_URL = os.environ.get('DATABASE_URL')

@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize the database with required tables."""
    if not DB_URL:
        print("⚠️ DATABASE_URL not set, skipping database initialization")
        return
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Create the stats table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    name TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0
                );
            """)
            
            # Insert the initial row for total analyses
            cur.execute("""
                INSERT INTO stats (name, count) 
                VALUES ('total_analyses', 0) 
                ON CONFLICT (name) DO NOTHING;
            """)
            
            cur.close()
            print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")

def increment_analysis_count():
    """Increment the analysis count and return the new value."""
    if not DB_URL:
        print("⚠️ DATABASE_URL not set, cannot increment count")
        return None
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE stats 
                SET count = count + 1 
                WHERE name = 'total_analyses' 
                RETURNING count;
            """)
            new_count = cur.fetchone()[0]
            cur.close()
            return new_count
    except Exception as e:
        print(f"❌ Failed to increment count: {e}")
        return None

def get_analysis_count():
    """Get the current analysis count."""
    if not DB_URL:
        return None
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT count 
                FROM stats 
                WHERE name = 'total_analyses';
            """)
            result = cur.fetchone()
            cur.close()
            return result[0] if result else 0
    except Exception as e:
        print(f"❌ Failed to get count: {e}")
        return None