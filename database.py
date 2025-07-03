import sqlite3
import logging

# Configuração de logging para ver mensagens do banco de dados
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATABASE_NAME = 'bot_data.db'

def connect_db():
    """Conecta ao banco de dados SQLite."""
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.execute("PRAGMA foreign_keys = ON;") # Garante integridade referencial
        logging.info(f"Conectado ao banco de dados: {DATABASE_NAME}")
        return conn
    except sqlite3.Error as e:
        logging.error(f"Erro ao conectar ao banco de dados: {e}")
        return None

def init_db():
    """Inicializa as tabelas do banco de dados se não existirem."""
    conn = connect_db()
    if conn:
        try:
            cursor = conn.cursor()

            # Tabela para configurações do Anti-Raid
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anti_raid_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    min_account_age_hours INTEGER DEFAULT 24,
                    join_burst_threshold INTEGER DEFAULT 10,
                    join_burst_time_seconds INTEGER DEFAULT 60
                    -- channel_id e message_id serão adicionados via ALTER TABLE se não existirem
                )
            """)
            logging.info("Tabela 'anti_raid_settings' verificada/criada.")

            # ADICIONA AS COLUNAS 'channel_id' E 'message_id' SE NÃO EXISTIREM
            try:
                cursor.execute("ALTER TABLE anti_raid_settings ADD COLUMN channel_id INTEGER;")
                logging.info("Coluna 'channel_id' adicionada à tabela 'anti_raid_settings'.")
            except sqlite3.OperationalError as e:
                if "duplicate column name: channel_id" in str(e):
                    logging.info("Coluna 'channel_id' já existe na tabela 'anti_raid_settings'.")
                else:
                    logging.error(f"Erro ao adicionar coluna 'channel_id' à tabela 'anti_raid_settings': {e}")

            try:
                cursor.execute("ALTER TABLE anti_raid_settings ADD COLUMN message_id INTEGER;")
                logging.info("Coluna 'message_id' adicionada à tabela 'anti_raid_settings'.")
            except sqlite3.OperationalError as e:
                if "duplicate column name: message_id" in str(e):
                    logging.info("Coluna 'message_id' já existe na tabela 'anti_raid_settings'.")
                else:
                    logging.error(f"Erro ao adicionar coluna 'message_id' à tabela 'anti_raid_settings': {e}")


            # Tabela para mensagens de Welcome/Leave
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_leave_messages (
                    guild_id INTEGER PRIMARY KEY,
                    welcome_enabled BOOLEAN DEFAULT 0, 
                    welcome_channel_id INTEGER,
                    welcome_message TEXT,
                    welcome_embed_json TEXT, 
                    leave_enabled BOOLEAN DEFAULT 0,  
                    leave_channel_id INTEGER,
                    leave_message TEXT,
                    leave_embed_json TEXT
                )
            """)
            logging.info("Tabela 'welcome_leave_messages' verificada/criada.")


            # Tabela para embeds salvos pelo EmbedCreator
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS saved_embeds (
                    guild_id INTEGER NOT NULL,
                    embed_name TEXT NOT NULL,
                    embed_json TEXT NOT NULL,
                    PRIMARY KEY (guild_id, embed_name)
                )
            """)
            logging.info("Tabela 'saved_embeds' verificada/criada.")


            # Tabela para sistema de Tickets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_settings (
                    guild_id INTEGER PRIMARY KEY,
                    category_id INTEGER,
                    transcript_channel_id INTEGER,
                    ticket_role_id INTEGER, -- Cargo que pode ver tickets
                    ticket_message_id INTEGER, -- ID da mensagem do painel de ticket
                    ticket_channel_id INTEGER, -- Canal onde o painel de ticket está
                    panel_embed_json TEXT, -- Coluna para o embed do painel de tickets
                    ticket_initial_embed_json TEXT -- NOVA COLUNA para o embed da mensagem inicial do ticket
                )
            """)
            logging.info("Tabela 'ticket_settings' verificada/criada (incluindo ticket_initial_embed_json).")


            # Tabela para tickets ativos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL UNIQUE,
                    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'open',
                    closed_by_id INTEGER, -- Nova coluna para quem fechou o ticket
                    closed_at TIMESTAMP -- Nova coluna para quando o ticket foi fechado
                )
            """)
            logging.info("Tabela 'active_tickets' verificada/criada.")


            # Tabela para sistema de Casamento
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS marriages (
                    marriage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    partner1_id INTEGER NOT NULL,
                    partner2_id INTEGER NOT NULL,
                    married_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, partner1_id),
                    UNIQUE(guild_id, partner2_id) -- Garante que uma pessoa só pode casar uma vez por guild
                )
            """)
            logging.info("Tabela 'marriages' verificada/criada.")


            # Tabela para Logs de Moderação
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS moderation_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logging.info("Tabela 'moderation_logs' verificada/criada.")

            # ADICIONA A COLUNA 'duration' SE NÃO EXISTIR
            try:
                cursor.execute("ALTER TABLE moderation_logs ADD COLUMN duration TEXT;")
                logging.info("Coluna 'duration' adicionada à tabela 'moderation_logs'.")
            except sqlite3.OperationalError as e:
                if "duplicate column name: duration" in str(e):
                    logging.info("Coluna 'duration' já existe na tabela 'moderation_logs'.")
                else:
                    logging.error(f"Erro ao adicionar coluna 'duration' à tabela 'moderation_logs': {e}")

            # --- NOVAS TABELAS PARA LOCKDOWN ---
            # Tabela para canais em lockdown (persistência do estado de lockdown)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS locked_channels (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    locked_until_timestamp INTEGER, -- Timestamp Unix opcional para lockdown temporário
                    reason TEXT,
                    locked_by_id INTEGER
                )
            """)
            logging.info("Tabela 'locked_channels' verificada/criada.")

            # Tabela para as configurações do painel de lockdown (onde o painel está)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lockdown_panel_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL
                )
            """)
            logging.info("Tabela 'lockdown_panel_settings' verificada/criada.")

            # --- FIM DAS NOVAS TABELAS ---

            conn.commit()
            logging.info("Tabelas do banco de dados verificadas/criadas com sucesso.")
        except sqlite3.Error as e:
            logging.error(f"Erro ao inicializar o banco de dados: {e}")
        finally:
            conn.close()

# Exemplo de como você usaria isso em um comando ou evento:
def execute_query(query, params=(), fetchone=False, fetchall=False):
    """Executa uma query SQL e retorna os resultados, se houver."""
    conn = connect_db()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit() # Seu execute_query já faz commit por padrão
            if fetchone:
                return cursor.fetchone()
            if fetchall:
                return cursor.fetchall()
            return True # Retorna True para indicar que a operação de escrita foi bem-sucedida
        except sqlite3.Error as e:
            logging.error(f"Erro ao executar query '{query}' com params {params}: {e}")
            return False # Retorna False em caso de erro
        finally:
            conn.close()
    return False # Retorna False se a conexão não puder ser estabelecida

# Inicializa o DB ao importar este módulo (ou quando main.py chama init_db)
# if __name__ == '__main__':
#     init_db()
#     print("Database initialization test complete.")