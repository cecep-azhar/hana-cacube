import os
import sys
import json
import time
# import pyaudio # Uncomment saat di Raspberry Pi
# import vosk    # Uncomment saat di Raspberry Pi

from brain import HanaBrain

# --- KONFIGURASI PATH ---
# Ganti dengan path model Vosk bahasa Indonesia yang sudah didownload
# Download di: https://alphacephei.com/vosk/models (pilih vosk-model-small-id-0.22)
VOSK_MODEL_PATH = "models/vosk-model-small-id-0.22"

# Piper model path (onnx dan json)
PIPER_MODEL = "models/id_ID-aris-medium.onnx" # Contoh nama model
PIPER_BINARY = "piper" # Pastikan piper sudah terinstall di /usr/bin/ atau PATH

def hana_speak_offline(text):
    """
    Menggunakan Piper TTS untuk mengubah teks menjadi suara (WAV) lalu memutarnya.
    """
    print(f"[Hana Bicara]: {text}")
    
    # Bersihkan teks dari karakter aneh agar command line aman
    safe_text = text.replace('"', '').replace("'", "")
    
    # Command Piper: echo "text" | piper ...
    # aplay untuk memutar hasil audio di Linux (Raspberry Pi)
    cmd = f'echo "{safe_text}" | {PIPER_BINARY} --model {PIPER_MODEL} --output_file response.wav && aplay response.wav'
    
    # Untuk testing di Windows (tanpa piper/aplay), kita hanya print command
    if sys.platform == "win32":
        # print(f"[MOCK AUDIO]: {cmd}")
        pass
    else:
        os.system(cmd)

class HanaHeadless:
    def __init__(self):
        self.brain = HanaBrain()
        self.rec = None
        self.stream = None
        self.pa = None
        
        # Setup Vosk (Error handling jika model belum ada)
        self.setup_vosk()

    def setup_vosk(self):
        try:
            import vosk
            import pyaudio
            
            if not os.path.exists(VOSK_MODEL_PATH):
                print(f"CRITICAL: Model Vosk tidak ditemukan di {VOSK_MODEL_PATH}")
                print("Silakan download model bahasa Indonesia dan ekstrak ke folder models/")
                return

            print("Memuat Model Vosk...")
            model = vosk.Model(VOSK_MODEL_PATH)
            self.rec = vosk.KaldiRecognizer(model, 16000)
            
            self.pa = pyaudio.PyAudio()
            self.stream = self.pa.open(format=pyaudio.paInt16, 
                                       channels=1, 
                                       rate=16000, 
                                       input=True, 
                                       frames_per_buffer=8000)
            print("Vosk STT Siap!")
            
        except ImportError:
            print("Library 'vosk' atau 'pyaudio' belum terinstall.")
            print("Mode Input text manual aktif.")
        except Exception as e:
            print(f"Error inisialisasi Vosk: {e}")

    def run(self):
        print("\n--- HANA CACUBE (OFFLINE MODE) ---")
        hana_speak_offline("Hana siap, assalamualaikum.")

        while True:
            # Jika mic & vosk tersedia
            if self.stream is not None:
                try:
                    data = self.stream.read(4000, exception_on_overflow=False)
                    if self.rec.AcceptWaveform(data):
                        result = json.loads(self.rec.Result())
                        text_input = result.get('text', '')
                        
                        if text_input:
                            self.process_interaction(text_input)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"Error Loop: {e}")
                    break
            else:
                # Fallback ke Text Input (misal testing di PC tanpa Mic/Vosk)
                try:
                    text_input = input("\n[Kamu]: ")
                    if text_input.lower() in ['exit', 'keluar']:
                        break
                    self.process_interaction(text_input)
                except KeyboardInterrupt:
                    break

    def process_interaction(self, user_text):
        # print(f"User (Heard): {user_text}")
        print(f"[Hana Berpikir]:")
        
        # 1. Kirim ke Brain (Ollama)
        response, actions = self.brain.process_input(user_text)
        
        # 2. Respon Suara
        hana_speak_offline(response)
        
        # 3. Eksekusi Hardware Actions
        if actions:
            print(f"[HARDWARE EXECUTION]: {actions}")
            # Disini masukkan kode GPIO Raspberry Pi
            # if 'LIGHT_ON' in actions: GPIO.output(PIN, True)

if __name__ == "__main__":
    app = HanaHeadless()
    app.run()
