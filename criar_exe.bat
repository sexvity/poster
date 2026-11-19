@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name "YTK-SHORTS" --icon ytk.ico --add-data "ytk.ico;." --add-data "ytk.png;." --add-data "ytk.png;." --collect-all customtkinter --collect-submodules PIL --collect-all imageio_ffmpeg --collect-data googleapiclient --collect-data tzdata app.py
echo.
echo Done! The program is at dist\YTK-SHORTS.exe
echo Your settings are saved in %%APPDATA%%\YTK SHORTS
pause
