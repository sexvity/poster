"""Vigia uma pasta onde outro programa salva clipes e avisa o app quando aparece um vídeo novo e completo.

Também guarda o histórico (arquivo clipes.json) para nunca postar o mesmo clipe duas vezes e respeita
um limite diário e um intervalo mínimo entre postagens em cada plataforma.
"""
import json
import os
import threading
import time

EXTENSOES = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
ARQUIVO = "clipes.json"
ESTADOS_FINAIS = ("postado", "pronto_tiktok", "falhou", "parcial", "aguardando", "ignorado", "antigo")


class Historico:
    """clipes.json: {"clipes": {caminho: {...}}, "postagens": {plataforma: [timestamps]}}"""

    def __init__(self, arquivo=ARQUIVO):
        self.arquivo = arquivo
        self.lock = threading.RLock()
        self.dados = {"clipes": {}, "postagens": {}, "pausas": {}}
        try:
            with open(arquivo, encoding="utf-8") as f:
                lido = json.load(f)
            self.dados["clipes"] = lido.get("clipes", {})
            self.dados["postagens"] = lido.get("postagens", {})
            self.dados["pausas"] = lido.get("pausas", {})
        except Exception:
            pass

    def _gravar(self):
        tmp = self.arquivo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.dados, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.arquivo)

    def conhece(self, caminho):
        with self.lock:
            return caminho in self.dados["clipes"]

    def get(self, caminho):
        with self.lock:
            return dict(self.dados["clipes"].get(caminho, {}))

    def atualizar(self, caminho, **campos):
        with self.lock:
            item = self.dados["clipes"].setdefault(caminho, {"quando": time.time()})
            item.update(campos)
            self._gravar()

    def lista(self, limite=40):
        """Clipes mais recentes primeiro: [(caminho, dados)]."""
        with self.lock:
            itens = [(c, dict(d)) for c, d in self.dados["clipes"].items() if d.get("estado") != "antigo"]
        itens.sort(key=lambda x: x[1].get("quando", 0), reverse=True)
        return itens[:limite]

    # ---- pausas (ex.: o YouTube barrou os envios do dia)
    def pausar(self, plataforma, segundos):
        with self.lock:
            self.dados["pausas"][plataforma] = time.time() + segundos
            self._gravar()

    def pausa_restante(self, plataforma):
        with self.lock:
            return max(0, self.dados["pausas"].get(plataforma, 0) - time.time())

    def aguardando(self):
        """Clipes que ficaram esperando uma plataforma voltar: [(caminho, [plataformas])]."""
        with self.lock:
            return [(c, [p for p, r in (d.get("resultados") or {}).items() if str(r).startswith("waiting")])
                    for c, d in self.dados["clipes"].items() if d.get("estado") == "aguardando"]

    # ---- limites de postagem
    def _recentes(self, plataforma, janela_s):
        agora = time.time()
        return [t for t in self.dados["postagens"].get(plataforma, []) if agora - t < janela_s]

    def espera_para_postar(self, plataforma, limite_dia, intervalo_min):
        """Segundos até poder postar de novo nessa plataforma (0 = pode agora; None = limite do dia atingido)."""
        with self.lock:
            dia = self._recentes(plataforma, 24 * 3600)
            if limite_dia and len(dia) >= limite_dia:
                return None
            if dia and intervalo_min:
                falta = max(dia) + intervalo_min * 60 - time.time()
                return max(0, falta)
            return 0

    def registrar_postagem(self, plataforma):
        with self.lock:
            lista = self._recentes(plataforma, 7 * 24 * 3600)
            lista.append(time.time())
            self.dados["postagens"][plataforma] = lista
            self._gravar()


def listar_videos(pasta, recursivo=False):
    """[(caminho, tamanho, mtime)] dos vídeos da pasta."""
    achados = []
    if not pasta or not os.path.isdir(pasta):
        return achados
    if recursivo:
        percurso = ((r, fs) for r, _, fs in os.walk(pasta))
    else:
        percurso = [(pasta, [f for f in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, f))])]
    for raiz, arquivos in percurso:
        for nome in arquivos:
            if nome.lower().endswith(EXTENSOES) and not nome.startswith((".", "~")):
                caminho = os.path.join(raiz, nome)
                try:
                    st = os.stat(caminho)
                    achados.append((caminho, st.st_size, st.st_mtime))
                except OSError:
                    pass
    return achados


