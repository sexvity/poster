"""YTK SHORTS: posts to YouTube Shorts, Instagram Reels and TikTok (US audience)."""
import json
import os
import queue
import re
import shutil
import sys
import threading
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
import compactar  # noqa: E402
from painel_tiktok import PainelTikTok  # noqa: E402
import tiktok_auth  # noqa: E402
import uploaders  # noqa: E402

CONFIG = "config.json"
PLATAFORMAS = ["YouTube Shorts", "Instagram Reels", "TikTok"]

# Paleta: tudo escuro, um único destaque
BG = "#0D0F14"
CARD = "#14171D"
CARD2 = "#1B1F27"
BORDA = "#262B35"
TEXTO = "#E8EAF0"
MUTED = "#8B91A1"
ACENTO = "#6366F1"
ACENTO_HOVER = "#4F52D9"
ACENTO_SUAVE = "#23264A"
VERDE = "#3FB68B"
AMBAR = "#E0A23B"
VERMELHO = "#E5646E"
PERIGO = "#B4474F"
PERIGO_HOVER = "#963A41"
FAMILIA = "Segoe UI"

# Dados que pertencem a cada conta (o resto, como a chave do Gemini e as chaves dos apps, é compartilhado)
CHAVES_CONTA = [
    "instagram_user_id", "instagram_access_token",
    "tiktok_access_token", "tiktok_refresh_token", "tiktok_privacidade",
    "youtube_token_file",
]
NOVA_CONTA = "＋  Add account..."

RAIO = 10  # cantos de botões e campos
RAIO_CARTAO = 14
MARGEM = 16  # espaço lateral dentro dos cartões

ctk.set_appearance_mode("dark")


