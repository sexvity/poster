"""YTK SHORTS: posts to YouTube Shorts, Instagram Reels and TikTok (US audience)."""
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Trabalha sempre na pasta do programa (config.json e tokens ficam aqui)
if getattr(sys, "frozen", False):
    # versão instalada (.exe): dados do usuário em %APPDATA%\\YTK SHORTS
    BASE = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "YTK SHORTS")
    os.makedirs(BASE, exist_ok=True)
    RECURSOS = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    RECURSOS = BASE
os.chdir(BASE)

import agenda  # noqa: E402
import ai  # noqa: E402
import capa  # noqa: E402
import clipes  # noqa: E402
import compactar  # noqa: E402
from painel_tiktok import PainelTikTok  # noqa: E402
import tiktok_auth  # noqa: E402
import uploaders  # noqa: E402

CONFIG = "config.json"
PLATAFORMAS = ["YouTube Shorts", "Instagram Reels", "TikTok"]

# Paleta: quase preto, bordas discretas e um único destaque
BG = "#0A0B0F"
CARD = "#101218"
CARD2 = "#161922"
BORDA = "#1F2330"
TEXTO = "#ECEEF4"
MUTED = "#7C8394"
ACENTO = "#6D6FF5"
ACENTO_HOVER = "#5B5DE0"
ACENTO_SUAVE = "#1C1F3F"
VERDE = "#3FB68B"
AMBAR = "#E0A23B"
VERMELHO = "#E5646E"
PERIGO = "#B4474F"
PERIGO_HOVER = "#963A41"
FAMILIA = "Segoe UI"
FAMILIA_TITULO = "Segoe UI"  # trocada por "Proxima Nova" (ou parecida) se estiver instalada no computador

# Dados que pertencem a cada conta (o resto, como a chave do Gemini e as chaves dos apps, é compartilhado)
CHAVES_CONTA = [
    "instagram_user_id", "instagram_access_token",
    "tiktok_access_token", "tiktok_refresh_token", "tiktok_privacidade",
    "youtube_token_file", "youtube_client_secret", "tiktok_client_key", "tiktok_client_secret",
]
NOVA_CONTA = "＋  Add account..."

RAIO = 12  # cantos de botões e campos
RAIO_CARTAO = 20
MARGEM = 20  # espaço lateral dentro dos cartões

ctk.set_appearance_mode("dark")


def fonte(tam=13, peso="normal"):
    return ctk.CTkFont(family=FAMILIA, size=tam, weight=peso)


def fonte_t(tam=13):
    """Fonte de destaque (títulos e botões principais): Proxima Nova Bold quando disponível."""
    return ctk.CTkFont(family=FAMILIA_TITULO, size=tam, weight="bold")


def escolher_fontes():
    """Proxima Nova é paga e não vem com o Windows: se o usuário a tiver instalada, o app usa; senão, uma parecida."""
    global FAMILIA_TITULO
    try:
        from tkinter import font as _tkfont

        instaladas = {f.lower(): f for f in _tkfont.families()}
        for candidata in ("proxima nova", "proxima nova bold", "montserrat", "gotham", "avenir next", "segoe ui semibold"):
            if candidata in instaladas:
                FAMILIA_TITULO = instaladas[candidata]
                return
    except Exception:
        pass


