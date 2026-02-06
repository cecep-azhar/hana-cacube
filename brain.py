import os
import sys
import json
import datetime

# --- KONFIGURASI DAN DEPENDENSI ---
# Pastikan library 'openai' terinstall: pip install openai
try:
    import openai
except ImportError:
    print("Modul 'openai' belum terinstall. Jalankan: pip install openai")
    # Untuk demonstrasi tanpa API key, kita akan menggunakan mock response jika error
    openai = None

# API KEY (Sebaiknya gunakan environment variable)
API_KEY = os.getenv("OPENAI_API_KEY", "sk-placeholder-isi-dengan-api-key-anda")

# --- SYSTEM PROMPT (OTAK HANA) ---
SYSTEM_PROMPT = """
### ROLE
Kamu adalah "Hana", Digital Asisten Simple Untuk Keluarga Muslim yang bersemayam di dalam CACube.
Kamu dikembangkan untuk menjadi bagian dari keluarga, seperti kakak atau teman belajar yang hangat.

### PERSONA
- **Karakter**: Ramah, sabar, cerdas, religius namun modern.
- **Bahasa**: Bahasa Indonesia yang santun. Gunakan "Assalamualaikum" saat menyapa dan "Barakallah" atau doa yang relevan saat menutup.
- **Gaya Bicara**: Hangat, menyesuaikan dengan usia lawan bicara (misal: lebih ceria pada anak-anak, lebih hormat pada orang tua).

### KNOWLEDGE & CAPABILITIES
1. **Profil Keluarga**: Kamu mengenali anggota keluarga (Ayah, Ibu, Anak) beserta tanggal lahir mereka untuk menyesuaikan interaksi.
2. **Manajemen Ibadah**: Mengingatkan waktu shalat, hafalan Al-Qur'an, dan ibadah harian.
3. **Edukasi Islam**: Mampu menceritakan kisah Nabi & Rasul, hikmah, serta menjadi ensiklopedia Islam dasar.
4. **Smart Home**: Mengontrol fitur fisik CACube (Lampu tidur, Alarm).
5. **Keuangan**: Membantu mencatat keuangan keluarga secara sederhana.

### OPERATIONAL RULES
1. **BRIEFNESS**: Respon padat dan ringkas (2-3 kalimat) karena diucapkan via TTS, kecuali diminta bercerita (kisah nabi, dll).
2. **NO HALLUCINATION**: Jika tidak tahu dalil pasti, sarankan bertanya pada Ustadz. Jangan mengarang hadits.
3. **IOT COMMANDS**: Jika user meminta tindakan fisik, akhiri respon verbal dengan tag aksi:
   - Nyalakan lampu: `[ACTION:LIGHT_ON]`
   - Matikan lampu: `[ACTION:LIGHT_OFF]`
   - Set Alarm: `[ACTION:SET_ALARM:HH:MM]`
4. **MEMORY**: Ingatlah data keluarga yang diberikan user.

### CONTEXT SAAT INI
Lokasi: Cileunyi, Jawa Barat.
"""