def dica(caminho):
    """Texto de apoio para a IA sobre o clipe: lê um arquivo .json ou .txt com o mesmo nome (se o outro programa
    gravar um) e, se não houver, usa o nome do arquivo."""
    base = os.path.splitext(caminho)[0]
    try:
        with open(base + ".json", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict):
            partes = []
            for chave in ("title", "titulo", "streamer", "channel", "game", "jogo", "category", "description",
                          "descricao", "topic", "tema"):
                v = dados.get(chave)
                if v and isinstance(v, (str, int, float)):
                    partes.append(f"{chave}: {v}")
            if partes:
                return "; ".join(partes)[:600]
    except Exception:
        pass
    try:
        with open(base + ".txt", encoding="utf-8", errors="replace") as f:
            texto = f.read(600).strip()
        if texto:
            return texto
    except Exception:
        pass
    nome = os.path.splitext(os.path.basename(caminho))[0].replace("_", " ").replace("-", " ").strip()
    return f"Live stream clip. File name hint: {nome}" if nome else "Live stream clip"


class Vigia(threading.Thread):
    """Olha a pasta de tempos em tempos. Um arquivo só conta como pronto quando o tamanho para de mudar."""

    def __init__(self, historico, obter_config, ao_encontrar, intervalo=15):
        super().__init__(daemon=True)
        self.h = historico
        self.obter_config = obter_config
        self.ao_encontrar = ao_encontrar
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._pendentes = {}  # caminho -> (tamanho, mtime)

    def parar(self):
        self._parar.set()

    def run(self):
        while not self._parar.is_set():
            try:
                self.varrer()
            except Exception:
                pass
            self._parar.wait(self.intervalo)

    def varrer(self):
        cfg = self.obter_config()
        if not cfg.get("clipes_ativo") or not cfg.get("clipes_pasta"):
            self._pendentes.clear()
            return []
        novos = []
        vistos_agora = set()
        for caminho, tam, mtime in sorted(listar_videos(cfg["clipes_pasta"], bool(cfg.get("clipes_subpastas"))),
                                          key=lambda x: x[2]):  # do mais antigo para o mais novo
            if self.h.conhece(caminho):
                continue
            vistos_agora.add(caminho)
            anterior = self._pendentes.get(caminho)
            parado = time.time() - mtime > 10
            if anterior == (tam, mtime) and parado and tam > 0:
                self._pendentes.pop(caminho, None)
                self.h.atualizar(caminho, estado="na_fila", nome=os.path.basename(caminho))
                novos.append(caminho)
                self.ao_encontrar(caminho)
            else:
                self._pendentes[caminho] = (tam, mtime)
        for c in list(self._pendentes):
            if c not in vistos_agora:
                del self._pendentes[c]
        return novos


def liberar_antigos(historico):
    """Clipes que versões anteriores marcaram como "antigos" (ignorados) voltam a ser candidatos a postagem.
    Quem já foi postado (ou falhou, ou foi ignorado por duração) continua no histórico e não é postado de novo."""
    with historico.lock:
        antigos = [c for c, d in historico.dados["clipes"].items() if d.get("estado") == "antigo"]
        for c in antigos:
            historico.dados["clipes"].pop(c, None)
        if antigos:
            historico._gravar()
    return len(antigos)


def marcar_existentes(historico, pasta, recursivo=False):
    """Ao ligar o vigia pela primeira vez: o que já está na pasta é considerado antigo (não será postado)."""
    n = 0
    for caminho, _, _ in listar_videos(pasta, recursivo):
        if not historico.conhece(caminho):
            historico.atualizar(caminho, estado="antigo", nome=os.path.basename(caminho))
            n += 1
    return n


def esquecer(historico, caminho):
    """Tira um clipe do histórico (será detectado de novo na próxima varredura)."""
    with historico.lock:
        historico.dados["clipes"].pop(caminho, None)
        historico._gravar()
