# database.py
import psycopg2
from psycopg2 import Error

# Veritabanı bağlantı bilgileri (kendi bilgilerine göre güncelle)
DB_CONFIG = {
    "dbname": "mamathon",
    "user": "ardaaydin",
    "password": "root",
    "host": "localhost",
    "port": "5432"
}

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Error as e:
        print(f"Veritabanına bağlanırken hata: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn is None:
        return

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS game_records (
                    id SERIAL PRIMARY KEY,
                    player1_wallet TEXT NOT NULL,
                    player2_wallet TEXT NOT NULL,
                    block_height INTEGER NOT NULL,
                    namespace TEXT NOT NULL
                );
            """)
            conn.commit()
        print("game_records tablosu oluşturuldu veya zaten var.")
    except Error as e:
        print(f"Tablo oluşturulurken hata: {e}")
    finally:
        conn.close()

def save_game_record(player1_wallet, player2_wallet, block_height, namespace):
    conn = get_db_connection()
    if conn is None:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO game_records (player1_wallet, player2_wallet, block_height, namespace)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
            """, (player1_wallet, player2_wallet, block_height, namespace))
            record_id = cur.fetchone()[0]
            conn.commit()
            return record_id
    except Error as e:
        print(f"Kayıt eklenirken hata: {e}")
        return False
    finally:
        conn.close()

def get_game_record(game_id):
    conn = get_db_connection()
    if conn is None:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, player1_wallet, player2_wallet, block_height, namespace
                FROM game_records
                WHERE id = %s;
            """, (game_id,))
            result = cur.fetchone()
            if result:
                return {
                    "game_id": result[0],
                    "player1_wallet": result[1],
                    "player2_wallet": result[2],
                    "block_height": result[3],
                    "namespace": result[4]
                }
            return None
    except Error as e:
        print(f"Kayıt getirilirken hata: {e}")
        return None
    finally:
        conn.close()

def get_last_game_id():
    """game_records tablosundaki son id değerini döner, yoksa 0 döner."""
    conn = get_db_connection()
    if conn is None:
        return 0

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(id) FROM game_records;")
            result = cur.fetchone()[0]
            return result if result is not None else 0
    except Error as e:
        print(f"Son id alınırken hata: {e}")
        return 0
    finally:
        conn.close()

def get_player_matches(user_wallet):
    conn = get_db_connection()
    if conn is None:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, player1_wallet, player2_wallet, block_height, namespace
            FROM game_records
            WHERE player1_wallet = %s OR player2_wallet = %s
            ORDER BY id DESC
        """, (user_wallet, user_wallet))
        return cur.fetchall()