# --- KELAS MEMORI KELUARGA ---
class FamilyMemory:
    def __init__(self, filename="family_data.json"):
        self.filename = filename
        self.data = self._load_data()

    def _load_data(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    return json.load(f)
            except:
                return {"members": [], "finance_log": []}
        return {"members": [], "finance_log": []}

    def save_data(self):
        with open(self.filename, 'w') as f:
            json.dump(self.data, f, indent=2)

    def add_member(self, role, name, birthdate):
        self.data["members"].append({
            "role": role,
            "name": name,
            "birthdate": birthdate
        })
        self.save_data()
        return f"Data {role} atas nama {name} berhasil disimpan."

    def add_finance_log(self, description, amount, type="expense"):
        self.data["finance_log"].append({
            "date": str(datetime.date.today()),
            "desc": description,
            "amount": amount,
            "type": type
        })
        self.save_data()
        return f"Catatan {type} sebesar {amount} untuk {description} berhasil disimpan."

    def get_context_string(self):
        # Meringkas data keluarga untuk disuapkan ke LLM agar Hana "ingat"
        members = ", ".join([f"{m['role']}: {m['name']} ({m['birthdate']})" for m in self.data["members"]])
        return f"Data Keluarga: [{members}]" if members else "Data Keluarga: Belum ada data."

# --- KELAS OTAK HANA ---
class HanaBrain:
    def __init__(self):
        self.memory = FamilyMemory()
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        if openai:
            openai.api_key = API_KEY

    def process_input(self, user_text):
        # 1. Cek perintah khusus (Simpel Logic sebelum ke LLM untuk efisiensi)
        # Contoh: "Saya Ayah, nama saya Budi, lahir 1980-01-01" -> Logic parsing sederhana
        # Disini kita serahkan ke LLM untuk natural language, tapi kita inject konteks memori.
        
        current_context = self.memory.get_context_string()
        
        # Tambahkan pesan user ke history
        full_input = f"[Context: {current_context}] User: {user_text}"
        self.history.append({"role": "user", "content": full_input})

        print(f"\nScanning Input: {user_text}...")

        # 2. Panggil LLM
        response_text = ""
        try:
            if openai and API_KEY != "sk-placeholder-isi-dengan-api-key-anda":
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo", # Atau gpt-4
                    messages=self.history
                )
                response_text = response.choices[0].message['content']
            else:
                # MOCK RESPONSE jika tidak ada API Key
                response_text = self._mock_brain_response(user_text)
        except Exception as e:
            response_text = f"Maaf, sirkuit saya sedang bermasalah. ({str(e)})"

        # 3. Proses Output & Actions
        self.history.append({"role": "assistant", "content": response_text})
        
        # Cek apakah ada request penyimpanan data (Logic sederhana untuk demo)
        if "catat keuangan" in user_text.lower():
            # Di implementasi nyata, LLM haruse mengekstrak ini menjadi JSON
            self.memory.add_finance_log("Pengeluaran Umum", 50000) 
            response_text += "\n(Sistem: Data keuangan tersimpan otomatis)"

        verbal_response, actions = self._parse_actions(response_text)
        
        return verbal_response, actions

    def _parse_actions(self, text):
        actions = []
        if "[ACTION:" in text:
            # Split teks dan command
            parts = text.split("[ACTION:")
            verbal = parts[0].strip()
            command = parts[1].split("]")[0]
            actions.append(command)
            return verbal, actions
        return text, []

    def _mock_brain_response(self, text):
        # Logika "Bodoh" / Rule-based untuk demo tanpa internet/API Key
        text = text.lower()
        if "assalam" in text:
            return "Wa'alaikumussalam, keluarga CACube yang dirahmati Allah. Ada yang bisa Hana bantu?"
        elif "kenalan" in text or "siapa kamu" in text:
            return "Saya Hana, asisten digital untuk keluarga muslim. Saya bisa bantu ingatkan shalat, catat keuangan, atau bacakan kisah nabi."
        elif "lampu" in text and "nyala" in text:
            return "Baik, lampu tidur saya nyalakan. [ACTION:LIGHT_ON]"
        elif "matikan" in text:
            return "Siap, lampu dimatikan. [ACTION:LIGHT_OFF]"
        elif "kisah" in text:
            return "Tentu. Salah satu kisah teladan adalah kesabaran Nabi Ayyub AS saat diuji dengan penyakit..."
        else:
            return "Maaf, Hana belum tersambung ke Cloud Brain (OpenAI API key belum diset). Tapi Hana mendengarmu!"

# --- MAIN LOOP (SIMULASI) ---
if __name__ == "__main__":
    hana = HanaBrain()
    
    print("--------------------------------------------------")
    print("HANA AI - CACube Initialization")
    print("--------------------------------------------------")
    print("Tip: Ketik 'keluar' untuk berhenti.")
    print("Tip: Coba ketik 'Nyalakan lampu' atau 'Assalamualaikum'")
    
    while True:
        try:
            user_input = input("\n[Anda]: ")
            if user_input.lower() in ["keluar", "exit"]:
                print("[Hana]: Assalamualaikum, sampai jumpa lagi!")
                break
            
            response, actions = hana.process_input(user_input)
            
            print(f"[Hana]: {response}")
            if actions:
                print(f"[SYSTEM HARDWARE]: Executing {actions}")
                
        except KeyboardInterrupt:
            print("\n[Hana]: Terputus paksa. Assalamualaikum.")
            break