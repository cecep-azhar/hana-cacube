import os
import json
import datetime
import subprocess
import sqlite3
import sys

# --- KONFIGURASI ---
# Pastikan model ini sudah di-pull: ollama pull gemma3:270m
OLLAMA_MODEL = "gemma3:270m" 

SYSTEM_PROMPT = """
### ROLE
Aku adalah "Hana", Asisten Keluarga Muslim di dalam CACube.
Karakter: Ramah, sabar, Islami, modern.
Lokasi: Cileunyi, Jawa Barat.
Aturan: Jawab SINGKAT (maksimal 3 kalimat).
Jika user minta kendali hardware, akhiri dengan: [ACTION:LIGHT_ON], [ACTION:LIGHT_OFF].

### KNOWLEDGE
Gunakan data konteks yang diberikan untuk menjawab pertanyaan personal.
"""

# --- 1. MEMORI KELUARGA (SQLite) ---
class FamilyMemory:
    def __init__(self, db_name="hana_memory.db"):
        self.db_name = db_name
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_name)

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        # Tabel Anggota
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT, name TEXT, birthdate TEXT
            )
        ''')
        # Tabel Keuangan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS finance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, description TEXT, amount REAL, type TEXT DEFAULT 'expense'
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
            return f"Data {role} bernama {name} tersimpan."
        except Exception as e:
            return f"Gagal simpan DB: {e}"

    def add_finance_log(self, description, amount):
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            today = str(datetime.date.today())
            cursor.execute("INSERT INTO finance_log (date, description, amount) VALUES (?, ?, ?)", 
                           (today, description, amount))
            conn.commit()
            conn.close()
            return "Catatan keuangan tersimpan."
        except Exception as e:
            return f"Gagal catat uang: {e}"

    def get_context_string(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT role, name, birthdate FROM family_members")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "Data Keluarga: (Kosong)"
        
        members = [f"{r[0]}: {r[1]} ({r[2]})" for r in rows]
        return "Data Keluarga: " + ", ".join(members)

# --- 2. OTAK HANA (Ollama Integration) ---
class HanaBrain:
    def __init__(self):
        self.memory = FamilyMemory()
        
    def _ask_ollama(self, prompt, context_text):
        # Format Prompt Lengkap
        full_input = f"{SYSTEM_PROMPT}\n\n[CONTEXT DARI DATABASE]\n{context_text}\n\nUser: {prompt}\nHana:"
        
        # print(f"[Brain] Sending to {OLLAMA_MODEL}...")
        
        # Percobaan Terakhir: API Generate paling sederhana (Raw Input -> Raw Output)
        # Menghapus sementara System Prompt kompleks yang membuat model kecil bingung/diam.
        import urllib.request
        import json
        
        url = "http://localhost:11434/api/generate"
        
        # Prompt Engineering khusus Model Nano (Gemma 3 270M)
        # Model sekecil ini lebih patuh pada format "Completion" daripada "Chat".
        # Kita pandu dia untuk melengkapi kalimat setelah "Jawaban:".
        
        final_prompt = f"""Instruksi: Kamu berperan sebagai Hana. Jawab pertanyaan berikut dengan ramah. Gunakan kata ganti "Aku" untuk dirimu.
Data: {context_text}

Pertanyaan: {prompt}
Jawaban (sebagai Hana):"""
        
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": final_prompt,
            "stream": False,
            "options": {
                "temperature": 0.5 # Kurangi kreatifitas agar lebih deterministik
            }
        }
        
        try:
            # print(f"[Brain] Mengirim request ke {url}...")
            json_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=json_data, headers={'Content-Type': 'application/json'})
            
            with urllib.request.urlopen(req, timeout=120) as response:
                 response_raw = response.read().decode('utf-8')
                 
                 # DEBUG: Lihat apa yang SEBENARNYA dikirim Ollama
                 # print(f"[DEBUG RAW]: {response_raw[:100]}...") 
                 
                 data = json.loads(response_raw)
                 output_text = data.get('response', '')
                 
                 # print(f"[Brain] Raw Output: '{output_text}'")
                 
                 if not output_text.strip():
                     return "Maaf, saya bingung."
                 
                 return output_text.strip()
                 
        except Exception as e:
             print(f"[Error API] {e}")
             return f"Error: {str(e)}"

    def _parse_actions(self, text):
        # Memisahkan Kata-kata Hana dengan Perintah Hardware
        actions = []
        clean_text = text
        
        if "[ACTION:" in text:
            parts = text.split("[ACTION:")
            clean_text = parts[0].strip() # Ambil kata-kata saja
            
            # Ambil semua action yang mungkin ada
            for part in parts[1:]:
                if "]" in part:
                    cmd = part.split("]")[0]
                    actions.append(cmd)
                    
        return clean_text, actions

    def process_input(self, user_text):
        text_lower = user_text.lower()
        
        # --- LOGIC MANUAL (Cepat & Tanpa AI) ---
        
        # 0. Parsing Identitas (Ayah/Ibu)
        # Mendukung: "Saya suami bernama Cecep" atau "Saya Ibu namanya Rini"
        if "bernama" in text_lower or "namanya" in text_lower or "nama saya" in text_lower:
            try:
                role = None
                name = None
                
                # Mapping kata kunci ke Role Database
                role_map = {
                    "ayah": "Ayah", "suami": "Ayah", "bapak": "Ayah",
                    "ibu": "Ibu", "istri": "Ibu", "bunda": "Ibu", "mama": "Ibu",
                    "anak": "Anak", "putra": "Anak", "putri": "Anak"
                }

                # 1. Tentukan Role
                # Prioritas: Kata role yang muncul SETELAH kata "saya" (e.g. "Saya Suami...")
                # Jika tidak ada "saya", ambil role pertama yang ketemu.
                words = text_lower.split()
                
                detected_roles = []
                for w in words:
                    if w in role_map:
                        detected_roles.append(role_map[w])
                
                # Simple heuristic: Ambil yang pertama deteksi, atau 'Ayah' kalau ada kata 'suami'
                if detected_roles:
                    role = detected_roles[0] 
                else:
                    role = "Keluarga" # Default

                # 2. Tentukan Nama
                # Strategi: Cari kata setelah marker ("bernama", "namanya", "nama")
                markers = ["bernama", "namanya", "nama", "panggil"]
                
                for i, word in enumerate(words):
                    if word in markers and (i+1) < len(words):
                         candidate = words[i+1]
                         # Filter kata umum
                         if candidate not in ["seorang", "adalah", "itu", "dan", "saya", "yang"]:
                             name = candidate.title()
                             break
                             
                if name:
                    self.memory.add_member(role, name, "0000-00-00")
                    return f"Salam kenal {role} {name}, data sudah tersimpan.", []
            except Exception as e:
                print(f"Error parsing manual: {e}")
                pass
        
        # 1. Cek Catat Keuangan
        if "catat beli" in text_lower:
            try:
                # Ambil angka pertama yang ditemukan
                parts = text_lower.split()
                amount = next((int(s) for s in parts if s.isdigit()), None)
                
                if amount:
                    item = text_lower.replace(str(amount), "").replace("catat beli", "").strip()
                    msg = self.memory.add_finance_log(f"Beli {item}", amount)
                    return f"Siap, {msg} ({item}: Rp{amount})", []
                else:
                    return "Berapa harganya? Sebutkan angkanya ya.", []
            except Exception as e:
                print(f"Error parsing: {e}")

        # 2. Cek Jadwal Shalat (Hardcode sementara)
        if "jadwal shalat" in text_lower:
            return "Dzuhur hari ini jam 12:05. Jangan lupa wudhu ya.", []

        # --- LOGIC AI (Ollama) ---
        context = self.memory.get_context_string()
        response_text = self._ask_ollama(user_text, context)
        
        verbal, actions = self._parse_actions(response_text)
        return verbal, actions

# --- TESTING ---
if __name__ == "__main__":
    bot = HanaBrain()
    
    print("\n--- TEST 1: Tambah Data ---")
    print(bot.memory.add_member("Anak", "Fatih", "2015-05-20"))
    
    print("\n--- TEST 2: Tanya Database (Harus pakai AI) ---")
    res, act = bot.process_input("Siapa nama anak di keluarga ini?")
    print(f"Hana: {res}")
    
    print("\n--- TEST 3: Hardware Action ---")
    # Kita paksa prompt seolah minta nyalakan lampu
    res, act = bot.process_input("Hana, tolong nyalakan lampunya dong, gelap nih.")
    print(f"Hana: {res}")
    print(f"Action Hardware: {act}") # Harusnya keluar ['LIGHT_ON']