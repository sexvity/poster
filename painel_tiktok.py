"""Painel 'Post to TikTok' que segue as regras de interface do TikTok para a Content Posting API.

Regras atendidas: mostra o nome da conta que vai receber o vídeo; a privacidade vem das opções que o TikTok
devolve e NÃO tem valor padrão; comentário/dueto/stitch começam desligados (e ficam travados se a conta os
desativou); divulgação comercial começa desligada e exige uma opção quando ligada; conteúdo de marca não pode ser
privado; declaração de consentimento com os links do TikTok; nada é enviado sem o clique do usuário.
O texto fica em inglês de propósito: quem avalia o app no TikTok lê em inglês.
"""
import threading
import webbrowser

import customtkinter as ctk

import uploaders

ROTULOS = {
    "PUBLIC_TO_EVERYONE": "Everyone",
    "MUTUAL_FOLLOW_FRIENDS": "Friends",
    "FOLLOWER_OF_CREATOR": "Followers",
    "SELF_ONLY": "Only me",
}
ESCOLHA = "Select who can view this video"
URL_MUSICA = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
URL_MARCA = "https://www.tiktok.com/legal/page/global/bc-policy/en"


class PainelTikTok(ctk.CTkFrame):
    def __init__(self, master, cores, fonte, obter_cfg, log, ao_mudar=None):
        super().__init__(master, fg_color=cores["CARD2"], corner_radius=cores["RAIO"])
        self.c, self.fonte, self.obter_cfg, self.log, self.ao_mudar = cores, fonte, obter_cfg, log, ao_mudar
        self.info = None          # resposta do TikTok (creator info)
        self.erro = ""
        self.consultando = False
        self.visivel = False
        # estado em variáveis do Python (os widgets só mostram)
        self.privacidade = ""     # código do TikTok; vazio = ainda não escolhida
        self.comentar = self.dueto = self.stitch = False
        self.comercial = self.proprio = self.terceiros = False
        self._montar()

    # ----------------------------------------------------------------- visual
    def _montar(self):
        c, f = self.c, self.fonte
        pad = dict(padx=12, anchor="w")
        ctk.CTkLabel(self, text="Post to TikTok", font=f(12, "bold"), text_color=c["TEXTO"]).pack(pady=(10, 0), **pad)
        self.quem = ctk.CTkLabel(self, text="Checking your TikTok account...", font=f(11), text_color=c["MUTED"],
                                 anchor="w", justify="left", wraplength=360)
        self.quem.pack(fill="x", padx=12, pady=(2, 6))

        ctk.CTkLabel(self, text="Who can view this video", font=f(11), text_color=c["MUTED"]).pack(**pad)
        self.menu = ctk.CTkOptionMenu(
            self, values=[ESCOLHA], command=self._escolheu_privacidade, height=30, corner_radius=c["RAIO"],
            fg_color=c["CARD"], button_color=c["BORDA"], button_hover_color="#2F3541", dropdown_fg_color=c["CARD"],
            dropdown_hover_color=c["ACENTO_SUAVE"], text_color=c["TEXTO"], font=f(12), dropdown_font=f(12),
        )
        self.menu.set(ESCOLHA)
        self.menu.pack(fill="x", padx=12, pady=(2, 8))

        ctk.CTkLabel(self, text="Allow users to", font=f(11), text_color=c["MUTED"]).pack(**pad)
        linha = ctk.CTkFrame(self, fg_color="transparent")
        linha.pack(fill="x", padx=12, pady=(2, 6))
        self.cb = {}
        for chave, texto in (("comentar", "Comment"), ("dueto", "Duet"), ("stitch", "Stitch")):
            cb = ctk.CTkCheckBox(
                linha, text=texto, font=f(12), text_color=c["TEXTO"], fg_color=c["ACENTO"], hover_color=c["ACENTO"],
                border_color=c["BORDA"], checkbox_width=18, checkbox_height=18,
                command=lambda k=chave: self._alternar(k),
            )
            cb.pack(side="left", padx=(0, 14))
            self.cb[chave] = cb

        self.sw = ctk.CTkSwitch(
            self, text="Disclose video content (promotes a brand, product or service)", font=f(12),
            text_color=c["TEXTO"], progress_color=c["ACENTO"], button_color="#F2F3F7", button_hover_color="white",
            fg_color=c["BORDA"], command=self._alternar_comercial,
        )
        self.sw.pack(padx=12, pady=(2, 4), anchor="w")
        self.caixa_comercial = ctk.CTkFrame(self, fg_color="transparent")
        self.cb_proprio = ctk.CTkCheckBox(
            self.caixa_comercial, text="Your brand", font=f(12), text_color=c["TEXTO"], fg_color=c["ACENTO"],
            hover_color=c["ACENTO"], border_color=c["BORDA"], checkbox_width=18, checkbox_height=18,
            command=lambda: self._alternar("proprio"),
        )
        self.cb_terceiros = ctk.CTkCheckBox(
            self.caixa_comercial, text="Branded content", font=f(12), text_color=c["TEXTO"], fg_color=c["ACENTO"],
            hover_color=c["ACENTO"], border_color=c["BORDA"], checkbox_width=18, checkbox_height=18,
            command=lambda: self._alternar("terceiros"),
        )
        self.cb_proprio.pack(side="left", padx=(0, 14))
        self.cb_terceiros.pack(side="left")
        self.aviso_comercial = ctk.CTkLabel(self, text="", font=f(11), text_color="#E0A23B", anchor="w",
                                            justify="left", wraplength=360)

        self.consentimento = ctk.CTkFrame(self, fg_color="transparent")
        self.consentimento.pack(fill="x", padx=12, pady=(6, 0))
        self.nota = ctk.CTkLabel(
            self, text="After you post, it can take a few minutes for the video to appear on your profile.",
            font=f(11), text_color=c["MUTED"], anchor="w", justify="left", wraplength=360,
        )
        self.nota.pack(fill="x", padx=12, pady=(4, 10))
        self._desenhar_consentimento()

    def _link(self, pai, texto, url):
        lbl = ctk.CTkLabel(pai, text=texto, font=self.fonte(11), text_color="#9AA0FF", cursor="hand2")
        lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))
        return lbl

    def _desenhar_consentimento(self):
        for w in self.consentimento.winfo_children():
            w.destroy()
        c, f = self.c, self.fonte
        ctk.CTkLabel(self.consentimento, text="By posting, you agree to TikTok's", font=f(11),
                     text_color=c["MUTED"]).pack(side="left")
        if self.comercial and self.terceiros:
            self._link(self.consentimento, " Branded Content Policy", URL_MARCA).pack(side="left")
            ctk.CTkLabel(self.consentimento, text=" and", font=f(11), text_color=c["MUTED"]).pack(side="left")
        self._link(self.consentimento, " Music Usage Confirmation", URL_MUSICA).pack(side="left")

    # --------------------------------------------------------------- eventos
    def _alternar(self, chave):
        cb = {"proprio": self.cb_proprio, "terceiros": self.cb_terceiros}.get(chave) or self.cb[chave]
        setattr(self, chave, bool(cb.get()))
        if chave == "terceiros":
            self._atualizar_opcoes_privacidade()
        self._atualizar_comercial()
        if self.ao_mudar:
            self.ao_mudar()

    def _alternar_comercial(self):
        self.comercial = bool(self.sw.get())
        if self.comercial:
            self.caixa_comercial.pack(padx=12, pady=(0, 4), anchor="w", before=self.consentimento)
            self.aviso_comercial.pack(fill="x", padx=12, pady=(0, 2), before=self.consentimento)
        else:
            self.caixa_comercial.pack_forget()
            self.aviso_comercial.pack_forget()
        self._atualizar_opcoes_privacidade()
        self._atualizar_comercial()
        if self.ao_mudar:
            self.ao_mudar()

    def _atualizar_comercial(self):
        if self.comercial and self.terceiros:
            txt = 'Your video will be labeled "Paid partnership".'
        elif self.comercial and self.proprio:
            txt = 'Your video will be labeled "Promotional content".'
        elif self.comercial:
            txt = "You need to indicate if your content promotes yourself, a third party, or both."
        else:
            txt = ""
        self.aviso_comercial.configure(text=txt)
        self._desenhar_consentimento()

    def _marca_privada_bloqueada(self):
        return self.comercial and self.terceiros

    def _opcoes_de_privacidade(self):
        opcoes = [o for o in (self.info or {}).get("privacy_level_options", []) if o in ROTULOS]
        if self._marca_privada_bloqueada():
            opcoes = [o for o in opcoes if o != "SELF_ONLY"]  # conteúdo de marca não pode ser privado
        return opcoes

    def _atualizar_opcoes_privacidade(self):
        opcoes = self._opcoes_de_privacidade()
        if self.privacidade and self.privacidade not in opcoes:
            if self.privacidade == "SELF_ONLY" and self._marca_privada_bloqueada():
                self.log("TikTok: branded content visibility cannot be set to private. Choose another option.")
            self.privacidade = ""
        self.menu.configure(values=[ESCOLHA] + [ROTULOS[o] for o in opcoes])
        self.menu.set(ROTULOS[self.privacidade] if self.privacidade else ESCOLHA)

    def _escolheu_privacidade(self, rotulo):
        inverso = {v: k for k, v in ROTULOS.items()}
        self.privacidade = inverso.get(rotulo, "")
        if self.ao_mudar:
            self.ao_mudar()

    # ------------------------------------------------------ dados do TikTok
    def invalidar(self):
        """Esquece os dados (troca de conta, nova conexão) e consulta de novo se o painel está à mostra."""
        self.info, self.erro = None, ""
        self.privacidade = ""
        self.menu.configure(values=[ESCOLHA])
        self.menu.set(ESCOLHA)
        if self.visivel:
            self.consultar()

    def consultar(self):
        if self.consultando:
            return
        self.consultando = True
        self.quem.configure(text="Checking your TikTok account...", text_color=self.c["MUTED"])

        def tarefa():
            info, erro = None, ""
            try:
                info = uploaders.tiktok_creator_info(self.obter_cfg())
            except Exception as e:  # noqa: BLE001
                erro = str(e)
            self.after(0, lambda: self._aplicar(info, erro))

        threading.Thread(target=tarefa, daemon=True).start()

    def _aplicar(self, info, erro):
        self.consultando = False
        self.info, self.erro = info, erro
        if not info:
            self.quem.configure(text=f"Could not read your TikTok account. {erro or 'Connect it in Settings > TikTok.'}",
                                text_color="#E5646E")
            return
        nome = info.get("creator_nickname") or info.get("creator_username") or "your account"
        user = info.get("creator_username")
        self.quem.configure(text=f"Posting to: {nome}" + (f" (@{user})" if user else ""), text_color=self.c["TEXTO"])
        # interações desligadas nas configurações da conta ficam travadas e sem marca
        for chave, bloqueado in (("comentar", info.get("comment_disabled")), ("dueto", info.get("duet_disabled")),
                                 ("stitch", info.get("stitch_disabled"))):
            cb = self.cb[chave]
            cb.deselect()
            setattr(self, chave, False)
            cb.configure(state="disabled" if bloqueado else "normal")
        self._atualizar_opcoes_privacidade()

    def mostrar(self, sim, **pack):
        if sim and not self.visivel:
            self.visivel = True
            self.pack(**pack)
            if self.info is None:
                self.consultar()
        elif not sim and self.visivel:
            self.visivel = False
            self.pack_forget()

    # ------------------------------------------------------------ validação
    def validar(self, duracao_s=None):
        """Devolve as opções escolhidas ou levanta ValueError com a explicação do que falta."""
        if not self.info:
            raise ValueError("TikTok: your account could not be checked. Connect it in Settings > TikTok and try again.")
        if self.info.get("can_post") is False or self.info.get("can_post_more") is False:
            raise ValueError("TikTok: this account can't post right now. Please try again later.")
        limite = self.info.get("max_video_post_duration_sec")
        if limite and duracao_s and duracao_s > limite:
            raise ValueError(f"TikTok: this video is {int(duracao_s)} s, longer than the {limite} s allowed for this account.")
        if not self.privacidade:
            raise ValueError("TikTok: select who can view this video.")
        if self.comercial and not (self.proprio or self.terceiros):
            raise ValueError("You need to indicate if your content promotes yourself, a third party, or both.")
        if self._marca_privada_bloqueada() and self.privacidade == "SELF_ONLY":
            raise ValueError("TikTok: branded content visibility cannot be set to private.")
        return {
            "privacidade": self.privacidade,
            "comentar": self.comentar, "dueto": self.dueto, "stitch": self.stitch,
            "comercial": self.comercial, "proprio": self.comercial and self.proprio,
            "terceiros": self.comercial and self.terceiros,
        }