def fonte(tam=13, peso="normal"):
    return ctk.CTkFont(family=FAMILIA, size=tam, weight=peso)


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
            master, text=texto, height=32, corner_radius=16, border_width=1,
            font=fonte(12, "bold"), command=self._alternar,
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
        try:
            self.iconbitmap(os.path.join(RECURSOS, "ytk.ico"))
            # reforço: ícone em PNG de alta resolução (barra de tarefas nítida)
            from PIL import Image as _I, ImageTk as _IT

            self._icone_tk = _IT.PhotoImage(_I.open(os.path.join(RECURSOS, "ytk.png")).resize((256, 256)))
            self.after(300, lambda: self.iconphoto(True, self._icone_tk))
        except Exception:
            pass
        self.geometry("1020x740")
        self.minsize(920, 680)
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
        self._montar()
        self._atualizar_previa()
        self._atualizar_status()
        self._atualizar_contas_conectadas()
        self.after(150, self._ler_fila)
        self.after(30000, self._tic)

    # ------------------------------------------------------ login no navegador
    def _dialogo_link(self, url, nome):
        """Pergunta como abrir o link de login: no navegador padrão ou copiando (para colar em outro navegador)."""
        self._fechar_dialogo_link()
        j = ctk.CTkToplevel(self, fg_color=BG)
        self._dlg_link = j
        j.title(f"Sign in to {nome}")
        j.geometry("460x250")
        j.resizable(False, False)
        j.transient(self)
        j.after(100, j.lift)
        ctk.CTkLabel(j, text=f"Sign in to {nome}", font=fonte(16, "bold"), text_color=TEXTO).pack(
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
            hover_color=ACENTO_HOVER, text_color="white", font=fonte(13, "bold"), command=abrir,
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
        c.pack(fill="both" if expandir else "x", expand=expandir, pady=(0, 12))
        return c

    def _rotulo(self, pai, texto, topo=12):
        ctk.CTkLabel(
            pai, text=texto, font=fonte(11, "bold"), text_color=MUTED, anchor="w",
        ).pack(fill="x", padx=MARGEM + 2, pady=(topo, 5))

    def _passo(self, pai, numero, texto, topo=16):
        """Título do cartão com um número em círculo: deixa claro a ordem (1, 2, 3)."""
        linha = ctk.CTkFrame(pai, fg_color="transparent")
        linha.pack(fill="x", padx=MARGEM, pady=(topo, 8))
        ctk.CTkLabel(
            linha, text=str(numero), width=22, height=22, corner_radius=11, fg_color=ACENTO_SUAVE,
            text_color="#C9CCFF", font=fonte(11, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(linha, text=texto, font=fonte(13, "bold"), text_color=TEXTO).pack(side="left", padx=(8, 0))
        return linha

    def _entrada(self, pai, var=None):
        e = ctk.CTkEntry(
            pai, textvariable=var, height=38, corner_radius=RAIO, border_width=1,
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
        topo.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 10))
        try:
            from PIL import Image as _Img

            _logo = _Img.open(os.path.join(RECURSOS, "ytk.png")).convert("RGBA")
            self._logo_img = ctk.CTkImage(light_image=_logo, dark_image=_logo, size=(52, 52))
            ctk.CTkLabel(topo, text="", image=self._logo_img, width=52, height=52).pack(side="left")
        except Exception:
            ctk.CTkLabel(
                topo, text="▶", width=34, height=34, corner_radius=10, fg_color=ACENTO, text_color="white",
                font=fonte(15, "bold"),
            ).pack(side="left")
        textos = ctk.CTkFrame(topo, fg_color="transparent")
        textos.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(textos, text="YTK SHORTS", font=fonte(18, "bold"), text_color=TEXTO, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            textos, text="English captions and posting for a US audience",
            font=fonte(11), text_color=MUTED, anchor="w",
        ).pack(anchor="w")
        ctk.CTkButton(
            topo, text="Settings", width=112, height=30, corner_radius=RAIO, border_width=1,
            fg_color="transparent", border_color=BORDA, hover_color=CARD2, text_color=MUTED,
            font=fonte(12), command=self._config,
        ).pack(side="right")
        self.menu_conta = ctk.CTkOptionMenu(
            topo, values=list(self.cfg["contas"]) + [NOVA_CONTA], command=self._trocar_conta, width=150, height=30,
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
        corpo.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 6))
        corpo.grid_columnconfigure((0, 1), weight=1, uniform="col")
        corpo.grid_rowconfigure(0, weight=1)
        # a coluna esquerda rola (o painel do TikTok a deixa mais alta que a janela)
        esq = ctk.CTkScrollableFrame(
            corpo, fg_color="transparent", scrollbar_button_color=BORDA, scrollbar_button_hover_color="#2F3541",
        )
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.esq = esq
        dire = ctk.CTkFrame(corpo, fg_color="transparent")
        dire.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        # ---- Coluna esquerda: vídeo + publicação
        c1 = self._cartao(esq, expandir=True)
        self._passo(c1, 1, "Video and topic")
        self.btn_video = ctk.CTkButton(
            c1, text="Choose video...", height=44, corner_radius=RAIO, border_width=1, anchor="w",
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
        self.btn_gerar = ctk.CTkButton(
            c1, text="Generate text", height=42, corner_radius=RAIO, border_width=1,
            fg_color=ACENTO_SUAVE, hover_color="#2D3160", border_color=ACENTO, text_color="#C9CCFF",
            font=fonte(13, "bold"), command=self._gerar,
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
            c3, text="Auto mode (no review)", font=fonte(12), text_color=MUTED,
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
        ctk.CTkLabel(cab, text="TITLE", font=fonte(11, "bold"), text_color=MUTED).pack(side="left")
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
            dire, text="Post now", height=46, corner_radius=RAIO, fg_color=ACENTO,
            hover_color=ACENTO_HOVER, text_color="white", font=fonte(15, "bold"), command=self._postar,
        )
        self.btn_postar.pack(fill="x", pady=(0, 8))
        self.barra = ctk.CTkProgressBar(
            dire, mode="indeterminate", height=3, corner_radius=2, fg_color=BORDA, progress_color=ACENTO,
        )
        self.barra.pack(fill="x", pady=(0, 10))
        self.barra.set(0)

        c4 = self._cartao(dire, expandir=True)
        self._rotulo(c4, "ACTIVITY", 14)
        self.log = ctk.CTkTextbox(
            c4, height=90, corner_radius=RAIO, border_width=0, fg_color=CARD,
            text_color=MUTED, font=fonte(12), wrap="word", state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=MARGEM - 4, pady=(0, 12))
        self.log.tag_config("ok", foreground=VERDE)
        self.log.tag_config("erro", foreground=VERMELHO)
        self.log.tag_config("hora", foreground="#5A6072")
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
            return
        linhas = []
        for nome in PLATAFORMAS:
            if self.chips[nome].ligado:
                try:
                    alvo = agenda.proximo_pico(nome)
                    linhas.append(f"{nome}: {agenda.descrever(alvo)} (in {agenda.faltam(alvo)})")
                except Exception as e:
                    linhas.append(f"{nome}: {e}")
        if not linhas:
            self.previa.configure(text="Choose at least one platform.")
        else:
            self.previa.configure(
                text="\n".join(linhas) + "\nKeep the app open and the computer on until then."
            )

    def _guardar_preferencias(self):
        self.prefs = {
            "plataformas": {n: self.chips[n].ligado for n in PLATAFORMAS},
            "agendar": bool(self.sw_agenda.get()),
            "auto": bool(self.sw_auto.get()),
            "compactar": bool(self.sw_compactar.get()),
        }
        self.cfg["prefs"] = self.prefs
        self._gravar()

    # --------------------------------------------------------------- ações
    def _escolher(self):
        caminho = filedialog.askopenfilename(
            filetypes=[("Videos", "*.mp4 *.mov *.m4v *.webm *.mkv"), ("All files", "*.*")]
        )
        if caminho:
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
        self.btn_gerar.configure(state="disabled", text="Generating...")

        def tarefa():
            try:
                self._escrever("Watching the video to write about what appears in it...")
                quadros = [b for _, b in capa.extrair_quadros(self.video, 6)]
                if not quadros:
                    self._escrever("Could not extract frames; using only your description.")
                res = ai.gerar(chave, descricao, nome, quadros=quadros)
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
        agendar = bool(self.sw_agenda.get())

        planos = []
        for nome in escolhidas:
            try:
                planos.append((nome, agenda.proximo_pico(nome) if agendar else None))
            except Exception as e:
                messagebox.showerror("Peak time", str(e))
                return

        self._guardar_preferencias()
        self.cancelar.clear()
        self.modo_agendado = agendar
        with self.lock:
            self.ativos = len(planos)
        self._botao_estado()
        for nome, alvo in planos:
            threading.Thread(
                target=self._tarefa, args=(nome, alvo, video, titulo, descricao, hashtags, legenda), daemon=True
            ).start()

    def _tarefa(self, nome, alvo, video, titulo, descricao, hashtags, legenda):
        arquivo, temporario = video, False
        conta = self.cfg.get("conta_ativa", "")
        try:
            if alvo:
                agenda.evitar_suspensao(True)
                self._escrever(f"{nome}: scheduled for {agenda.descrever(alvo)}.")
                if not agenda.esperar(alvo, self.cancelar, lambda t: self._escrever(f"{nome}: {t}")):
                    self._escrever(f"{nome}: schedule canceled.")
                    return
            self._escrever(f"{nome}: posting to account '{conta}'...")
            log = lambda m: self._escrever(m)  # noqa: E731
            if nome != "Instagram Reels" and self.cfg.get("prefs", {}).get("compactar", True):
                arquivo, temporario = compactar.ajustar(video, compactar.LIMITES_MB[nome], log, nome)
            if nome == "YouTube Shorts":
                r = uploaders.postar_youtube(self.cfg, arquivo, titulo, descricao, hashtags, log)
            elif nome == "Instagram Reels":
                r = uploaders.postar_instagram(self.cfg, video, legenda, log)
            else:
                capa_ms = None
                if self.cfg.get("capa_ia", True):
                    log("TikTok: AI is choosing the cover...")
                    capa_ms = capa.escolher(self.cfg.get("gemini_api_key", ""), video, titulo, log)
                try:
                    r = uploaders.postar_tiktok(self.cfg, arquivo, legenda, log, capa_ms, self._opcoes_tiktok)
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
                    r = uploaders.postar_tiktok(self.cfg, arquivo, legenda, log, None, self._opcoes_tiktok)
            self._escrever(f"OK {nome}: {r}")
        except Exception as e:
            self._escrever(f"FAILED {nome}: {e}")
        finally:
            if temporario:
                try:
                    os.remove(arquivo)
                except OSError:
                    pass
            if alvo:
                agenda.evitar_suspensao(False)
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

    # -------------------------------------------------------- configurações
    def _config(self):
        j = ctk.CTkToplevel(self, fg_color=BG)
        j.title(f"Settings  ·  account: {self.cfg['conta_ativa']}")
        j.geometry("520x780")
        j.transient(self)
        j.after(150, j.lift)

        abas = ctk.CTkTabview(
            j, fg_color=CARD, corner_radius=RAIO_CARTAO, border_width=1, border_color=BORDA,
            segmented_button_selected_color=ACENTO, segmented_button_selected_hover_color=ACENTO_HOVER,
            segmented_button_unselected_color=CARD2, segmented_button_unselected_hover_color=BORDA,
            segmented_button_fg_color=CARD2, text_color=TEXTO,
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
            font=fonte(13, "bold"), command=conectar_tiktok,
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

        ctk.CTkButton(
            a, text="Rename this account", height=34, corner_radius=RAIO, border_width=1, fg_color="transparent",
            border_color=BORDA, hover_color=CARD2, text_color=TEXTO, font=fonte(12), command=renomear,
        ).pack(fill="x", padx=6, pady=(14, 0))
        ctk.CTkButton(
            a, text="Remove this account", height=34, corner_radius=RAIO, border_width=1, fg_color="transparent",
            border_color=PERIGO, hover_color="#3A1F22", text_color="#F0A0A6", font=fonte(12), command=remover,
        ).pack(fill="x", padx=6, pady=(8, 0))

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
            text_color="white", font=fonte(14, "bold"), command=guardar,
        ).pack(fill="x", padx=16, pady=(0, 16))


if __name__ == "__main__":
    App().mainloop()
