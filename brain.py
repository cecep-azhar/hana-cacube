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
        
        # Tabel Anggota Keluarga (Basic)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                name TEXT,
                birthdate TEXT
            )
        ''')
        
        # --- MIGRATION: Tambah Kolom Baru (Jika belum ada) ---
        # Kita check apakah kolom gender/hobbies sudah ada
        cursor.execute("PRAGMA table_info(family_members)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'gender' not in columns:
            print("[DB] Migrasi: Menambah kolom gender...")
            cursor.execute("ALTER TABLE family_members ADD COLUMN gender TEXT")
            
        if 'hobbies' not in columns:
            print("[DB] Migrasi: Menambah kolom hobbies...")
            cursor.execute("ALTER TABLE family_members ADD COLUMN hobbies TEXT")
            
        if 'notes' not in columns:
            print("[DB] Migrasi: Menambah kolom notes TEXT")
            cursor.execute("ALTER TABLE family_members ADD COLUMN notes TEXT")

        # Tabel Keuangan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS finance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, description TEXT, amount REAL, type TEXT DEFAULT 'expense'
            )
        ''')
        conn.commit()
        conn.close()

    def add_member(self, role, name, birthdate="0000-00-00", gender="-", hobbies="-", notes="-"):
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Cek apakah nama ini sudah ada? (Update jika ada)
            cursor.execute("SELECT id FROM family_members WHERE name = ? AND role = ?", (name, role))
            data = cursor.fetchone()
            
            if data:
                # Update Existing
                cursor.execute("""
                    UPDATE family_members 
                    SET birthdate=?, gender=?, hobbies=?, notes=?
                    WHERE id=?
                """, (birthdate, gender, hobbies, notes, data[0]))
                action = "diperbarui"
            else:
                # Insert New
                cursor.execute("""
                    INSERT INTO family_members (role, name, birthdate, gender, hobbies, notes) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (role, name, birthdate, gender, hobbies, notes))
                action = "tersimpan"
                
            conn.commit()
            conn.close()
            return f"Data {role} atas nama {name} berhasil {action} (Gender: {gender}, Hobi: {hobbies})."
        except Exception as e:
            return f"Gagal simpan DB: {e}"

    def add_finance_log(self, description, amount, type="expense"):
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            today = str(datetime.date.today())
            cursor.execute("INSERT INTO finance_log (date, description, amount, type) VALUES (?, ?, ?, ?)", 
                           (today, description, amount, type))
            conn.commit()
            conn.close()
            return f"Catatan {type} tersimpan."
        except Exception as e:
            return f"Gagal catat uang: {e}"

    def get_context_string(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 1. Data Keluarga
        cursor.execute("SELECT role, name, birthdate, gender, hobbies FROM family_members")
        rows = cursor.fetchall()
        
        if not rows:
            family_str = "Data Keluarga: (Kosong)"
        else:
            members = [f"- {r[0]} {r[1]} ({r[3]}, Hobi: {r[4]})" for r in rows]
            family_str = "Data Keluarga:\n" + "\n".join(members)

        # 2. Data Keuangan (Summary)
        cursor.execute("SELECT type, amount, description FROM finance_log")
        logs = cursor.fetchall()
        
        total_income = sum([x[1] for x in logs if x[0] == 'income'])
        total_expense = sum([x[1] for x in logs if x[0] == 'expense'])
        balance = total_income - total_expense
        
        # Ambil 3 Transaksi Terakhir
        cursor.execute("SELECT date, description, amount, type FROM finance_log ORDER BY id DESC LIMIT 3")
        last_tx = cursor.fetchall()
        tx_str = ", ".join([f"{t[1]} ({t[3]}: {t[2]})" for t in last_tx])
        
        finance_str = f"""
Data Keuangan:
- Total Pemasukan: Rp{total_income:,.0f}
- Total Pengeluaran: Rp{total_expense:,.0f}
- Sisa Saldo: Rp{balance:,.0f}
- Transaksi Terakhir: {tx_str}
"""
        conn.close()
        return f"{family_str}\n\n{finance_str}"

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
                    # Infer Gender sederhana dari Role
                    gender = "-"
                    if role in ["Ayah", "Suami", "Putra", "Kakek"]: gender = "Laki-laki"
                    elif role in ["Ibu", "Istri", "Putri", "Nenek"]: gender = "Perempuan"
                    
                    self.memory.add_member(role, name, birthdate="0000-00-00", gender=gender, hobbies="-")
                    return f"Salam kenal {role} {name}, data lengkapmu sudah saya simpan.", []
            except Exception as e:
                print(f"Error parsing manual: {e}")
                pass
        
                pass
        
        # 1. Cek Catat Keuangan Smart
        # Keyword triggers: "catat", "beli", "jajan", "bayar", "pemasukan", "pengeluaran", "gaji"
        finance_keywords = ["catat", "beli", "jajan", "bayar", "pemasukan", "pengeluaran", "gaji", "uang"]
        if any(w in text_lower for w in finance_keywords):
            try:
                # A. Tentukan Tipe (Income/Expense)
                ftype = "expense" # Default pengeluaran
                if "pemasukan" in text_lower or "gaji" in text_lower or "dapat uang" in text_lower:
                    ftype = "income"
                
                # B. Cari Angka (Support "100 ribu", "1.5 juta")
                # Split text, cari digit
                parts = text_lower.split()
                amount = 0
                
                for i, word in enumerate(parts):
                    # Bersihkan Rp/titik/koma
                    clean_word = word.replace("rp", "").replace(".", "").replace(",", "")
                    if clean_word.isdigit():
                        val = int(clean_word)
                        # Cek multiplier di kata berikutnya (ribu, juta)
                        if i + 1 < len(parts):
                            next_word = parts[i+1]
                            if "ribu" in next_word or "rb" in next_word:
                                val *= 1000
                            elif "juta" in next_word or "jt" in next_word:
                                val *= 1000000
                        amount = val
                        break # Ambil angka pertama aja
                
                if amount > 0:
                    # C. Cari Deskripsi (Hapus angka & keyword)
                    # Cara simple: hapus angka yang ketemu, hapus keyword trigger
                    desc_text = text_lower
                    triggers = finance_keywords + ["ribu", "juta", "rb", "jt", "rp", str(amount)]
                    for t in triggers:
                         desc_text = desc_text.replace(t, "")
                    
                    desc_text = desc_text.strip()
                    if not desc_text: desc_text = "Umum"
                    
                    msg = self.memory.add_finance_log(desc_text.title(), amount, ftype)
                    return f"Siap, {msg} ({desc_text}: Rp{amount:,.0f})", []
            except Exception as e:
                print(f"Error parsing finance: {e}")
                pass
        
        # 2. Cek Tanya Saldo Manual (Cepat)
        if "uang saya" in text_lower or "saldo" in text_lower or "sisa uang" in text_lower:
            conn = self.memory._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT type, amount FROM finance_log")
            logs = cursor.fetchall()
            conn.close()
            
            income = sum([x[1] for x in logs if x[0] == 'income'])
            expense = sum([x[1] for x in logs if x[0] == 'expense'])
            bal = income - expense
            return f"Laporan Keuangan: Total Pemasukan Rp{income:,.0f}, Pengeluaran Rp{expense:,.0f}. Sisa Saldo saat ini: Rp{bal:,.0f}", []

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