def carregar():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def salvar(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def arquivo_token_youtube(nome):
    seguro = re.sub(r"[^A-Za-z0-9_-]", "", nome.replace(" ", "_")).lower() or "conta"
    return f"youtube_token_{seguro}.json"


def nome_curto(caminho, limite=34):
    nome = os.path.basename(caminho)
    if len(nome) <= limite:
        return nome
    base, ext = os.path.splitext(nome)
    return base[: limite - len(ext) - 1] + "…" + ext


class Chip(ctk.CTkButton):
    """Botão liga/desliga em formato de pílula."""

    def __init__(self, master, texto, ligado, ao_mudar):
        super().__init__(
            master, text=texto, height=34, corner_radius=17, border_width=1,
            font=fonte_t(12), command=self._alternar,
        )
        self.ligado = ligado
        self._ao_mudar = ao_mudar
        self._pintar()

    def _alternar(self):
        self.ligado = not self.ligado
        self._pintar()
        self._ao_mudar()

    def _pintar(self):
        if self.ligado:
            self.configure(fg_color=ACENTO, hover_color=ACENTO_HOVER, border_color=ACENTO, text_color="white")
        else:
            self.configure(fg_color="transparent", hover_color=CARD2, border_color=BORDA, text_color=MUTED)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.title("YTK SHORTS")
        escolher_fontes()
        try:
            self.iconbitmap(os.path.join(RECURSOS, "ytk.ico"))
            # reforço: ícone em PNG de alta resolução (barra de tarefas nítida)
            from PIL import Image as _I, ImageTk as _IT

            self._icone_tk = _IT.PhotoImage(_I.open(os.path.join(RECURSOS, "ytk.png")).resize((256, 256)))
            self.after(300, lambda: self.iconphoto(True, self._icone_tk))
        except Exception:
            pass
        self.after(350, self._icone_windows)
        self.geometry("1080x780")
        self.minsize(960, 700)
        self.cfg = carregar()
        self._iniciar_contas()
        self._dlg_link = None
        uploaders.ABRIR_LINK = lambda url, nome: self.after(0, lambda: self._dialogo_link(url, nome))
        uploaders.FECHAR_LINK = lambda: self.after(0, self._fechar_dialogo_link)
        self.prefs = self.cfg.get("prefs", {})
        self.fila = queue.Queue()
        self.cancelar = threading.Event()
        self.lock = threading.Lock()
        self.ativos = 0
        self.modo_agendado = False
        self.video = ""
        self.video_duracao = None
        self._opcoes_tiktok = None
        self._barra_ativa = False
        self.agendados = []  # vídeos esperando o horário de pico (guardados em agendados.json)
        self._ag_lock = threading.RLock()
        self._ag_cancel = {}
        self._esperando = 0
        self._aba = "log"
        self._slot_sel = {}  # horário de pico escolhido por plataforma
        self._slots_sig = None
        self._ag_arquivo = os.path.join(BASE, "agendados.json")
        self._montar()
        self._atualizar_previa()
        self._atualizar_status()
        self._atualizar_contas_conectadas()
        self._iniciar_clipes()
        self._retomar_agendados()
        self.after(150, self._ler_fila)
        self.after(30000, self._tic)

    def _icone_windows(self):
        """Entrega ao Windows o ícone grande e o pequeno nos tamanhos exatos que ele vai desenhar (barra de tarefas,
        Alt+Tab, título da janela). Sem isso ele estica um tamanho só e o ícone fica borrado."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            u = ctypes.windll.user32
            u.LoadImageW.restype = wintypes.HANDLE
            u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                                     ctypes.c_int, wintypes.UINT]
            u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            u.SendMessageW.restype = wintypes.LPARAM
            hwnd = u.GetParent(self.winfo_id()) or self.winfo_id()
            caminho = os.path.join(RECURSOS, "ytk.ico")
            self._hicons = []
            for tipo, metrica in ((1, 11), (0, 49)):  # ICON_BIG / SM_CXICON, ICON_SMALL / SM_CXSMICON
                px = max(16, u.GetSystemMetrics(metrica))
                h = u.LoadImageW(None, caminho, 1, px, px, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    self._hicons.append(h)
                    u.SendMessageW(hwnd, 0x80, tipo, h)  # WM_SETICON
        except Exception:
            pass

    def _estilizar_janela(self, j):
        """Janelas secundárias: ícone do YTK e barra de título escura (o customtkinter recoloca o ícone padrão
        depois de 200 ms, por isso o reforço atrasado)."""
        def aplicar():
            try:
                if not j.winfo_exists():
                    return
                j.iconbitmap(os.path.join(RECURSOS, "ytk.ico"))
                if sys.platform == "win32":
                    import ctypes

                    hwnd = ctypes.windll.user32.GetParent(j.winfo_id()) or j.winfo_id()
                    um = ctypes.c_int(1)
                    for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 11 / 10)
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(um), ctypes.sizeof(um))
            except Exception:
                pass

        j.after(260, aplicar)

    # ------------------------------------------------------ login no navegador
    def _dialogo_link(self, url, nome):
        """Pergunta como abrir o link de login: no navegador padrão ou copiando (para colar em outro navegador)."""
        self._fechar_dialogo_link()
        j = ctk.CTkToplevel(self, fg_color=BG)
        self._estilizar_janela(j)
        self._dlg_link = j
        j.title(f"Sign in to {nome}")
        j.geometry("460x250")
        j.resizable(False, False)
        j.transient(self)
        j.after(100, j.lift)
        ctk.CTkLabel(j, text=f"Sign in to {nome}", font=fonte_t(16), text_color=TEXTO).pack(
            anchor="w", padx=22, pady=(20, 2))
        ctk.CTkLabel(
            j, text="How do you want to open the sign-in link? Use \"Copy link\" if the right account is signed in on another browser.",
            font=fonte(12), text_color=MUTED, wraplength=410, justify="left", anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 10))
        campo = ctk.CTkEntry(j, height=32, corner_radius=RAIO, fg_color=CARD2, border_color=BORDA, text_color=MUTED,
                             font=fonte(11))
        campo.insert(0, url)
        campo.configure(state="readonly")
        campo.pack(fill="x", padx=22, pady=(0, 14))
        aviso = ctk.CTkLabel(j, text="", font=fonte(11), text_color=VERDE)

        def abrir():
            webbrowser.open(url)
            j.destroy()

        def copiar():
            self.clipboard_clear()
            self.clipboard_append(url)
            aviso.configure(text="Link copied. Paste it into your browser's address bar (Ctrl+V).")

        linha = ctk.CTkFrame(j, fg_color="transparent")
        linha.pack(fill="x", padx=22)
        ctk.CTkButton(
            linha, text="Open in default browser", height=38, corner_radius=RAIO, fg_color=ACENTO,
            hover_color=ACENTO_HOVER, text_color="white", font=fonte_t(13), command=abrir,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            linha, text="Copy link", height=38, corner_radius=RAIO, border_width=1, fg_color="transparent",
            border_color=BORDA, hover_color=CARD2, text_color=TEXTO, font=fonte(13), command=copiar,
        ).pack(side="left", fill="x", expand=True)
        aviso.pack(anchor="w", padx=22, pady=(10, 0))

    def _fechar_dialogo_link(self):
        """Fecha a janelinha do link quando o login termina."""
        j, self._dlg_link = self._dlg_link, None
        if j is not None:
            try:
                j.destroy()
            except Exception:
                pass

    # ----------------------------------------------------------------- contas
    def _iniciar_contas(self):
        """Garante a lista de contas. Na primeira vez, as configurações atuais viram a conta 'Principal'."""
        contas = self.cfg.setdefault("contas", {})
        for chave in ("youtube_client_secret", "tiktok_client_key", "tiktok_client_secret"):
            plano = self.cfg.get(chave, "")
            if contas and plano and not any(chave in d for d in contas.values()):
                # versão antiga: a chave era única; passa a ser de cada conta (fica só na primeira)
                contas["Principal" if "Principal" in contas else next(iter(contas))][chave] = plano
        if not contas:
            principal = {k: self.cfg[k] for k in CHAVES_CONTA if k in self.cfg}
            principal.setdefault("youtube_token_file", "youtube_token.json")  # o arquivo que já existe
            contas["Principal"] = principal
            self.cfg["conta_ativa"] = "Principal"
        if self.cfg.get("conta_ativa") not in contas:
            self.cfg["conta_ativa"] = next(iter(contas))
        self._carregar_conta(self.cfg["conta_ativa"])

    def _carregar_conta(self, nome):
        """Coloca os dados da conta nas chaves normais, que é o que o resto do app lê."""
        for k in CHAVES_CONTA:
            self.cfg.pop(k, None)
        self.cfg.update(self.cfg["contas"][nome])
        self.cfg["conta_ativa"] = nome

    def _gravar(self):
        """Guarda as configurações no disco, atualizando antes os dados da conta ativa."""
        ativa = self.cfg.get("conta_ativa")
        if ativa in self.cfg.get("contas", {}):
            self.cfg["contas"][ativa] = {k: self.cfg[k] for k in CHAVES_CONTA if k in self.cfg}
        salvar(self.cfg)

    def _trocar_conta(self, escolha):
        if escolha == NOVA_CONTA:
            self.menu_conta.set(self.cfg["conta_ativa"])
            self._nova_conta()
            return
        if escolha == self.cfg["conta_ativa"]:
            return
        if self.ativos:
            messagebox.showinfo("Please wait", "Wait for the post to finish before switching accounts.")
            self.menu_conta.set(self.cfg["conta_ativa"])
            return
        self._gravar()
        self._carregar_conta(escolha)
        self._gravar()
        self._atualizar_status()
        self.painel_tiktok.invalidar()
        self._atualizar_contas_conectadas()
        self._escrever(f"Active account: {escolha}")

    def _nova_conta(self):
        dialogo = ctk.CTkInputDialog(text="Name for the new account (e.g. Shop, Channel 2):", title="New account")
        nome = (dialogo.get_input() or "").strip()
        if not nome:
            return
        if nome in self.cfg["contas"] or nome == NOVA_CONTA:
            messagebox.showwarning("Duplicate name", "An account with that name already exists.")
            return
        self._gravar()
        self.cfg["contas"][nome] = {"youtube_token_file": arquivo_token_youtube(nome)}
        self._carregar_conta(nome)
        self._gravar()
        self._atualizar_menu_contas()
        self._atualizar_status()
        self.painel_tiktok.invalidar()
        self._atualizar_contas_conectadas()
        self._escrever(f"Account '{nome}' created. Fill in its Instagram and TikTok details in Settings.")
        self._config()

    def _atualizar_menu_contas(self):
        self.menu_conta.configure(values=list(self.cfg["contas"]) + [NOVA_CONTA])
        self.menu_conta.set(self.cfg["conta_ativa"])

    # ------------------------------------------------------------ peças de UI
    def _cartao(self, pai, expandir=False):
        c = ctk.CTkFrame(pai, fg_color=CARD, corner_radius=RAIO_CARTAO, border_width=1, border_color=BORDA)
        c.pack(fill="both" if expandir else "x", expand=expandir, pady=(0, 14))
        return c

    def _rotulo(self, pai, texto, topo=12):
        ctk.CTkLabel(
            pai, text=texto, font=fonte_t(10), text_color=MUTED, anchor="w",
        ).pack(fill="x", padx=MARGEM + 2, pady=(topo, 6))

    def _passo(self, pai, numero, texto, topo=16):
        """Título do cartão com um número em círculo: deixa claro a ordem (1, 2, 3)."""
        linha = ctk.CTkFrame(pai, fg_color="transparent")
        linha.pack(fill="x", padx=MARGEM, pady=(topo, 8))
        ctk.CTkLabel(linha, text=f"{numero:02d}", font=fonte_t(12), text_color=ACENTO).pack(side="left")
        ctk.CTkLabel(linha, text=texto, font=fonte_t(16), text_color=TEXTO).pack(side="left", padx=(10, 0))
        return linha

    def _entrada(self, pai, var=None):
        e = ctk.CTkEntry(
            pai, textvariable=var, height=42, corner_radius=RAIO, border_width=1,
            fg_color=CARD2, border_color=BORDA, text_color=TEXTO, font=fonte(13),
        )
        e.pack(fill="x", padx=MARGEM, pady=(0, 2))
        return e

    def _caixa(self, pai, altura, expandir=False):
        t = ctk.CTkTextbox(
            pai, height=altura, corner_radius=RAIO, border_width=1, fg_color=CARD2,
            border_color=BORDA, text_color=TEXTO, font=fonte(13), wrap="word",
        )
        t.pack(fill="both" if expandir else "x", expand=expandir, padx=MARGEM, pady=(0, 2))
        return t

    def _montar(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Topo
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 12))
        try:
            from PIL import Image as _Img

            _logo = _Img.open(os.path.join(RECURSOS, "ytk.png")).convert("RGBA")
            self._logo_img = ctk.CTkImage(light_image=_logo, dark_image=_logo, size=(46, 46))
            ctk.CTkLabel(topo, text="", image=self._logo_img, width=46, height=46).pack(side="left")
        except Exception:
            ctk.CTkLabel(
                topo, text="▶", width=34, height=34, corner_radius=10, fg_color=ACENTO, text_color="white",
                font=fonte_t(15),
            ).pack(side="left")
        textos = ctk.CTkFrame(topo, fg_color="transparent")
        textos.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(textos, text="YTK SHORTS", font=fonte_t(21), text_color=TEXTO, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            textos, text="English captions and posting for a US audience",
            font=fonte(11), text_color=MUTED, anchor="w",
        ).pack(anchor="w")
        ctk.CTkButton(
            topo, text="Settings", width=96, height=34, corner_radius=RAIO, border_width=1,
            fg_color="transparent", border_color=BORDA, hover_color=CARD2, text_color=MUTED,
            font=fonte_t(12), command=self._config,
        ).pack(side="right")
        ctk.CTkButton(
            topo, text="Clips", width=80, height=34, corner_radius=RAIO, border_width=1,
            fg_color="transparent", border_color=BORDA, hover_color=CARD2, text_color=MUTED,
            font=fonte_t(12), command=self._dialogo_clipes,
        ).pack(side="right", padx=(0, 8))
        self.menu_conta = ctk.CTkOptionMenu(
            topo, values=list(self.cfg["contas"]) + [NOVA_CONTA], command=self._trocar_conta, width=150, height=34,
            corner_radius=RAIO, fg_color=CARD2, button_color=BORDA, button_hover_color="#2F3541",
            dropdown_fg_color=CARD2, dropdown_hover_color=ACENTO_SUAVE, text_color=TEXTO, font=fonte(12),
            dropdown_font=fonte(12),
        )
        self.menu_conta.set(self.cfg["conta_ativa"])
        self.menu_conta.pack(side="right", padx=(0, 14))
        ctk.CTkLabel(topo, text="Account", font=fonte(11), text_color=MUTED).pack(side="right", padx=(0, 6))
        self.status_lbl = {}
        for nome, curto in (("TikTok", "TikTok"), ("Instagram Reels", "Instagram"), ("YouTube Shorts", "YouTube")):
            lbl = ctk.CTkLabel(topo, text=f"●  {curto}", font=fonte(11), text_color=MUTED)
            lbl.pack(side="right", padx=(0, 14))
            self.status_lbl[nome] = lbl

        # Duas colunas
        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 10))
        corpo.grid_columnconfigure((0, 1), weight=1, uniform="col")
        corpo.grid_rowconfigure(0, weight=1)
        # a coluna esquerda rola (o painel do TikTok a deixa mais alta que a janela)
        esq = ctk.CTkScrollableFrame(
            corpo, fg_color="transparent", scrollbar_button_color=BORDA, scrollbar_button_hover_color="#2F3541",
        )
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        self.esq = esq
        dire = ctk.CTkFrame(corpo, fg_color="transparent")
        dire.grid(row=0, column=1, sticky="nsew", padx=(9, 0))

        # ---- Coluna esquerda: vídeo + publicação
        c1 = self._cartao(esq, expandir=True)
        self._passo(c1, 1, "Video and topic")
        self.btn_video = ctk.CTkButton(
            c1, text="Choose video...", height=48, corner_radius=RAIO, border_width=1, anchor="w",
            fg_color=CARD2, hover_color="#232834", border_color=BORDA, text_color=TEXTO,
            font=fonte(13), command=self._escolher,
        )
        self.btn_video.pack(fill="x", padx=MARGEM, pady=(0, 2))
        linha_video = ctk.CTkFrame(c1, fg_color="transparent")
        linha_video.pack(fill="x", padx=MARGEM, pady=(6, 0))
        self.miniatura = ctk.CTkLabel(linha_video, text="", fg_color="transparent")  # prévia (o TikTok exige)
        self.info_video = ctk.CTkLabel(
            linha_video, text="Accepts mp4, mov, m4v, webm and mkv.", font=fonte(11), text_color=MUTED, anchor="nw",
            justify="left", wraplength=240,
        )
        self.info_video.pack(side="right", fill="both", expand=True, padx=(12, 0))
        self._rotulo(c1, "WHAT IS IT ABOUT? (any language)", 14)
        self.desc = self._caixa(c1, 70, expandir=True)
        # a roda do mouse sobre esta caixa também rola a coluna (a caixa é curta, não precisa rolar sozinha)
        self.desc._textbox.bind(
            "<MouseWheel>", lambda e: (self.esq._parent_canvas.yview_scroll(int(-e.delta / 120), "units"), "break")[1]
        )
        self._rotulo(c1, "TEXT LANGUAGE", 10)
        self.idiomas = {"Auto (from the video's speech)": "auto", "English (US)": "en", "Português (Brasil)": "pt"}
        self.menu_idioma = ctk.CTkOptionMenu(
            c1, values=list(self.idiomas), height=32, corner_radius=RAIO, fg_color=CARD2, button_color=BORDA,
            button_hover_color="#2F3541", dropdown_fg_color=CARD2, dropdown_hover_color=ACENTO_SUAVE,
            text_color=TEXTO, font=fonte(12), dropdown_font=fonte(12),
        )
        self.menu_idioma.set(next((k for k, v in self.idiomas.items() if v == self.prefs.get("idioma", "auto")),
                                  "Auto (from the video's speech)"))
        self.menu_idioma.pack(fill="x", padx=MARGEM, pady=(0, 0))
        self._rotulo(c1, "NUMBER OF HASHTAGS", 10)
        self.qtds_hash = ["0", "3", "5", "8", "10", "12", "15"]
        self.menu_qtd_hash = ctk.CTkOptionMenu(
            c1, values=self.qtds_hash, height=32, corner_radius=RAIO, fg_color=CARD2, button_color=BORDA,
            button_hover_color="#2F3541", dropdown_fg_color=CARD2, dropdown_hover_color=ACENTO_SUAVE,
            text_color=TEXTO, font=fonte(12), dropdown_font=fonte(12),
        )
        qtd_salva = str(self.prefs.get("qtd_hashtags", 8))
        self.menu_qtd_hash.set(qtd_salva if qtd_salva in self.qtds_hash else "8")
        self.menu_qtd_hash.pack(fill="x", padx=MARGEM, pady=(0, 0))
        self.sw_pergunta = ctk.CTkSwitch(
            c1, text="Title as a question (to get comments)", font=fonte(12), text_color=MUTED,
            progress_color=ACENTO, button_color="#F2F3F7", button_hover_color="white", fg_color=BORDA,
        )
        self.sw_pergunta.pack(anchor="w", padx=MARGEM + 2, pady=(12, 0))
        if self.prefs.get("titulo_pergunta", False):
            self.sw_pergunta.select()
        self.btn_gerar = ctk.CTkButton(
            c1, text="Generate text", height=46, corner_radius=RAIO, border_width=1,
            fg_color=ACENTO_SUAVE, hover_color="#262A55", border_color=ACENTO, text_color="#D3D5FF",
            font=fonte_t(13), command=self._gerar,
        )
        self.btn_gerar.pack(fill="x", padx=MARGEM, pady=(8, MARGEM))

        c3 = self._cartao(esq)
        self._passo(c3, 3, "Where to post")
        linha = ctk.CTkFrame(c3, fg_color="transparent")
        linha.pack(fill="x", padx=MARGEM, pady=(0, 4))
        marcadas = self.prefs.get("plataformas", {"YouTube Shorts": True, "Instagram Reels": False, "TikTok": False})
        self.chips = {}
        for nome in PLATAFORMAS:
            chip = Chip(linha, nome, bool(marcadas.get(nome, False)), self._atualizar_previa)
            chip.pack(side="left", padx=(0, 8))
            self.chips[nome] = chip

        self.contas_lbl = ctk.CTkLabel(
            c3, text="Connected accounts: checking...",
            font=fonte(11), text_color=MUTED, anchor="w", justify="left", wraplength=400,
        )
        self.contas_lbl.pack(fill="x", padx=MARGEM + 4, pady=(10, 0))

        self.painel_tiktok = PainelTikTok(
            c3, {"CARD": CARD, "CARD2": CARD2, "BORDA": BORDA, "TEXTO": TEXTO, "MUTED": MUTED, "ACENTO": ACENTO,
                 "ACENTO_SUAVE": ACENTO_SUAVE, "RAIO": RAIO},
            fonte, lambda: self.cfg, self._escrever,
        )

        self.sw_agenda = ctk.CTkSwitch(
            c3, text="Post at peak US time", font=fonte(13), text_color=TEXTO,
            progress_color=ACENTO, button_color="#F2F3F7", button_hover_color="white",
            fg_color=BORDA, command=self._atualizar_previa,
        )
        self.sw_agenda.pack(anchor="w", padx=MARGEM + 2, pady=(12, 4))
        if self.prefs.get("agendar"):
            self.sw_agenda.select()
        self.slots_box = ctk.CTkFrame(c3, fg_color="transparent", width=1, height=1)
        self.previa = ctk.CTkLabel(
            c3, text="", font=fonte(11), text_color=MUTED, anchor="w", justify="left", wraplength=380,
        )
        self.previa.pack(fill="x", padx=MARGEM + 4, pady=(0, 8))

        self.sw_compactar = ctk.CTkSwitch(
            c3, text="Compress if over the platform limit", font=fonte(12), text_color=MUTED,
            progress_color=ACENTO, button_color="#F2F3F7", button_hover_color="white", fg_color=BORDA,
        )
        self.sw_compactar.pack(anchor="w", padx=MARGEM + 2, pady=(0, 10))
        if self.prefs.get("compactar", True):
            self.sw_compactar.select()

        self.sw_auto = ctk.CTkSwitch(
            c3, text="Empty title? AI writes it and posts (no review)", font=fonte(12), text_color=MUTED,
            progress_color=ACENTO, button_color="#F2F3F7", button_hover_color="white", fg_color=BORDA,
        )
        self.sw_auto.pack(anchor="w", padx=MARGEM + 2, pady=(0, 10))
        if self.prefs.get("auto"):
            self.sw_auto.select()

        ctk.CTkFrame(c3, fg_color="transparent", height=MARGEM - 6).pack()

        # ---- Coluna direita: texto + botão + atividade
        c2 = self._cartao(dire)
        self._passo(c2, 2, "Post text")
        cab = ctk.CTkFrame(c2, fg_color="transparent")
        cab.pack(fill="x", padx=MARGEM + 2, pady=(0, 5))
        ctk.CTkLabel(cab, text="TITLE", font=fonte_t(10), text_color=MUTED).pack(side="left")
        self.cont_titulo = ctk.CTkLabel(cab, text="0/70", font=fonte(11), text_color=MUTED)
        self.cont_titulo.pack(side="right")
        self.titulo = ctk.StringVar()
        self.titulo.trace_add("write", lambda *_: self._contar_titulo())
        e = self._entrada(c2, self.titulo)
        e.configure(placeholder_text="The title appears here after generating")
        self._rotulo(c2, "DESCRIPTION")
        self.descricao_final = self._caixa(c2, 66)
        self._rotulo(c2, "HASHTAGS")
        self.hashtags = self._caixa(c2, 56)
        ctk.CTkFrame(c2, height=MARGEM - 2, fg_color="transparent").pack()

        self.btn_postar = ctk.CTkButton(
            dire, text="Post now", height=52, corner_radius=14, fg_color=ACENTO,
            hover_color=ACENTO_HOVER, text_color="white", font=fonte_t(16), command=self._postar,
        )
        self.btn_postar.pack(fill="x", pady=(0, 8))
        self.barra = ctk.CTkProgressBar(
            dire, mode="indeterminate", height=3, corner_radius=2, fg_color=BORDA, progress_color=ACENTO,
        )
        self.barra.pack(fill="x", pady=(0, 10))
        self.barra.set(0)

        c4 = self._cartao(dire, expandir=True)
        abas_d = ctk.CTkFrame(c4, fg_color="transparent")
        abas_d.pack(fill="x", padx=MARGEM, pady=(16, 8))
        self.btn_aba_log = ctk.CTkButton(
            abas_d, text="Activity", width=92, height=30, corner_radius=15, font=fonte_t(12),
            command=lambda: self._aba_direita("log"),
        )
        self.btn_aba_log.pack(side="left", padx=(0, 6))
        self.btn_aba_ag = ctk.CTkButton(
            abas_d, text="Scheduled", width=124, height=30, corner_radius=15, font=fonte_t(12),
            command=lambda: self._aba_direita("ag"),
        )
        self.btn_aba_ag.pack(side="left")
        self.f_log = ctk.CTkFrame(c4, fg_color="transparent")
        self.f_ag = ctk.CTkScrollableFrame(c4, fg_color="transparent", corner_radius=0)
        self.log = ctk.CTkTextbox(
            self.f_log, height=90, corner_radius=RAIO, border_width=0, fg_color=CARD,
            text_color=MUTED, font=fonte(12), wrap="word", state="disabled",
        )
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("ok", foreground=VERDE)
        self.log.tag_config("erro", foreground=VERMELHO)
        self.log.tag_config("hora", foreground="#5A6072")
        self._aba_direita("log")
        self._botao_estado()

    # ----------------------------------------------------------- utilidades
    def _escrever(self, msg):
        self.fila.put(("log", msg))

    def _hashtags_finais(self, texto):
        """Hashtags do campo, sem repetir, sempre com a hashtag fixa (para achar todos os vídeos por ela)."""
        lista = ai.lista_hashtags(texto)
        fixa = ai.lista_hashtags(self.cfg.get("hashtag_fixa", ""))
        for h in fixa:
            if h not in lista:
                lista.append(h)
        return lista

    def _get_hashtags(self):
        return self.hashtags.get("1.0", "end").strip()

    def _set_hashtags(self, texto):
        self.hashtags.delete("1.0", "end")
        self.hashtags.insert("1.0", texto)

    def _ler_fila(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self.log.configure(state="normal")
                    tag = "ok" if str(dado).startswith(("OK", "TikTok connected", "Text generated", "Done")) else (
                        "erro" if str(dado).startswith(("FAILED", "Error")) or "Error" in str(dado)[:30] else ""
                    )
                    self.log.insert("end", f"{datetime.now():%H:%M}  ", "hora")
                    self.log.insert("end", f"{dado}\n", tag)
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif tipo == "preencher":
                    self.titulo.set(dado["titulo"])
                    self.descricao_final.delete("1.0", "end")
                    self.descricao_final.insert("1.0", dado["descricao"])
                    self._set_hashtags(" ".join(self._hashtags_finais(" ".join(dado["hashtags"]))))
                elif tipo == "gerado":
                    self.btn_gerar.configure(state="normal", text="Generate text")
                elif tipo == "copiar":
                    self.clipboard_clear()
                    self.clipboard_append(dado)
                elif tipo == "abrir":
                    try:
                        os.startfile(dado)  # só existe no Windows
                    except Exception:
                        pass
                elif tipo == "auto_postar":
                    if self.chips["TikTok"].ligado:
                        self._escrever("TikTok requires you to review and confirm each post. Check the options and click Post.")
                    else:
                        self._postar()
                elif tipo == "agendados":
                    self._desenhar_agendados()
                elif tipo == "fim":
                    self.modo_agendado = False
                    self._botao_estado()
                    self._atualizar_previa()
        except queue.Empty:
            pass
        self.after(150, self._ler_fila)

    def _contar_titulo(self):
        n = len(self.titulo.get())
        self.cont_titulo.configure(text=f"{n}/70", text_color=AMBAR if n > 70 else MUTED)

    def _atualizar_contas_conectadas(self):
        """Consulta o @ de cada plataforma conectada (em segundo plano) e mostra abaixo dos botões."""
        self._versao_contas = getattr(self, "_versao_contas", 0) + 1
        versao = self._versao_contas
        cfg = dict(self.cfg)  # cópia: o app pode trocar de conta enquanto consulta

        def tarefa():
            linhas = []
            for nome, fn in (("YouTube", uploaders.youtube_canal), ("Instagram", uploaders.instagram_usuario),
                             ("TikTok", uploaders.tiktok_usuario)):
                try:
                    r = fn(cfg)
                    if r is None:
                        texto = "not connected"
                    elif r == "":
                        texto = "connected" + (" (reconnect to see the @)" if nome == "YouTube" else "")
                    else:
                        texto = r
                except Exception:  # noqa: BLE001
                    texto = "could not read"
                linhas.append(f"{nome}: {texto}")
            if versao == self._versao_contas:
                self.after(0, lambda: self.contas_lbl.configure(text="Connected accounts   " + "   ·   ".join(linhas)))

        threading.Thread(target=tarefa, daemon=True).start()

    def _atualizar_status(self):
        """Bolinha verde = a plataforma está configurada; cinza = falta configurar."""
        cfg = self.cfg
        feito = {
            "YouTube Shorts": os.path.exists(cfg.get("youtube_token_file") or "youtube_token.json"),
            "Instagram Reels": bool(cfg.get("instagram_access_token") and cfg.get("instagram_user_id")),
            "TikTok": bool(cfg.get("tiktok_access_token") or cfg.get("tiktok_refresh_token")),
        }
        for nome, lbl in self.status_lbl.items():
            lbl.configure(text_color=VERDE if feito.get(nome) else MUTED)

    def _tic(self):
        self._desenhar_agendados()
        if not self.ativos:
            self._atualizar_previa()
        self._atualizar_status()
        self.after(30000, self._tic)

    def _botao_estado(self):
        em_andamento = bool(self.ativos) and not self.modo_agendado
        if em_andamento and not self._barra_ativa:
            self.barra.start()
            self._barra_ativa = True
        elif not em_andamento and self._barra_ativa:
            self.barra.stop()
            self.barra.set(0)
            self._barra_ativa = False
        if self.ativos and self.modo_agendado:
            self.btn_postar.configure(
                text="Cancel schedule", state="normal", fg_color=PERIGO, hover_color=PERIGO_HOVER
            )
        elif self.ativos:
            self.btn_postar.configure(text="Posting...", state="disabled", fg_color=ACENTO)
        else:
            texto = "Schedule for peak time" if self.sw_agenda.get() else "Post now"
            self.btn_postar.configure(text=texto, state="normal", fg_color=ACENTO, hover_color=ACENTO_HOVER)

    def _mostrar_painel_tiktok(self):
        self.painel_tiktok.mostrar(
            self.chips["TikTok"].ligado, fill="x", padx=MARGEM, pady=(10, 0), before=self.sw_agenda
        )

    def _atualizar_previa(self):
        self._mostrar_painel_tiktok()
        if self.ativos:
            return
        self._botao_estado()
        if not self.sw_agenda.get():
            self.previa.configure(text="Posts as soon as you click the button.")
            self._desenhar_slots([])
            return
        plats = [n for n in PLATAFORMAS if self.chips[n].ligado and n != "TikTok"]
        tiktok = self.chips["TikTok"].ligado
        aviso_tt = "\nTikTok can't be scheduled: it needs your confirmation on each post. Turn this switch off to post to TikTok." if tiktok else ""
        if not plats:
            self.previa.configure(text=("Choose YouTube or Instagram to schedule." if not tiktok else "") + aviso_tt.strip())
            self._desenhar_slots([])
            return
        self.previa.configure(
            text="Pick the peak time for each platform. The video goes to the Scheduled tab; "
            "keep the app open and the computer on until then." + aviso_tt
        )
        self._desenhar_slots(plats)

    def _ocupados(self, nome):
        """Horários já usados por outros vídeos que esperam nessa plataforma."""
        with self._ag_lock:
            return {
                int(i["alvo"]) for it in self.agendados for n, i in it["plataformas"].items()
                if n == nome and i["estado"] == "waiting"
            }

    def _desenhar_slots(self, plats):
        """Um seletor de horário de pico por plataforma (só os horários que ainda estão livres)."""
        dados = {}
        try:
            for n in plats:
                dados[n] = agenda.proximos_picos(n, 12, ocupados=self._ocupados(n))
        except Exception as e:
            self.previa.configure(text=str(e))
            dados = {}
        sig = tuple((n, tuple(int(d.timestamp()) for d in v)) for n, v in dados.items())
        if sig == self._slots_sig:
            return
        self._slots_sig = sig
        for w in self.slots_box.winfo_children():
            w.destroy()
        if not dados:
            self.slots_box.pack_forget()
            return
        self.slots_box.pack(fill="x", padx=MARGEM + 4, pady=(2, 4), before=self.previa)
        curto = {"YouTube Shorts": "YouTube", "Instagram Reels": "Instagram", "TikTok": "TikTok"}
        for n, lista in dados.items():
            if not lista:
                ctk.CTkLabel(self.slots_box, text=f"{curto[n]}: no free peak time in the next 3 weeks.",
                             font=fonte(11), text_color=AMBAR, anchor="w").pack(fill="x")
                continue
            rotulos = {}
            for i, d in enumerate(lista):
                r = ("Next free  ·  " if i == 0 else "") + f"{agenda._fmt(d)} NY  ·  {agenda._fmt(d.astimezone())} you"
                rotulos[r] = d.timestamp()
            atual = next((r for r, t in rotulos.items() if t == self._slot_sel.get(n)), next(iter(rotulos)))
            self._slot_sel[n] = rotulos[atual]
            linha = ctk.CTkFrame(self.slots_box, fg_color="transparent")
            linha.pack(fill="x", pady=(0, 6))
            ctk.CTkLabel(linha, text=curto[n], font=fonte_t(11), text_color=TEXTO, width=68, anchor="w").pack(side="left")
            menu = ctk.CTkOptionMenu(
                linha, values=list(rotulos), height=30, corner_radius=10, fg_color=CARD2, button_color=BORDA,
                button_hover_color="#2F3541", dropdown_fg_color=CARD2, dropdown_hover_color=ACENTO_SUAVE,
                text_color=TEXTO, font=fonte(11), dropdown_font=fonte(11),
                command=lambda v, n=n, r=rotulos: self._slot_sel.__setitem__(n, r[v]),
            )
            menu.set(atual)
            menu.pack(side="left", fill="x", expand=True)

    def _idioma(self):
        try:
            return self.idiomas.get(self.menu_idioma.get(), "auto")
        except Exception:
            return self.prefs.get("idioma", "auto")

    def _qtd_hashtags(self):
        try:
            return int(self.menu_qtd_hash.get())
        except Exception:
            return int(self.prefs.get("qtd_hashtags", 8))

    def _titulo_pergunta(self):
        try:
            return bool(self.sw_pergunta.get())
        except Exception:
            return bool(self.prefs.get("titulo_pergunta", False))

    def _guardar_preferencias(self):
        self.prefs = {
            "plataformas": {n: self.chips[n].ligado for n in PLATAFORMAS},
            "agendar": bool(self.sw_agenda.get()),
            "auto": bool(self.sw_auto.get()),
            "compactar": bool(self.sw_compactar.get()),
            "idioma": self._idioma(),
            "qtd_hashtags": self._qtd_hashtags(),
            "titulo_pergunta": self._titulo_pergunta(),
        }
        self.cfg["prefs"] = self.prefs
        self._gravar()

    # --------------------------------------------------------------- ações
    def _escolher(self):
        caminho = filedialog.askopenfilename(
            filetypes=[("Videos", "*.mp4 *.mov *.m4v *.webm *.mkv"), ("All files", "*.*")]
        )
        if caminho:
            self._definir_video(caminho)

    def _definir_video(self, caminho):
        self.video = caminho
        mb = os.path.getsize(caminho) / (1024 * 1024)
        self.btn_video.configure(text=f"{nome_curto(caminho)}   ·   {mb:.0f} MB")
        self.info_video.configure(text="Reading video...", text_color=MUTED)

        def ler():
            inf = capa.informacoes(caminho)
            quadros = capa.extrair_quadros(caminho, 1, 480)
            self.after(0, lambda: self._mostrar_info(caminho, inf))
            if quadros:
                self.after(0, lambda: self._mostrar_miniatura(caminho, quadros[0][1]))

        threading.Thread(target=ler, daemon=True).start()

    def _mostrar_miniatura(self, caminho, b64):
        """Prévia do vídeo que vai ser postado (um quadro, em tamanho pequeno)."""
        if caminho != self.video:
            return
        try:
            import base64
            import io

            from PIL import Image

            from PIL import ImageDraw

            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
            # cantos redondos
            mascara = Image.new("L", img.size, 0)
            ImageDraw.Draw(mascara).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=img.width // 12, fill=255)
            img.putalpha(mascara)
            altura = 132
            largura = max(1, int(img.width * altura / img.height))
            self._img_previa = ctk.CTkImage(light_image=img, dark_image=img, size=(largura, altura))
            self.miniatura.configure(image=self._img_previa)
            self.miniatura.pack(side="left")
        except Exception:
            pass

    def _mostrar_info(self, caminho, inf):
        if caminho != self.video:
            return  # o usuário já escolheu outro vídeo
        if not inf:
            self.info_video.configure(text="Could not read the details, but you can still post.", text_color=MUTED)
            return
        dur, larg, alt = inf
        self.video_duracao = dur
        tempo = f"{int(dur) // 60}:{int(dur) % 60:02d}"
        base = f"{tempo}  ·  {larg}×{alt}"
        if alt >= larg * 1.6:
            self.info_video.configure(text=f"{base}  ·  ✓ vertical 9:16, ideal for Shorts, Reels and TikTok", text_color=VERDE)
        elif alt > larg:
            self.info_video.configure(text=f"{base}  ·  vertical, but not exactly 9:16", text_color=AMBAR)
        else:
            self.info_video.configure(
                text=f"{base}  ·  ⚠ horizontal: on YouTube it becomes a regular video (not a Short) and elsewhere it gets black bars",
                text_color=AMBAR,
            )
        if dur > 180:
            self.info_video.configure(text=self.info_video.cget("text") + "\n⚠ over 3 min: it will not be a Short on YouTube.")



    def _gerar(self, depois_postar=False):
        if not self.video:
            messagebox.showwarning("Video missing", "Choose the video file first.")
            return
        descricao = self.desc.get("1.0", "end").strip()
        nome = os.path.basename(self.video)
        chave = self.cfg.get("gemini_api_key", "")
        idioma = self._idioma()  # lido aqui, na thread da janela
        qtd_hash = self._qtd_hashtags()
        pergunta = self._titulo_pergunta()
        self._guardar_preferencias()
        self.btn_gerar.configure(state="disabled", text="Generating...")

        def tarefa():
            try:
                self._escrever("Watching the video to write about what appears in it...")
                quadros = [b for _, b in capa.extrair_quadros(self.video, 6)]
                if not quadros:
                    self._escrever("Could not extract frames; using only your description.")
                audio = capa.extrair_audio(self.video) if idioma == "auto" else None
                res = ai.gerar(chave, descricao, nome, qtd_hash, quadros=quadros, idioma=idioma, audio=audio,
                                titulo_pergunta=pergunta)
                self.fila.put(("preencher", res))
                self._escrever("Text generated. Review it and edit if you like.")
                if depois_postar:
                    self.fila.put(("auto_postar", None))
            except Exception as e:
                self._escrever(f"Error from AI: {e}")
            finally:
                self.fila.put(("gerado", None))

        threading.Thread(target=tarefa, daemon=True).start()

    def _preparar_manual(self):
        """Converte o vídeo para o formato do Reels e copia o texto, para postar pela Meta Business Suite."""
        video = self.video
        if not video or not os.path.exists(video):
            messagebox.showwarning("Video missing", "Choose the video file first.")
            return
        titulo = self.titulo.get().strip()
        if not titulo:
            messagebox.showwarning("Text missing", "Generate or write the title first.")
            return
        titulo = ai.sem_hashtags(titulo)
        descricao = ai.sem_hashtags(self.descricao_final.get("1.0", "end"))
        legenda = f"{titulo}\n\n{descricao}\n\n{' '.join(self._hashtags_finais(self._get_hashtags()))}".strip()

        def tarefa():
            try:
                pronto = uploaders.preparar_instagram(video, self._escrever, bool(self.sw_compactar.get()))
                if pronto != video:
                    destino = os.path.splitext(video)[0] + "_instagram.mp4"
                    shutil.copy2(pronto, destino)
                    try:
                        os.remove(pronto)
                    except OSError:
                        pass
                else:
                    destino = video
                self.fila.put(("copiar", legenda))
                self._escrever(f"Done: {destino}")
                self._escrever("Text copied. In Meta Business Suite: Create reel, upload the video and paste (Ctrl+V).")
                self.fila.put(("abrir", os.path.dirname(destino)))
            except Exception as e:
                self._escrever(f"Error while preparing: {e}")

        threading.Thread(target=tarefa, daemon=True).start()

    def _postar(self):
        if self.ativos:  # botão virou "Cancelar agendamento"
            self.cancelar.set()
            self._escrever("Canceling the schedule...")
            return
        video = self.video
        if not video or not os.path.exists(video):
            messagebox.showwarning("Video missing", "Choose a valid video file.")
            return
        escolhidas = [n for n in PLATAFORMAS if self.chips[n].ligado]
        if not escolhidas:
            messagebox.showwarning("No platform", "Select at least one platform.")
            return
        if self.sw_agenda.get() and "TikTok" in escolhidas:
            messagebox.showinfo(
                "TikTok can't be scheduled",
                "TikTok requires you to review and confirm each post when you publish it.\n\n"
                "Turn off 'Post at peak US time' to post to TikTok now, or unselect TikTok to schedule the others.",
            )
            return
        self._opcoes_tiktok = None
        if "TikTok" in escolhidas:
            try:
                self._opcoes_tiktok = self.painel_tiktok.validar(self.video_duracao)
            except ValueError as e:
                messagebox.showwarning("TikTok", str(e))
                return
        titulo = self.titulo.get().strip()
        if not titulo:
            if self.sw_auto.get():
                self._gerar(depois_postar=True)
                return
            messagebox.showwarning("Title missing", "Generate or write a title before posting.")
            return

        # hashtags só no campo delas: tira qualquer # que tenha ido parar no título ou na descrição
        titulo = ai.sem_hashtags(titulo)
        descricao = ai.sem_hashtags(self.descricao_final.get("1.0", "end"))
        hashtags = self._hashtags_finais(self._get_hashtags())
        legenda = f"{titulo}\n\n{descricao}\n\n{' '.join(hashtags)}".strip()
        if self.sw_agenda.get():
            self._agendar(escolhidas, video, titulo, descricao, hashtags, legenda)
            return
        planos = [(nome, None) for nome in escolhidas]

        self._guardar_preferencias()
        self.cancelar.clear()
        self.modo_agendado = False
        with self.lock:
            self.ativos = len(planos)
        self._botao_estado()
        for nome, alvo in planos:
            threading.Thread(
                target=self._tarefa, args=(nome, alvo, video, titulo, descricao, hashtags, legenda), daemon=True
            ).start()

    def _publicar(self, nome, cfg, video, titulo, descricao, hashtags, legenda, opcoes, log):
        """Envia o vídeo para uma plataforma (compactando se precisar). Devolve a mensagem de sucesso."""
        arquivo, temporario = video, False
        try:
            if nome != "Instagram Reels" and cfg.get("prefs", {}).get("compactar", True):
                arquivo, temporario = compactar.ajustar(video, compactar.LIMITES_MB[nome], log, nome)
            if nome == "YouTube Shorts":
                return uploaders.postar_youtube(cfg, arquivo, titulo, descricao, hashtags, log)
            capa_ms = None
            if cfg.get("capa_ia", True):
                log(f"{nome.split()[0]}: AI is choosing the cover...")
                capa_ms = capa.escolher(cfg.get("gemini_api_key", ""), video, titulo, log)
            if nome == "Instagram Reels":
                return uploaders.postar_instagram(cfg, video, legenda, log, capa_ms)
            try:
                return uploaders.postar_tiktok(cfg, arquivo, legenda, log, capa_ms, opcoes)
            except RuntimeError as e:
                if "picture_size_check_failed" not in str(e):
                    raise
                # o TikTok não gostou do arquivo: refaz num formato padrão e tenta uma vez mais, sem capa escolhida
                refeito = compactar.normalizar(video, log, nome)
                if not refeito:
                    raise
                if temporario:
                    try:
                        os.remove(arquivo)
                    except OSError:
                        pass
                arquivo, temporario = refeito, True
                return uploaders.postar_tiktok(cfg, arquivo, legenda, log, None, opcoes)
        finally:
            if temporario:
                try:
                    os.remove(arquivo)
                except OSError:
                    pass

    def _tarefa(self, nome, alvo, video, titulo, descricao, hashtags, legenda):
        conta = self.cfg.get("conta_ativa", "")
        try:
            self._escrever(f"{nome}: posting to account '{conta}'...")
            r = self._publicar(nome, self.cfg, video, titulo, descricao, hashtags, legenda,
                               self._opcoes_tiktok, self._escrever)
            self._escrever(f"OK {nome}: {r}")
        except Exception as e:
            self._escrever(f"FAILED {nome}: {e}")
        finally:
            with self.lock:
                self.ativos -= 1
                ultimo = self.ativos == 0
                try:
                    self._gravar()  # guarda tokens renovados
                except Exception:
                    pass
            if ultimo:
                self._escrever("Finished.")
                self.fila.put(("fim", None))

    # ------------------------------------------------- fila do horário de pico
    @staticmethod
    def _dt(ts):
        return datetime.fromtimestamp(ts, agenda.FUSO) if agenda.FUSO else datetime.fromtimestamp(ts)

    def _salvar_agendados(self):
        with self._ag_lock:
            try:
                tmp = self._ag_arquivo + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.agendados, f, indent=1, ensure_ascii=False, default=str)
                os.replace(tmp, self._ag_arquivo)
            except Exception:
                pass

    def _cfg_da_conta(self, conta):
        """Configurações com os dados da conta que agendou. Se for a conta ativa, o próprio dicionário do app."""
        if conta == self.cfg.get("conta_ativa") or conta not in self.cfg.get("contas", {}):
            return self.cfg, True
        snap = dict(self.cfg)
        for k in CHAVES_CONTA:
            snap.pop(k, None)
        snap.update(self.cfg["contas"][conta])
        return snap, False

    def _agendar(self, plataformas, video, titulo, descricao, hashtags, legenda):
        """Põe o vídeo na fila do horário de pico e libera o editor para o próximo."""
        plataformas = [n for n in plataformas if n != "TikTok"]
        alvos = {}
        for nome in plataformas:
            try:
                livres = agenda.proximos_picos(nome, 12, ocupados=self._ocupados(nome))
            except Exception as e:
                messagebox.showerror("Peak time", str(e))
                return
            if not livres:
                messagebox.showinfo("Peak time", f"{nome}: no free peak time in the next 3 weeks.")
                return
            escolha = self._slot_sel.get(nome)
            ts = {d.timestamp() for d in livres}
            alvos[nome] = self._dt(escolha if escolha in ts else livres[0].timestamp())
        self._guardar_preferencias()
        item = {
            "id": str(int(time.time() * 1000)), "video": video, "nome": os.path.basename(video),
            "titulo": titulo, "descricao": descricao, "hashtags": list(hashtags), "legenda": legenda,
            "conta": self.cfg.get("conta_ativa", ""), "tiktok": self._opcoes_tiktok, "criado": time.time(),
            "plataformas": {n: {"alvo": a.timestamp(), "estado": "waiting", "msg": ""} for n, a in alvos.items()},
        }
        with self._ag_lock:
            self.agendados.insert(0, item)
            del self.agendados[40:]
        self._salvar_agendados()
        for n, a in alvos.items():
            self._escrever(f"{n}: scheduled for {agenda.descrever(a)}.")
            self._iniciar_espera(item["id"], n)
        self._slot_sel.clear()
        self._slots_sig = None
        self._limpar_editor()
        self._aba_direita("ag")

    def _limpar_editor(self):
        """Depois de agendar: editor vazio, pronto para o próximo vídeo."""
        self.video = ""
        self.video_duracao = None
        self._opcoes_tiktok = None
        self.btn_video.configure(text="Choose video...")
        self.info_video.configure(text="Accepts mp4, mov, m4v, webm and mkv.", text_color=MUTED)
        try:
            self.miniatura.pack_forget()
        except Exception:
            pass
        self.titulo.set("")
        self.desc.delete("1.0", "end")
        self.descricao_final.delete("1.0", "end")
        self._set_hashtags("")
        self._atualizar_previa()

    def _iniciar_espera(self, id_, nome):
        ev = threading.Event()
        self._ag_cancel[(id_, nome)] = ev
        threading.Thread(target=self._tarefa_agendada, args=(id_, nome, ev), daemon=True).start()

    def _achar_item(self, id_):
        with self._ag_lock:
            for it in self.agendados:
                if it["id"] == id_:
                    return it
        return None

    def _contar_espera(self, delta):
        with self._ag_lock:
            self._esperando = max(0, self._esperando + delta)
            agenda.evitar_suspensao(self._esperando > 0)  # o computador não dorme enquanto há algo na fila

    def _marcar(self, item, nome, estado, msg=""):
        with self._ag_lock:
            item["plataformas"][nome]["estado"] = estado
            item["plataformas"][nome]["msg"] = msg
        self._salvar_agendados()
        self.fila.put(("agendados", None))

    def _tarefa_agendada(self, id_, nome, ev):
        item = self._achar_item(id_)
        if not item:
            return
        log = self._escrever
        self._contar_espera(1)
        try:
            alvo = self._dt(item["plataformas"][nome]["alvo"])
            if not agenda.esperar(alvo, ev, lambda t: log(f"{nome} ({item['nome']}): {t}")):
                self._marcar(item, nome, "canceled")
                log(f"{nome}: schedule canceled for {item['nome']}.")
                return
            if not os.path.exists(item["video"]):
                self._marcar(item, nome, "failed", "video file not found")
                log(f"FAILED {nome}: the video file {item['nome']} is not there anymore.")
                return
            self._marcar(item, nome, "posting")
            cfg, ativa = self._cfg_da_conta(item["conta"])
            try:
                log(f"{nome}: posting '{item['nome']}' to account '{item['conta']}'...")
                r = self._publicar(nome, cfg, item["video"], item["titulo"], item["descricao"], item["hashtags"],
                                   item["legenda"], item.get("tiktok"), log)
                log(f"OK {nome}: {r}")
                self._marcar(item, nome, "done", str(r)[:200])
            except Exception as e:
                log(f"FAILED {nome}: {e}")
                self._marcar(item, nome, "failed", str(e)[:200])
            finally:
                with self.lock:
                    try:
                        if not ativa:
                            self.cfg["contas"][item["conta"]] = {k: cfg[k] for k in CHAVES_CONTA if k in cfg}
                        self._gravar()  # guarda tokens renovados
                    except Exception:
                        pass
        finally:
            self._contar_espera(-1)

    def _cancelar_agendado(self, id_):
        item = self._achar_item(id_)
        if not item:
            return
        for nome, info in item["plataformas"].items():
            if info["estado"] == "waiting":
                ev = self._ag_cancel.get((id_, nome))
                if ev:
                    ev.set()
                else:
                    self._marcar(item, nome, "canceled")

    def _limpar_finalizados(self):
        with self._ag_lock:
            self.agendados = [
                it for it in self.agendados
                if any(i["estado"] in ("waiting", "posting") for i in it["plataformas"].values())
            ]
        self._salvar_agendados()
        self._desenhar_agendados()

    def _retomar_agendados(self):
        """Ao abrir o app: continua a fila que ficou salva. O que perdeu o horário vai para o próximo pico."""
        try:
            with open(self._ag_arquivo, encoding="utf-8") as f:
                self.agendados = json.load(f)[:40]
        except Exception:
            self.agendados = []
        agora = time.time()
        for item in self.agendados:
            for nome, info in item.get("plataformas", {}).items():
                if info.get("estado") == "posting":
                    info["estado"], info["msg"] = "failed", "interrupted when the app closed; check the platform"
                elif info.get("estado") == "waiting" and nome == "TikTok":
                    info["estado"], info["msg"] = "canceled", "TikTok posts can't be scheduled"
                elif info.get("estado") == "waiting":
                    if not os.path.exists(item.get("video", "")):
                        info["estado"], info["msg"] = "failed", "video file not found"
                        continue
                    if info["alvo"] < agora:
                        try:
                            novo = agenda.proximos_picos(nome, 1, ocupados=self._ocupados(nome))[0]
                            info["alvo"] = novo.timestamp()
                            self._escrever(f"{nome}: '{item['nome']}' missed its time while the app was closed. "
                                           f"Moved to {agenda.descrever(novo)}.")
                        except Exception:
                            info["estado"], info["msg"] = "failed", "could not find the next peak time"
                            continue
                    self._iniciar_espera(item["id"], nome)
        self._salvar_agendados()
        self._desenhar_agendados()

    def _aba_direita(self, nome):
        self._aba = nome
        ativo = {"fg_color": ACENTO_SUAVE, "text_color": "#D3D5FF", "hover_color": ACENTO_SUAVE}
        inativo = {"fg_color": "transparent", "text_color": MUTED, "hover_color": CARD2}
        self.btn_aba_log.configure(**(ativo if nome == "log" else inativo))
        self.btn_aba_ag.configure(**(ativo if nome == "ag" else inativo))
        self.f_log.pack_forget()
        self.f_ag.pack_forget()
        if nome == "log":
            self.f_log.pack(fill="both", expand=True, padx=MARGEM - 4, pady=(0, 12))
        else:
            self.f_ag.pack(fill="both", expand=True, padx=MARGEM - 8, pady=(0, 12))
        self._desenhar_agendados()

    def _desenhar_agendados(self):
        with self._ag_lock:
            itens = list(self.agendados)
        esperando = sum(
            1 for it in itens if any(i["estado"] in ("waiting", "posting") for i in it["plataformas"].values())
        )
        self.btn_aba_ag.configure(text=f"Scheduled · {esperando}" if esperando else "Scheduled")
        if self._aba != "ag":
            return
        for w in self.f_ag.winfo_children():
            w.destroy()
        if not itens:
            ctk.CTkLabel(
                self.f_ag, text="Nothing scheduled yet.\nTurn on “Post at peak US time” and click Schedule.\n"
                "The app stays free for more videos.", font=fonte(12), text_color=MUTED, justify="left", anchor="w",
            ).pack(anchor="w", padx=8, pady=10)
            return
        curto = {"YouTube Shorts": "YouTube", "Instagram Reels": "Instagram", "TikTok": "TikTok"}
        for it in itens:
            ativo = any(i["estado"] in ("waiting", "posting") for i in it["plataformas"].values())
            cartao = ctk.CTkFrame(self.f_ag, fg_color=CARD2, corner_radius=RAIO, border_width=1, border_color=BORDA)
            cartao.pack(fill="x", pady=(0, 8), padx=2)
            topo = ctk.CTkFrame(cartao, fg_color="transparent")
            topo.pack(fill="x", padx=12, pady=(10, 0))
            if ativo:
                ctk.CTkButton(
                    topo, text="Cancel", width=62, height=26, corner_radius=8, fg_color="transparent",
                    border_width=1, border_color=BORDA, hover_color="#2A1519", text_color=VERMELHO,
                    font=fonte(11), command=lambda i=it["id"]: self._cancelar_agendado(i),
                ).pack(side="right")
            titulo = it.get("titulo", "") or it["nome"]
            ctk.CTkLabel(
                topo, text=titulo if len(titulo) <= 34 else titulo[:33] + "…", font=fonte_t(12),
                text_color=TEXTO, anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(
                cartao, text=f"{nome_curto(it['nome'], 36)}  ·  {it.get('conta', '')}", font=fonte(10),
                text_color=MUTED, anchor="w",
            ).pack(fill="x", padx=12, pady=(0, 6))
            for nome, info in it["plataformas"].items():
                est = info["estado"]
                dt = self._dt(info["alvo"])
                if est == "waiting":
                    txt, cor = f"{agenda._fmt(dt)} NY  ·  in {agenda.faltam(dt)}", MUTED
                elif est == "posting":
                    txt, cor = "posting now...", "#A5A7FF"
                elif est == "done":
                    txt, cor = "posted ✓", VERDE
                elif est == "canceled":
                    txt, cor = "canceled", MUTED
                else:
                    txt, cor = f"failed: {info.get('msg', '')}"[:60], VERMELHO
                linha = ctk.CTkFrame(cartao, fg_color="transparent")
                linha.pack(fill="x", padx=12, pady=(0, 3))
                ctk.CTkLabel(linha, text=curto.get(nome, nome), font=fonte_t(11), text_color=TEXTO, width=76,
                             anchor="w").pack(side="left")
                ctk.CTkLabel(linha, text=txt, font=fonte(11), text_color=cor, anchor="w").pack(side="left")
            ctk.CTkFrame(cartao, fg_color="transparent", height=6).pack()
        if any(not any(i["estado"] in ("waiting", "posting") for i in it["plataformas"].values()) for it in itens):
            ctk.CTkButton(
                self.f_ag, text="Clear finished", height=28, corner_radius=RAIO, fg_color="transparent",
                border_width=1, border_color=BORDA, hover_color=CARD2, text_color=MUTED, font=fonte(11),
                command=self._limpar_finalizados,
            ).pack(anchor="e", pady=(2, 0), padx=2)

    # ------------------------------------------------------- clipes automáticos
    def _iniciar_clipes(self):
        """Vigia a pasta de clipes (de outro programa) e posta sozinho no YouTube/Instagram."""
        self.hist = clipes.Historico()
        self.fila_clipes = queue.Queue()
        self._dlg_clipes = None
        self.vigia = clipes.Vigia(self.hist, lambda: self.cfg, self._clipe_novo)
        self.vigia.start()
        threading.Thread(target=self._trabalhador_clipes, daemon=True).start()

    def _clipe_novo(self, caminho):
        self._escrever(f"New clip found: {os.path.basename(caminho)}")
        self.fila_clipes.put(caminho)

    def _trabalhador_clipes(self):
        while True:
            caminho = self.fila_clipes.get()
            try:
                self._processar_clipe(caminho)
            except Exception as e:
                self.hist.atualizar(caminho, estado="falhou", erro=str(e)[:300])
                self._escrever(f"FAILED clip {os.path.basename(caminho)}: {e}")
            time.sleep(4)  # respiro entre clipes (a IA gratuita tem limite por minuto)

    def _processar_clipe(self, caminho):
        nome = os.path.basename(caminho)
        cfg = self.cfg
        if not cfg.get("clipes_ativo"):
            clipes.esquecer(self.hist, caminho)  # desligado enquanto esperava: será visto de novo ao religar
            return
        if not os.path.exists(caminho):
            clipes.esquecer(self.hist, caminho)
            return
        inf = capa.informacoes(caminho)
        if not inf:
            raise RuntimeError("could not read the video file")
        dur = inf[0]
        if dur < 3 or dur > 180:
            self.hist.atualizar(caminho, estado="ignorado", erro=f"length {dur:.0f}s is outside 3s-3min")
            self._escrever(f"Clip {nome}: skipped (shorts must be between 3 seconds and 3 minutes).")
            return
        log = self._escrever
        self.hist.atualizar(caminho, estado="processando")
        log(f"Clip {nome}: watching it to write the text...")
        quadros = [b for _, b in capa.extrair_quadros(caminho, 6)]
        idioma = self.prefs.get("idioma", "auto")
        audio = capa.extrair_audio(caminho) if idioma == "auto" else None
        res = ai.gerar(cfg.get("gemini_api_key", ""), clipes.dica(caminho), nome,
                       int(self.prefs.get("qtd_hashtags", 8)), quadros=quadros, idioma=idioma, audio=audio,
                       titulo_pergunta=bool(self.prefs.get("titulo_pergunta", False)))
        titulo_ = ai.sem_hashtags(res["titulo"])
        descricao = ai.sem_hashtags(res["descricao"])
        hashtags = self._hashtags_finais(" ".join(res["hashtags"]))
        legenda = f"{titulo_}\n\n{descricao}\n\n{' '.join(hashtags)}".strip()
        self.hist.atualizar(caminho, titulo=titulo_, descricao=descricao, hashtags=hashtags)

        auto = [p for p in ("YouTube Shorts", "Instagram Reels") if p in cfg.get("clipes_auto", [])]
        quer_tiktok = bool(cfg.get("clipes_tiktok"))
        arquivo, temporario = caminho, False
        if (auto or quer_tiktok) and cfg.get("clipes_vertical", True):
            arquivo, temporario = compactar.vertical(caminho, log, "Clip")
        resultados = {}
        try:
            for plataforma in auto:
                resultados[plataforma] = self._postar_clipe(plataforma, caminho, arquivo, titulo_, descricao, hashtags, legenda)
            pronto = ""
            if quer_tiktok:
                pronto = caminho
                if temporario:  # guarda o vertical para o TikTok: o temporário seria apagado
                    pasta = os.path.join(BASE, "ready_for_tiktok")
                    os.makedirs(pasta, exist_ok=True)
                    pronto = os.path.join(pasta, os.path.splitext(nome)[0] + "_9x16.mp4")
                    shutil.copy2(arquivo, pronto)
        finally:
            if temporario:
                try:
                    os.remove(arquivo)
                except OSError:
                    pass
        feitos = [p for p, r in resultados.items() if r.startswith("OK")]
        if quer_tiktok:
            estado = "pronto_tiktok"
            log(f"Clip {nome}: ready for TikTok. Open the Clips window and click 'Open in editor' to review and post.")
        elif auto and not feitos:
            estado = "falhou"
        else:
            estado = "postado"
        self.hist.atualizar(caminho, estado=estado, resultados=resultados, pronto=pronto)

    def _postar_clipe(self, plataforma, original, arquivo, titulo_, descricao, hashtags, legenda):
        """Posta um clipe numa plataforma respeitando o limite por dia e o intervalo. Devolve 'OK ...' ou o motivo."""
        cfg = self.cfg
        limite = int(cfg.get("clipes_limite_dia", 3) or 0)
        intervalo = int(cfg.get("clipes_intervalo_min", 60) or 0)
        log = self._escrever
        while True:
            espera = self.hist.espera_para_postar(plataforma, limite, intervalo)
            if espera is None:
                log(f"{plataforma}: daily limit of {limite} reached, skipping this clip.")
                return "skipped: daily limit"
            if espera <= 0:
                break
            if not cfg.get("clipes_ativo"):
                return "skipped: watcher turned off"
            log(f"{plataforma}: waiting {int(espera // 60) + 1} min before the next post...")
            time.sleep(min(espera, 300))
        compactado, temp2 = arquivo, False
        try:
            if plataforma == "YouTube Shorts":
                if cfg.get("prefs", {}).get("compactar", True):
                    compactado, temp2 = compactar.ajustar(arquivo, compactar.LIMITES_MB[plataforma], log, plataforma)
                r = uploaders.postar_youtube(cfg, compactado, titulo_, descricao, hashtags, log)
            else:
                capa_ms = capa.escolher(cfg.get("gemini_api_key", ""), arquivo, titulo_, log) if cfg.get("capa_ia", True) else None
                r = uploaders.postar_instagram(cfg, arquivo, legenda, log, capa_ms)
            self.hist.registrar_postagem(plataforma)
            log(f"OK {plataforma}: {r}")
            return f"OK {r}"
        except Exception as e:
            log(f"FAILED {plataforma}: {e}")
            return f"failed: {str(e)[:150]}"
        finally:
            if temp2:
                try:
                    os.remove(compactado)
                except OSError:
                    pass
            with self.lock:
                try:
                    self._gravar()
                except Exception:
                    pass

    def _carregar_clip(self, caminho):
        """Põe um clipe pronto no editor principal para revisar e postar no TikTok."""
        dados = self.hist.get(caminho)
        arquivo = dados.get("pronto") or caminho
        if not os.path.exists(arquivo):
            messagebox.showwarning("File missing", "The clip file is not there anymore.")
            return
        self._definir_video(arquivo)
        self.titulo.set(dados.get("titulo", ""))
        self.descricao_final.delete("1.0", "end")
        self.descricao_final.insert("1.0", dados.get("descricao", ""))
        self._set_hashtags(" ".join(dados.get("hashtags", [])))
        for nome, chip in self.chips.items():
            chip.ligado = nome == "TikTok"
            chip._pintar()
        self._atualizar_previa()
        self.lift()
        self.focus_force()
        self._escrever(f"Clip loaded in the editor: {os.path.basename(caminho)}")

    def _dialogo_clipes(self):
        if self._dlg_clipes is not None:
            try:
                self._dlg_clipes.lift()
                return
            except Exception:
                self._dlg_clipes = None
        j = ctk.CTkToplevel(self, fg_color=BG)
        self._estilizar_janela(j)
        self._dlg_clipes = j
        j.title("Clips")
        j.geometry("620x780")
        j.minsize(560, 640)
        j.transient(self)

        def fechar():
            self._dlg_clipes = None
            j.destroy()

        j.protocol("WM_DELETE_WINDOW", fechar)

        def guardar(chave, valor):
            self.cfg[chave] = valor
            self._gravar()

        ctk.CTkLabel(j, text="Clips", font=fonte_t(22), text_color=TEXTO, anchor="w").pack(
            fill="x", padx=24, pady=(20, 0))
        ctk.CTkLabel(
            j, text="Point to the folder where your clip app saves videos. New clips get a caption, a vertical "
                    "version and are posted for you.",
            font=fonte(12), text_color=MUTED, anchor="w", justify="left", wraplength=560,
        ).pack(fill="x", padx=24, pady=(2, 12))

        cartao = ctk.CTkFrame(j, fg_color=CARD, corner_radius=RAIO_CARTAO, border_width=1, border_color=BORDA)
        cartao.pack(fill="x", padx=20)

        linha = ctk.CTkFrame(cartao, fg_color="transparent")
        linha.pack(fill="x", padx=MARGEM, pady=(16, 6))
        pasta_var = ctk.StringVar(value=self.cfg.get("clipes_pasta", ""))
        ctk.CTkEntry(
            linha, textvariable=pasta_var, height=40, corner_radius=RAIO, border_width=1, fg_color=CARD2,
            border_color=BORDA, text_color=TEXTO, font=fonte(12), state="readonly",
            placeholder_text="No folder chosen",
        ).pack(side="left", fill="x", expand=True)

        def escolher_pasta():
            p = filedialog.askdirectory(title="Folder where your clips are saved")
            if p:
                guardar("clipes_pasta", p)
                pasta_var.set(p)
                if sw_ativo.get():
                    ligar()

        ctk.CTkButton(
            linha, text="Browse", width=90, height=40, corner_radius=RAIO, fg_color=CARD2, hover_color="#232834",
            border_width=1, border_color=BORDA, text_color=TEXTO, font=fonte_t(12), command=escolher_pasta,
        ).pack(side="left", padx=(8, 0))

        def ligar():
            pasta = self.cfg.get("clipes_pasta", "")
            if not pasta or not os.path.isdir(pasta):
                messagebox.showwarning("Folder", "Choose the clips folder first.")
                sw_ativo.deselect()
                guardar("clipes_ativo", False)
                return
            if not self.cfg.get("clipes_baseline") == pasta:
                n = clipes.marcar_existentes(self.hist, pasta, bool(self.cfg.get("clipes_subpastas")))
                guardar("clipes_baseline", pasta)
                self._escrever(f"Watching {pasta}. {n} existing clip(s) will be ignored; only new ones are posted.")
            guardar("clipes_ativo", True)

        def alternar_ativo():
            if sw_ativo.get():
                ligar()
            else:
                guardar("clipes_ativo", False)
                self._escrever("Clip watcher turned off.")

        def interruptor(texto, chave, padrao=False, comando=None):
            sw = ctk.CTkSwitch(
                cartao, text=texto, font=fonte(13), text_color=TEXTO, progress_color=ACENTO,
                button_color="#F2F3F7", button_hover_color="white", fg_color=BORDA,
                command=comando or (lambda: guardar(chave, bool(sw.get()))),
            )
            sw.pack(anchor="w", padx=MARGEM + 2, pady=(8, 2))
            if self.cfg.get(chave, padrao):
                sw.select()
            return sw

        sw_ativo = interruptor("Watch this folder and post new clips", "clipes_ativo", False, alternar_ativo)
        interruptor("Include subfolders", "clipes_subpastas", False)
        interruptor("Make horizontal clips vertical (9:16, blurred background)", "clipes_vertical", True)

        ctk.CTkLabel(cartao, text="POST AUTOMATICALLY TO", font=fonte_t(10), text_color=MUTED, anchor="w").pack(
            fill="x", padx=MARGEM + 2, pady=(14, 4))
        auto_atual = list(self.cfg.get("clipes_auto", ["YouTube Shorts"]))
        caixas = {}

        def mudou_auto():
            guardar("clipes_auto", [p for p, c in caixas.items() if c.get()])

        for p in ("YouTube Shorts", "Instagram Reels"):
            c = ctk.CTkCheckBox(
                cartao, text=p, font=fonte(13), text_color=TEXTO, fg_color=ACENTO, hover_color=ACENTO_HOVER,
                border_color=BORDA, command=mudou_auto,
            )
            c.pack(anchor="w", padx=MARGEM + 2, pady=3)
            if p in auto_atual:
                c.select()
            caixas[p] = c
        interruptor("Get clips ready for TikTok (you review and post each one)", "clipes_tiktok", False)
        ctk.CTkLabel(
            cartao, text="TikTok requires you to confirm every post, so those clips wait for you in the list below.",
            font=fonte(11), text_color=MUTED, anchor="w", justify="left", wraplength=540,
        ).pack(fill="x", padx=MARGEM + 4, pady=(0, 6))

        limites = ctk.CTkFrame(cartao, fg_color="transparent")
        limites.pack(fill="x", padx=MARGEM, pady=(8, 16))

        def numero(rotulo, chave, padrao):
            col = ctk.CTkFrame(limites, fg_color="transparent")
            col.pack(side="left", padx=(0, 16))
            ctk.CTkLabel(col, text=rotulo, font=fonte_t(10), text_color=MUTED, anchor="w").pack(anchor="w")
            var = ctk.StringVar(value=str(self.cfg.get(chave, padrao)))

            def salvar_num(*_):
                try:
                    guardar(chave, max(0, int(var.get())))
                except ValueError:
                    pass

            var.trace_add("write", salvar_num)
            ctk.CTkEntry(
                col, textvariable=var, width=120, height=36, corner_radius=RAIO, border_width=1, fg_color=CARD2,
                border_color=BORDA, text_color=TEXTO, font=fonte(13),
            ).pack(pady=(4, 0))

        numero("MAX POSTS PER DAY (EACH SITE)", "clipes_limite_dia", 3)
        numero("MINUTES BETWEEN POSTS", "clipes_intervalo_min", 60)

        ctk.CTkLabel(j, text="RECENT CLIPS", font=fonte_t(10), text_color=MUTED, anchor="w").pack(
            fill="x", padx=26, pady=(16, 4))
        lista = ctk.CTkScrollableFrame(
            j, fg_color=CARD, corner_radius=RAIO_CARTAO, border_width=1, border_color=BORDA,
            scrollbar_button_color=BORDA, scrollbar_button_hover_color="#2F3541",
        )
        lista.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        ROTULOS = {
            "na_fila": ("Waiting", MUTED), "processando": ("Working...", AMBAR), "postado": ("Posted", VERDE),
            "pronto_tiktok": ("Ready for TikTok", ACENTO), "falhou": ("Failed", VERMELHO),
            "ignorado": ("Skipped", MUTED),
        }

        def desenhar():
            if self._dlg_clipes is not j:
                return
            for w in lista.winfo_children():
                w.destroy()
            itens = self.hist.lista(30)
            if not itens:
                ctk.CTkLabel(lista, text="No clips yet. New videos that appear in the folder will show up here.",
                             font=fonte(12), text_color=MUTED, wraplength=480, justify="left").pack(padx=12, pady=16)
            for caminho, d in itens:
                linha = ctk.CTkFrame(lista, fg_color="transparent")
                linha.pack(fill="x", padx=8, pady=3)
                txt, cor = ROTULOS.get(d.get("estado"), (d.get("estado", ""), MUTED))
                ctk.CTkLabel(linha, text=nome_curto(caminho, 30), font=fonte(12), text_color=TEXTO, anchor="w").pack(
                    side="left")
                if d.get("estado") == "pronto_tiktok":
                    ctk.CTkButton(
                        linha, text="Done", width=54, height=28, corner_radius=8, fg_color="transparent",
                        border_width=1, border_color=BORDA, text_color=MUTED, hover_color=CARD2, font=fonte(11),
                        command=lambda c=caminho: (self.hist.atualizar(c, estado="postado"), desenhar()),
                    ).pack(side="right", padx=(6, 0))
                    ctk.CTkButton(
                        linha, text="Open in editor", width=104, height=28, corner_radius=8, fg_color=ACENTO,
                        hover_color=ACENTO_HOVER, text_color="white", font=fonte_t(11),
                        command=lambda c=caminho: self._carregar_clip(c),
                    ).pack(side="right", padx=(6, 0))
                ctk.CTkLabel(linha, text=txt, font=fonte_t(11), text_color=cor).pack(side="right", padx=(8, 4))
            j.after(4000, desenhar)

        desenhar()

    # -------------------------------------------------------- configurações
    def _config(self):
        j = ctk.CTkToplevel(self, fg_color=BG)
        self._estilizar_janela(j)
        j.title(f"Settings  ·  account: {self.cfg['conta_ativa']}")
        j.geometry("520x780")
        j.transient(self)
        j.after(150, j.lift)

        abas = ctk.CTkTabview(
            j, fg_color=BG, corner_radius=RAIO_CARTAO, border_width=0,
            segmented_button_selected_color=ACENTO, segmented_button_selected_hover_color=ACENTO_HOVER,
            segmented_button_unselected_color=CARD, segmented_button_unselected_hover_color=CARD2,
            segmented_button_fg_color=CARD, text_color=TEXTO,
        )
        abas.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        campos = {}

        def titulo_campo(aba, texto):
            ctk.CTkLabel(aba, text=texto, font=fonte(12), text_color=MUTED, anchor="w").pack(
                fill="x", padx=6, pady=(10, 4)
            )

        def campo(aba, chave, rotulo, secreto=False):
            titulo_campo(aba, rotulo)
            e = ctk.CTkEntry(
                aba, height=36, corner_radius=RAIO, border_width=1, fg_color=CARD2, border_color=BORDA,
                text_color=TEXTO, font=fonte(13), show="•" if secreto else "",
            )
            e.insert(0, self.cfg.get(chave, ""))
            e.pack(fill="x", padx=6)
            campos[chave] = e
            return e

        def opcoes(aba, chave, rotulo, valores, padrao):
            titulo_campo(aba, rotulo)
            m = ctk.CTkOptionMenu(
                aba, values=valores, height=36, corner_radius=RAIO, fg_color=CARD2, button_color=BORDA,
                button_hover_color=ACENTO, text_color=TEXTO, font=fonte(13), dropdown_fg_color=CARD2,
            )
            m.set(self.cfg.get(chave) or padrao)
            m.pack(fill="x", padx=6)
            campos[chave] = m

        def ajuda(aba, texto):
            ctk.CTkLabel(
                aba, text=texto, font=fonte(11), text_color=MUTED, anchor="w", justify="left", wraplength=420,
            ).pack(fill="x", padx=6, pady=(14, 0))

        a = abas.add("AI")
        campo(a, "gemini_api_key", "Gemini key (free)", True)
        ajuda(a, "Create one at aistudio.google.com > Get API key. The text is written in English for a US audience.")
        e_fixa = campo(a, "hashtag_fixa", "Fixed hashtag (added to every video)")
        ajuda(a, "Always goes at the end of the hashtags, so you can find all your videos by it. Leave empty to skip.")

        a = abas.add("YouTube")
        e = campo(a, "youtube_client_secret", "client_secret.json file")

        def procurar():
            p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
            if p:
                e.delete(0, "end")
                e.insert(0, p)

        ctk.CTkButton(
            a, text="Browse...", width=110, height=30, corner_radius=RAIO, border_width=1,
            fg_color="transparent", border_color=BORDA, hover_color=CARD2, text_color=MUTED,
            font=fonte(12), command=procurar,
        ).pack(anchor="w", padx=6, pady=(8, 0))
        opcoes(a, "youtube_privacidade", "Privacy", ["public", "unlisted", "private"], "public")
        ajuda(a, "Until Google verifies your project, videos are uploaded as private.")
        ajuda(a, f"Each account has its own YouTube settings. This is for account '{self.cfg['conta_ativa']}': "
                 "choose the client_secret.json and sign in with the Google account of its channel.")

        def sair_youtube():
            arq = self.cfg.get("youtube_token_file", "")
            if arq and os.path.exists(arq):
                try:
                    os.remove(arq)
                except OSError as ex:
                    messagebox.showerror("YouTube", str(ex))
                    return
            self._escrever(f"YouTube: signed out of account '{self.cfg['conta_ativa']}'. The next post asks you to sign in.")
            self._atualizar_contas_conectadas()

        ctk.CTkButton(
            a, text="Sign out of YouTube (this account)", height=34, corner_radius=RAIO, fg_color=CARD2,
            hover_color=BORDA, text_color=TEXTO, font=fonte_t(12), command=sair_youtube,
        ).pack(fill="x", padx=6, pady=(14, 0))

        a = abas.add("Instagram")
        campo(a, "instagram_user_id", "Professional account ID")
        campo(a, "instagram_access_token", "Access token", True)
        ajuda(a, "Use a system user token that never expires (Meta Business settings).")

        a = abas.add("TikTok")
        ajuda(a, "To use the default YTK SHORTS login, leave client key and client secret EMPTY and click Connect. "
                 "Only fill them in if you have your own app on TikTok for Developers.")
        campo(a, "tiktok_client_key", "Client key")
        campo(a, "tiktok_client_secret", "Client secret", True)

        def conectar_tiktok():
            for k in ("tiktok_client_key", "tiktok_client_secret"):
                self.cfg[k] = campos[k].get().strip()
            self._gravar()

            def mostrar_tokens():
                for k in ("tiktok_access_token", "tiktok_refresh_token"):
                    try:
                        campos[k].delete(0, "end")
                        campos[k].insert(0, self.cfg.get(k, ""))
                    except Exception:
                        pass  # a janela já foi fechada

            def tarefa():
                try:
                    tiktok_auth.conectar(
                        self.cfg, self._escrever, abrir=False,
                        ao_url=lambda url: self.after(0, lambda: self._dialogo_link(url, "TikTok")),
                    )
                    self._gravar()
                    self.after(0, mostrar_tokens)
                    self.after(0, self.painel_tiktok.invalidar)
                    self.after(0, self._atualizar_contas_conectadas)
                except Exception as e:
                    self._escrever(f"TikTok: {e}")
                finally:
                    self.after(0, self._fechar_dialogo_link)

            threading.Thread(target=tarefa, daemon=True).start()

        ctk.CTkButton(
            a, text="Connect to TikTok", height=36, corner_radius=RAIO, fg_color=ACENTO_SUAVE,
            hover_color="#2D3160", border_width=1, border_color=ACENTO, text_color="#C9CCFF",
            font=fonte_t(13), command=conectar_tiktok,
        ).pack(fill="x", padx=6, pady=(14, 0))
        def desconectar_tiktok():
            for k in ("tiktok_client_key", "tiktok_client_secret"):
                self.cfg[k] = campos[k].get().strip()
            self.cfg["tiktok_access_token"] = campos["tiktok_access_token"].get().strip()

            def tarefa():
                try:
                    tiktok_auth.desconectar(self.cfg, self._escrever)
                    self._gravar()
                    for k in ("tiktok_access_token", "tiktok_refresh_token"):
                        self.after(0, lambda k=k: (campos[k].delete(0, "end")))
                    self._escrever("TikTok: disconnected.")
                except Exception as e:
                    self._escrever(f"TikTok: {e}")

            threading.Thread(target=tarefa, daemon=True).start()

        ctk.CTkButton(
            a, text="Disconnect from TikTok", height=32, corner_radius=RAIO, fg_color=CARD2,
            hover_color=BORDA, text_color=TEXTO, font=fonte(12), command=desconectar_tiktok,
        ).pack(fill="x", padx=6, pady=(8, 0))
        campo(a, "tiktok_refresh_token", "Refresh token (filled in on connect)", True)
        campo(a, "tiktok_access_token", "Access token (filled in on connect)", True)
        opcoes(a, "tiktok_privacidade", "Privacy", ["SELF_ONLY", "PUBLIC_TO_EVERYONE"], "SELF_ONLY")
        ajuda(a, f"In the TikTok developer portal, register this Redirect URI: {tiktok_auth.REDIRECT}")

        a = abas.add("Accounts")
        ajuda(
            a,
            "Each account keeps its own Instagram (ID and token), TikTok (login) and YouTube (login). "
            "The Gemini key and app keys are shared. Switch accounts from the Account menu at the top of the main window.",
        )

        def renomear():
            dialogo = ctk.CTkInputDialog(text="New name for this account:", title="Rename account")
            novo = (dialogo.get_input() or "").strip()
            antigo = self.cfg["conta_ativa"]
            if not novo or novo == antigo:
                return
            if novo in self.cfg["contas"] or novo == NOVA_CONTA:
                messagebox.showwarning("Duplicate name", "An account with that name already exists.")
                return
            self._gravar()
            self.cfg["contas"] = {(novo if n == antigo else n): d for n, d in self.cfg["contas"].items()}
            self.cfg["conta_ativa"] = novo
            self._gravar()
            self._atualizar_menu_contas()
            j.title(f"Settings  ·  account: {novo}")

        def remover():
            ativa = self.cfg["conta_ativa"]
            if len(self.cfg["contas"]) < 2:
                messagebox.showinfo("Only account", "You must keep at least one account.")
                return
            if not messagebox.askyesno("Remove account", f"Remove account '{ativa}' from the app?\nVideos already posted are not affected."):
                return
            self._gravar()
            del self.cfg["contas"][ativa]
            self._carregar_conta(next(iter(self.cfg["contas"])))
            salvar(self.cfg)
            self._atualizar_menu_contas()
            self._atualizar_status()
            self.painel_tiktok.invalidar()
            self._atualizar_contas_conectadas()
            j.destroy()

        ctk.CTkLabel(
            a, text=f"Current account:  {self.cfg['conta_ativa']}", font=fonte_t(15), text_color=TEXTO, anchor="w",
        ).pack(fill="x", padx=6, pady=(18, 0))
        ctk.CTkButton(
            a, text="Rename this account", height=38, corner_radius=RAIO, fg_color=CARD2, hover_color=BORDA,
            text_color=TEXTO, font=fonte_t(12), command=renomear,
        ).pack(fill="x", padx=6, pady=(10, 0))
        ctk.CTkFrame(a, height=1, fg_color=BORDA).pack(fill="x", padx=6, pady=(28, 12))
        ctk.CTkLabel(
            a, text="Danger zone", font=fonte_t(10), text_color=VERMELHO, anchor="w",
        ).pack(fill="x", padx=6)
        ctk.CTkButton(
            a, text="Remove this account", height=34, corner_radius=RAIO, fg_color="transparent",
            hover_color="#2A1519", text_color=VERMELHO, font=fonte(12), anchor="w", command=remover,
        ).pack(fill="x", padx=6, pady=(6, 0))

        def guardar():
            for chave, w in campos.items():
                self.cfg[chave] = w.get().strip()
            self._gravar()
            self._atualizar_status()
            self.painel_tiktok.invalidar()
            self._atualizar_contas_conectadas()
            j.destroy()

        ctk.CTkButton(
            j, text="Save", height=42, corner_radius=RAIO, fg_color=ACENTO, hover_color=ACENTO_HOVER,
            text_color="white", font=fonte_t(14), command=guardar,
        ).pack(fill="x", padx=16, pady=(0, 16))


if __name__ == "__main__":
    if sys.platform == "win32":
        try:  # identidade própria: a barra de tarefas usa o ícone do YTK SHORTS e não o do Python
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YTK.Shorts.App")
        except Exception:
            pass
    App().mainloop()
