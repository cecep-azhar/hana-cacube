# Petunjuk Instalasi Offline Hana-CACube

## 1. Persiapan Hardware
- Raspberry Pi (rekomendasi Pi 4 atau 5 dengan RAM 4GB+)
- Speaker (Jack 3.5mm atau USB)
- Microphone (USB)

## 2. Instalasi Software (Raspberry Pi OS)

### Sistem
Update sistem terlebih dahulu:
```bash
sudo apt update && sudo apt upgrade
sudo apt install python3-pip portaudio19-dev
```

### Library Python
Install dependensi Python:
```bash
pip install -r requirements.txt
```
*(Catatan: pyaudio dan vosk butuh waktu untuk build)*

### 3. Setup Model AI Offline

#### A. Ollama (Otak)
Install Ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```
Download model ringan (TinyLlama):
```bash
ollama pull tinyllama
```

#### B. Vosk (Telinga)
Download model bahasa Indonesia:
1. Buka https://alphacephei.com/vosk/models
2. Download `vosk-model-small-id-0.22`
3. Ekstrak folder hasil download ke dalam folder `models/` di project ini.
   Structure harus: `hana-cacube/models/vosk-model-small-id-0.22/`

#### C. Piper (Mulut)
Install Piper text-to-speech:
```bash
# Contoh install piper (binary)
wget -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_linux_aarch64.tar.gz
tar -xvf piper.tar.gz
sudo mv piper /usr/local/bin/
```
Download Model Suara Indonesia:
- Cari model `id_ID` (Aris atau lainnya) di huggingface rhasspy/piper-voices.
- Simpan `.onnx` dan `.json` config-nya ke folder `models/`.

## 4. Menjalankan Hana
Jalankan script utama:
```bash
python3 main.py
```

## Troubleshooting
- **Error PyAudio**: Pastikan `portaudio19-dev` terinstall.
- **Lambat?**: Pastikan pendingin Raspberry Pi terpasang karena TinyLlama menggunakan CPU cukup intensif.
