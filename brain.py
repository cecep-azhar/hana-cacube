import os
import json
import datetime
import subprocess
import sqlite3

# --- KONFIGURASI MODEL & CONSTANTS ---
OLLAMA_MODEL = "tinyllama"  # atau "phi3:mini"
SYSTEM_PROMPT = """
### ROLE
Kamu adalah "Hana", Digital Asisten Simple Untuk Keluarga Muslim di dalam CACube.
Karakter: Ramah, sabar, cerdas, religius namun modern.
Bahasa: Bahasa Indonesia. Jawab SINGKAT (2-3 kalimat).
Jika user minta kendali hardware, akhiri dengan tag: [ACTION:LIGHT_ON], [ACTION:LIGHT_OFF], dll.

### KNOWLEDGE
Kamu memiliki akses ke data keluarga (nama, tanggal lahir) dan data keuangan yang tersimpan di database.
"""

# --- KELAS MEMORI KELUARGA (SQLite Version) ---
class FamilyMemory:
    def __init__(self, db_name="hana_memory.db"):
        self.db_name = db_name
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_name)

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Tabel Anggota Keluarga
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                birthdate TEXT
            )
        ''')
        
        # Tabel Keuangan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS finance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                type TEXT DEFAULT 'expense'
            )
        ''')
        
        conn.commit()
        conn.close()

    def add_member(self, role, name, birthdate):
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO family_members (role, name, birthdate) VALUES (?, ?, ?)", 
                           (role, name, birthdate))
            conn.commit()
            conn.close()
            return f"Data {role} atas nama {name} berhasil disimpan ke database."
        except Exception as e:
            return f"Gagal menyimpan data: {e}"

    def add_finance_log(self, description, amount, type="expense"):
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            today = str(datetime.date.today())
            cursor.execute("INSERT INTO finance_log (date, description, amount, type) VALUES (?, ?, ?, ?)", 
                           (today, description, amount, type))
            conn.commit()
            conn.close()
            return f"Catatan keuangan berhasil disimpan."
        except Exception as e:
            return f"Gagal mencatat keuangan: {e}"

    def get_context_string(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Ambil Data Keluarga
        cursor.execute("SELECT role, name, birthdate FROM family_members")
        rows = cursor.fetchall()
        
        conn.close()
        
        if not rows:
            return "Data Keluarga: Belum ada data."
            
        members_str = ", ".join([f"{r[0]}: {r[1]} (Lahir: {r[2]})" for r in rows])
        return f"Data Keluarga: [{members_str}]"

# --- KELAS OTAK HANA (Offline Version via Ollama) ---
class HanaBrain:
    def __init__(self):
        self.memory = FamilyMemory()
        
    def _ask_ollama(self, prompt, context_text):
        # Menggunakan subprocess untuk memanggil Ollama secara lokal
        full_prompt = f"System: {SYSTEM_PROMPT}\nContext: {context_text}\nUser: {prompt}\nAssistant:"
        
        try:
            # Escape quote untuk command line argument yang aman
            safe_prompt = full_prompt.replace('"', '\\"')
            
            # Command ollama run
            command = f'ollama run {OLLAMA_MODEL} "{safe_prompt}"'
            
            # Eksekusi dengan timeout agar tidak hang
            # stderr=subprocess.STDOUT menggabungkan error ke output untuk debugging
            result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=5)
            return result.decode('utf-8').strip()
        except subprocess.TimeoutExpired:
            print("[Info] Ollama timeout. Beralih ke Mock.")
            return self._mock_fallback(prompt)
        except FileNotFoundError:
            return self._mock_fallback(prompt)
        except subprocess.CalledProcessError as e:
            output = e.output.decode()
            # Jika command not found (di windows kadang beda behavior), switch ke mock
            if "not recognized" in output or "not found" in output or "command not found" in output:
                print(f"[Info] Ollama tidak ditemukan, beralih ke Mode Demo Mock.")
                return self._mock_fallback(prompt)
            return f"Maaf, otak saya (Ollama) sedang error: {output}"
        except Exception as e:
            return f"Error sistem: {str(e)}"

    def _mock_fallback(self, prompt):
        # Fallback sederhana untuk demo tanpa Ollama
        prompt = prompt.lower()
        if "siapa" in prompt:
            return "Saya Hana (Mode Demo), asisten keluarga muslim."
        if "lampu" in prompt:
            return "Baik, lampu saya atur. [ACTION:LIGHT_SWITCH]"
        return "Maaf saya dalam Mode Demo tanpa Ollama. Saya mendengarkan: " + prompt


    def process_input(self, user_text):
        print(f"\n[Brain] Berpikir untuk input: {user_text}")
        
        # 1. Cek Logic Sederhana / Hardcoded
        text_lower = user_text.lower()
        
        # CONTOH LOGIC INSERT MANUAL (Simulasi parser perintah simpan data)
        # "Saya ayah namanya budi lahir 1980" (Sangat simplifikasi)
        if "nama saya" in text_lower and "ayah" in text_lower:
             # Disini idealnya pakai Regex atau LLM extraction, kita hardcode demo
             # Asumsi user bilang: "Saya Ayah nama saya Budi"
             self.memory.add_member("Ayah", "Budi", "1980-01-01")
             return "Salam kenal Ayah Budi, data Anda sudah saya simpan.", []

        if "catat beli" in text_lower:
             # Contoh: "Catat beli beras 50000"
             # Simplifikasi parse
             try:
                 parts = text_lower.split(" ")
                 amount = [int(s) for s in parts if s.isdigit()][0]
                 item = text_lower.replace(str(amount), "").replace("catat beli", "").strip()
                 self.memory.add_finance_log(f"Beli {item}", amount)
                 return f"Siap, pengeluaran {amount} untuk {item} sudah dicatat.", []
             except:
                 pass

        if "jadwal shalat" in text_lower:
            return "Untuk kepastian, silakan cek jam shalat CACube. Biasanya Dzuhur sekitar jam 12.", []
            
        # 2. Ambil Konteks Memori dari SQLite
        context = self.memory.get_context_string()

        # 3. Lempar ke Ollama
        response_text = self._ask_ollama(user_text, context)
        
        # 4. Parse Actions
        verbal_response, actions = self._parse_actions(response_text)
        
        return verbal_response, actions

    def _parse_actions(self, text):
        actions = []
        if "[ACTION:" in text:
            parts = text.split("[ACTION:")
            verbal = parts[0].strip()
            if "]" in parts[1]:
                command = parts[1].split("]")[0]
                actions.append(command)
            return verbal, actions
        return text, []

# Test block
if __name__ == "__main__":
    print("Mencoba koneksi ke Database & Ollama...")
    bot = HanaBrain()
    
    # Test Simpan Data
    print(bot.memory.add_member("Anak", "Fatih", "2015-05-20"))
    
    # Test Baca Data via Context
    print(f"Context saat ini: {bot.memory.get_context_string()}")
    
    res, act = bot.process_input("Siapa saja anggota keluarga ini?")
    print(f"Response: {res}")