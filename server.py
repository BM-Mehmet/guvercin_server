import subprocess

# Flask servislerini çalıştıran Python dosyalarının yolları
scripts = [
    "chat.py",
    "home.py",
    "login.py",
    "register.py",
    "search.py"
]

processes = []

# Her bir servisi çalıştır
for script in scripts:
    print(f"API başlatıldı: {script}...")
    process = subprocess.Popen(
        ["python3", script], 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        text=True
    )
    processes.append(process)

# Servislerin çıktısını gösterme
for i, process in enumerate(processes):
    stdout, stderr = process.communicate()  # Çıktıları ve hataları yakala
    if stdout:
        print(f"Çıktılar ({scripts[i]}):\n{stdout}")
    if stderr:
        print(f"Hata ({scripts[i]}):\n{stderr}")

