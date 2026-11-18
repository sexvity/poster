"""Abre o YTK sem janela de console: mostra uma telinha de carregamento, instala o que faltar e inicia o app.

Só usa o tkinter que vem com o Python, porque as outras bibliotecas podem ainda não estar instaladas.
"""
import importlib
import importlib.util
import os
import queue
import subprocess
import sys
import threading
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

BG, TEXTO, MUTED, ACENTO, TRILHO = "#0D0F14", "#E8EAF0", "#8B91A1", "#6366F1", "#232834"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# módulo que se importa -> o que checar
MODULOS = ["requests", "googleapiclient", "google_auth_oauthlib", "google_auth_httplib2", "imageio_ffmpeg",
           "customtkinter", "tzdata", "PIL"]


def faltando():
    return [m for m in MODULOS if importlib.util.find_spec(m) is None]


def python_com_console():
    """O pip roda com python.exe (pythonw.exe não tem saída), mas sem abrir janela."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        candidato = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(candidato):
            return candidato
    return exe


def instalar(log):
    """Roda 'pip install -r requirements.txt' sem janela e manda as linhas para `log`. Devolve True se deu certo."""
    cmd = [python_com_console(), "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=SEM_JANELA,
                         cwd=BASE, text=True, encoding="utf-8", errors="replace")
    ultimas = []
    for linha in p.stdout:
        linha = linha.strip()
        if linha:
            ultimas.append(linha)
            log(linha)
    p.wait()
    if p.returncode != 0:
        log("Installation failed:\n" + "\n".join(ultimas[-6:]))
    return p.returncode == 0


def main():
    import tkinter as tk

    raiz = tk.Tk()
    raiz.title("YTK SHORTS")
    raiz.configure(bg=BG)
    larg, alt = 420, 300
    raiz.geometry(f"{larg}x{alt}+{(raiz.winfo_screenwidth() - larg) // 2}+{(raiz.winfo_screenheight() - alt) // 3}")
    raiz.resizable(False, False)
    raiz.overrideredirect(True)  # sem barra de título: só o cartão

    borda = tk.Frame(raiz, bg=TRILHO)
    borda.pack(fill="both", expand=True)
    corpo = tk.Frame(borda, bg=BG)
    corpo.pack(fill="both", expand=True, padx=1, pady=1)

    tk.Label(corpo, text="▶", bg=ACENTO, fg="white", font=("Segoe UI", 16, "bold"), width=2).pack(pady=(34, 8))
    tk.Label(corpo, text="YTK SHORTS", bg=BG, fg=TEXTO, font=("Segoe UI", 18, "bold")).pack()

    canvas = tk.Canvas(corpo, width=44, height=44, bg=BG, highlightthickness=0)
    canvas.pack(pady=(22, 10))
    canvas.create_oval(5, 5, 39, 39, outline=TRILHO, width=3)
    arco = canvas.create_arc(5, 5, 39, 39, start=90, extent=90, style="arc", outline=ACENTO, width=3)

    estado = tk.Label(corpo, text="Starting...", bg=BG, fg=TEXTO, font=("Segoe UI", 11))
    estado.pack()
    detalhe = tk.Label(corpo, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=370, justify="center")
    detalhe.pack(pady=(4, 0))

    angulo = [90]

    def girar():
        angulo[0] = (angulo[0] - 9) % 360
        canvas.itemconfigure(arco, start=angulo[0])
        raiz.after(25, girar)

    girar()

    fila = queue.Queue()  # mensagens da thread de trabalho para a tela

    def trabalho():
        try:
            if faltando():
                fila.put(("estado", "Installing missing components (first run only)..."))
                if not instalar(lambda linha: fila.put(("detalhe", linha[:110]))):
                    fila.put(("erro", "Could not install the libraries.\nCheck your internet connection and try again."))
                    return
            fila.put(("estado", "Opening YTK SHORTS..."))
            fila.put(("detalhe", ""))
            for modulo in ("customtkinter", "PIL", "requests", "googleapiclient"):  # aquecimento: são os mais lentos
                importlib.import_module(modulo)
            fila.put(("pronto", None))
        except Exception:  # noqa: BLE001
            fila.put(("erro", traceback.format_exc()[-600:]))

    resultado = {"abrir": False}

    def ler_fila():
        try:
            while True:
                tipo, valor = fila.get_nowait()
                if tipo == "estado":
                    estado.configure(text=valor)
                elif tipo == "detalhe":
                    detalhe.configure(text=valor)
                elif tipo == "erro":
                    estado.configure(text="Something went wrong", fg="#E5646E")
                    detalhe.configure(text=valor)
                    tk.Button(corpo, text="Close", command=raiz.destroy, bg=TRILHO, fg=TEXTO, relief="flat",
                              padx=18, pady=4).pack(pady=12)
                elif tipo == "pronto":
                    resultado["abrir"] = True
                    raiz.quit()
                    return
        except queue.Empty:
            pass
        raiz.after(80, ler_fila)

    threading.Thread(target=trabalho, daemon=True).start()
    ler_fila()
    raiz.mainloop()
    try:
        raiz.destroy()
    except Exception:  # noqa: BLE001
        pass
    if resultado["abrir"]:
        import app

        app.App().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        with open(os.path.join(BASE, "erro.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        try:
            import tkinter as tk
            from tkinter import messagebox

            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("YTK SHORTS", "Could not open YTK SHORTS.\nThe reason was saved to erro.log in the app folder.")
        except Exception:  # noqa: BLE001
            pass
