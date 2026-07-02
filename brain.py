import os
import json
import datetime
import subprocess
import sqlite3
import sys
import re

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
        text_lower = user_text.lower().strip()
        words = re.findall(r"[a-z0-9]+", text_lower)
        
        # --- LOGIC MANUAL (Cepat & Tanpa AI) ---
        role_map = {
            "ayah": "Ayah", "suami": "Ayah", "bapak": "Ayah",
            "ibu": "Ibu", "istri": "Ibu", "bunda": "Ibu", "mama": "Ibu",
            "anak": "Anak", "putra": "Anak", "putri": "Anak"
        }
        role_keywords = set(role_map.keys())
        add_verbs = ["tambah", "tambahkan", "daftarkan", "input", "masukkan", "masukan", "simpan"]
        question_words = ["siapa", "berapa", "apa", "kapan", "dimana", "di", "mana"]
        stop_words = {
            "lapar", "sakit", "capek", "lelah", "baik", "oke", "siap", "sedih", "senang",
            "saya", "aku", "kami", "kita", "ini", "itu", "ya"
        }

        def is_question():
            return "?" in user_text or any(q in words for q in question_words)

        def parse_gender(text):
            if "laki-laki" in text or "laki laki" in text or "pria" in text:
                return "Laki-laki"
            if "perempuan" in text or "wanita" in text:
                return "Perempuan"
            return "-"

        def parse_age(text):
            match = re.search(r"(\d{1,3})\s*tahun", text)
            if match:
                return int(match.group(1))
            return None

        def extract_name_after_role(tokens, role_word):
            try:
                idx = tokens.index(role_word)
            except ValueError:
                return None

            if idx + 1 < len(tokens) and tokens[idx + 1] in {"saya", "ku", "kami"}:
                idx += 1
            if idx + 1 < len(tokens):
                return " ".join(tokens[idx + 1:]).title()
            return None

        def extract_name_after_markers(tokens, markers):
            for i, word in enumerate(tokens):
                if word in markers and (i + 1) < len(tokens):
                    candidate = tokens[i + 1]
                    if candidate not in stop_words:
                        return " ".join(tokens[i + 1:]).title()
            return None

        def parse_amount(tokens):
            for i, tok in enumerate(tokens):
                if not re.search(r"\d", tok):
                    continue

                raw = re.sub(r"[^\d.,]", "", tok)
                if not raw:
                    continue

                suffix = re.sub(r"[\d.,]", "", tok)
                suffix = suffix.lower()

                next_word = tokens[i + 1] if i + 1 < len(tokens) else ""
                multiplier = 1
                multiplier_word = None

                if suffix in {"ribu", "rb", "k"}:
                    multiplier = 1000
                    multiplier_word = suffix
                elif suffix in {"juta", "jt", "m"}:
                    multiplier = 1000000
                    multiplier_word = suffix
                elif next_word in {"ribu", "rb", "k"}:
                    multiplier = 1000
                    multiplier_word = next_word
                elif next_word in {"juta", "jt", "m"}:
                    multiplier = 1000000
                    multiplier_word = next_word

                if raw.count(".") + raw.count(",") >= 2:
                    num = int(re.sub(r"[.,]", "", raw))
                else:
                    if multiplier > 1:
                        num = float(raw.replace(",", "."))
                    else:
                        if "." in raw or "," in raw:
                            sep = "." if "." in raw else ","
                            parts = raw.split(sep)
                            if len(parts[-1]) == 3 and all(p.isdigit() for p in parts):
                                num = int("".join(parts))
                            else:
                                num = float(raw.replace(",", "."))
                        else:
                            num = int(raw)

                amount = int(num * multiplier)
                return amount, tok, multiplier_word

            return 0, None, None

        # 0. Salam & sapaan singkat
        if any(w in words for w in ["assalamualaikum", "salaam", "salam", "halo", "hai"]):
            return "Waalaikumsalam. Ada yang bisa saya bantu hari ini?", []

        if any(w in words for w in ["waalaikumsalam", "waalaikumussalam", "walaikumsalam", "walaikumussalam","wslm"]) or any(w.startswith("waalaikum") or w.startswith("walaikum") for w in words):
            return "Ada yang bisa saya bantu hari ini?", []
        
        # 0. Parsing Identitas (Ayah/Ibu)
        # Mendukung: "Saya suami bernama Cecep" atau "Saya Ibu namanya Rini"
        if "bernama" in text_lower or "namanya" in text_lower or "nama saya" in text_lower:
            try:
                role = None
                name = None

                detected_roles = []
                for w in words:
                    if w in role_map:
                        detected_roles.append(role_map[w])

                if detected_roles:
                    role = detected_roles[0]
                else:
                    role = "Keluarga"

                markers = ["bernama", "namanya", "nama", "panggil"]
                name = extract_name_after_markers(words, markers)
                             
                if name:
                    gender = parse_gender(text_lower)
                    age = parse_age(text_lower)
                    notes = f"Umur {age} tahun" if age else "-"

                    if gender == "-":
                        if role in ["Ayah", "Suami", "Putra", "Kakek"]:
                            gender = "Laki-laki"
                        elif role in ["Ibu", "Istri", "Putri", "Nenek"]:
                            gender = "Perempuan"

                    self.memory.add_member(role, name, birthdate="0000-00-00", gender=gender, hobbies="-", notes=notes)
                    return f"Salam kenal {role} {name}, data lengkapmu sudah saya simpan.", []
            except Exception as e:
                print(f"Error parsing manual: {e}")
                pass

        # 0b. Parsing Identitas sederhana: "Saya Cecep" atau "Saya Ayah Cecep"
        if text_lower.startswith("saya ") and "bernama" not in text_lower and "namanya" not in text_lower:
            try:
                if len(words) >= 2:
                    second = words[1]
                    if second in role_map and len(words) >= 3:
                        role = role_map[second]
                        name = " ".join(words[2:]).title()
                    elif second not in stop_words:
                        role = "Keluarga"
                        name = " ".join(words[1:]).title()
                    else:
                        name = None

                    if name:
                        gender = parse_gender(text_lower)
                        age = parse_age(text_lower)
                        notes = f"Umur {age} tahun" if age else "-"
                        self.memory.add_member(role, name, birthdate="0000-00-00", gender=gender, hobbies="-", notes=notes)
                        return f"Salam kenal {role} {name}, data lengkapmu sudah saya simpan.", []
            except Exception as e:
                print(f"Error parsing simple identity: {e}")
                pass

        # 0c. Tambah Anggota Keluarga (Command)
        if any(v in words for v in add_verbs) and not is_question() and not any(w in words for w in ["catat", "beli", "jajan", "bayar", "pemasukan", "pengeluaran", "gaji", "uang", "transfer", "terima", "dapat"]):
            try:
                role = None
                name = None

                for w in words:
                    if w in role_keywords:
                        role = role_map[w]
                        name = extract_name_after_role(words, w)
                        break

                if not role and "anak saya" in text_lower:
                    role = "Anak"
                    name = extract_name_after_role(words, "anak")

                age = parse_age(text_lower)
                if not role and age is not None and age <= 18:
                    role = "Anak"

                if not role and words and words[0] in add_verbs:
                    role = "Anak"
                    if len(words) > 1 and words[1] not in stop_words:
                        name = " ".join(words[1:]).title()

                if not role and "anak" not in words and "anak saya" not in text_lower:
                    return "Peran belum jelas. Contoh: 'Tambahkan anak saya Harun'.", []

                if not role:
                    return "Peran belum jelas. Contoh: 'Tambahkan anak saya Harun'.", []

                if not name:
                    return "Nama belum disebutkan. Contoh: 'Tambahkan anak saya Harun'.", []

                gender = parse_gender(text_lower)
                notes = f"Umur {age} tahun" if age else "-"
                self.memory.add_member(role, name, birthdate="0000-00-00", gender=gender, hobbies="-", notes=notes)
                return f"Baik, data {role} {name} sudah saya simpan.", []
            except Exception as e:
                print(f"Error parsing add member: {e}")
                pass

        # 0c1. Hapus Anggota Keluarga
        if "hapus" in words and not is_question():
            try:
                target = " ".join([w for w in words if w not in {"hapus", "data", "anak", "istri", "suami", "ayah", "ibu"}]).title()
                if not target:
                    return "Nama yang mau dihapus belum disebutkan.", []

                conn = self.memory._get_conn()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM family_members WHERE name = ?", (target,))
                affected = cursor.rowcount
                conn.commit()
                conn.close()

                if affected <= 0:
                    return f"Nama {target} tidak ditemukan di data keluarga.", []

                return f"Baik, data {target} sudah saya hapus dari keluarga.", []
            except Exception as e:
                print(f"Error delete member: {e}")
                pass

        # 0c2. Tambah Anak tanpa kata kerja (mis. "anak saya Harun", "anak saya berikutnya Harun")
        if "anak saya" in text_lower and not is_question():
            try:
                name = None
                if "bernama" in words:
                    name = extract_name_after_markers(words, ["bernama"])
                elif "berikutnya" in words:
                    name = extract_name_after_markers(words, ["berikutnya"])
                else:
                    name = extract_name_after_role(words, "anak")

                if not name:
                    return "Nama anak belum disebutkan. Contoh: 'anak saya Harun'.", []

                gender = parse_gender(text_lower)
                age = parse_age(text_lower)
                notes = f"Umur {age} tahun" if age else "-"
                self.memory.add_member("Anak", name, birthdate="0000-00-00", gender=gender, hobbies="-", notes=notes)
                return f"Baik, data Anak {name} sudah saya simpan.", []
            except Exception as e:
                print(f"Error parsing add child: {e}")
                pass

        # 0d. Pertanyaan identitas: "Siapa saya?"
        if "siapa saya" in text_lower:
            conn = self.memory._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT role, name FROM family_members WHERE role IN ('Ayah', 'Ibu', 'Keluarga') ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()

            if not row:
                return "Aku belum tahu namamu. Coba perkenalkan diri dulu, misalnya: 'Saya Cecep'.", []

            role, name = row
            if role == "Keluarga":
                return f"Kamu adalah {name}.", []
            return f"Kamu adalah {role} {name}.", []

        # 1. Laporan Keuangan (Detail)
        if "laporan" in words and ("pengeluaran" in words or "pemasukan" in words):
            conn = self.memory._get_conn()
            cursor = conn.cursor()

            if "pengeluaran" in words:
                cursor.execute("SELECT date, description, amount FROM finance_log WHERE type = 'expense' ORDER BY id DESC")
                label = "Pengeluaran"
            else:
                cursor.execute("SELECT date, description, amount FROM finance_log WHERE type = 'income' ORDER BY id DESC")
                label = "Pemasukan"

            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return f"Belum ada {label.lower()} yang tersimpan.", []

            lines = [f"{label} (Terbaru -> Lama):"]
            for date, desc, amount in rows:
                lines.append(f"- {date}: {desc} (Rp{amount:,.0f})")

            return "\n".join(lines), []
        
        # 1. Cek Catat Keuangan Smart
        # Keyword triggers: "catat", "beli", "jajan", "bayar", "pemasukan", "pengeluaran", "gaji"
        finance_keywords = ["catat", "beli", "jajan", "bayar", "pemasukan", "pengeluaran", "gaji", "uang", "transfer", "terima", "dapat"]
        if any(w in words for w in finance_keywords) and not is_question():
            try:
                ftype = "expense"
                if "pemasukan" in text_lower or "gaji" in text_lower or "dapat uang" in text_lower:
                    ftype = "income"
                
                amount, num_token, mult_token = parse_amount(words)

                if amount <= 0:
                    return "Nominalnya berapa? Contoh: 'catat jajan 10 ribu'.", []

                drop_words = set(finance_keywords + ["ribu", "juta", "rb", "jt", "k", "m", "rp", "rupiah", "hari", "ini", "buat", "untuk", "ke"])
                if num_token:
                    drop_words.add(num_token)
                if mult_token:
                    drop_words.add(mult_token)

                desc_tokens = [w for w in words if w not in drop_words]
                desc_text = " ".join(desc_tokens).strip()
                if not desc_text:
                    desc_text = "Umum"

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
            return (
                "Laporan Keuangan:\n"
                f"- Total Pemasukan: Rp{income:,.0f}\n"
                f"- Total Pengeluaran: Rp{expense:,.0f}\n"
                f"- Sisa Saldo: Rp{bal:,.0f}"
            ), []

        # 2b. Cek Transaksi Terakhir
        if "terakhir" in words and ("transaksi" in words or "jajan" in words or "pengeluaran" in words or "pemasukan" in words):
            conn = self.memory._get_conn()
            cursor = conn.cursor()

            if "pemasukan" in words:
                cursor.execute("SELECT date, description, amount FROM finance_log WHERE type = 'income' ORDER BY id DESC LIMIT 1")
                label = "Pemasukan"
            elif "jajan" in words or "pengeluaran" in words:
                cursor.execute("SELECT date, description, amount FROM finance_log WHERE type = 'expense' ORDER BY id DESC LIMIT 1")
                label = "Pengeluaran"
            else:
                cursor.execute("SELECT date, description, amount, type FROM finance_log ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                conn.close()

                if not row:
                    return "Belum ada transaksi yang tersimpan.", []

                date, desc, amount, ftype = row
                label = "Pemasukan" if ftype == "income" else "Pengeluaran"
                return f"Transaksi terakhir: {label} {desc} (Rp{amount:,.0f}) pada {date}.", []

            row = cursor.fetchone()
            conn.close()

            if not row:
                return f"Belum ada {label.lower()} yang tersimpan.", []

            date, desc, amount = row
            return f"{label} terakhir: {desc} (Rp{amount:,.0f}) pada {date}.", []

        # 2c. Cek Tanya Total Pengeluaran
        if "pengeluaran" in text_lower and ("total" in text_lower or "semua" in text_lower or is_question()):
            conn = self.memory._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT amount FROM finance_log WHERE type = 'expense'")
            rows = cursor.fetchall()
            conn.close()

            total_expense = sum([x[0] for x in rows])
            return f"Total pengeluaran kamu saat ini: Rp{total_expense:,.0f}", []

        # 2d. Cek Tanya Total Pemasukan
        if "pemasukan" in text_lower and ("total" in text_lower or "semua" in text_lower or is_question()):
            conn = self.memory._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT amount FROM finance_log WHERE type = 'income'")
            rows = cursor.fetchall()
            conn.close()

            total_income = sum([x[0] for x in rows])
            return f"Total pemasukan kamu saat ini: Rp{total_income:,.0f}", []

        # 2e. Cek Tanya Anak di Keluarga
        if "anak" in text_lower and ("anak saya" in text_lower or "anak di keluarga" in text_lower or is_question()):
            conn = self.memory._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM family_members WHERE role = 'Anak'")
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return "Data anak belum ada di database.", []

            names = ", ".join([r[0] for r in rows])
            return f"Anak di keluarga ini: {names}.", []

        # 2f. Cek Tanya Peran Keluarga Lain
        if "siapa" in text_lower or (is_question() and any(k in words for k in role_keywords)):
            for key, role in role_map.items():
                if key in words:
                    conn = self.memory._get_conn()
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM family_members WHERE role = ?", (role,))
                    rows = cursor.fetchall()
                    conn.close()

                    if not rows:
                        return f"Data {role.lower()} belum ada di database.", []

                    names = ", ".join([r[0] for r in rows])
                    return f"{role} di keluarga ini: {names}.", []

        # 3. Cek Jadwal Shalat (Hardcode sementara)
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