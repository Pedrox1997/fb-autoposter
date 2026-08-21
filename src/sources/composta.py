"""Varias pastas atendendo a mesma etiqueta, em ordem de prioridade.

Uma pasta sozinha esgota: 60 videos com 3 posts por dia duram 20 dias e o robo
para. Aqui as pastas viram uma fila unica - consome a primeira ate o fim, depois
a segunda, e assim por diante. As pastas podem estar ate em contas diferentes.
"""


class FonteComposta:
    label = "varias pastas"

    def __init__(self, fontes):
        self.fontes = [f for f in fontes if f is not None]
        self._por_item = {}

    def list_videos(self):
        """Concatena mantendo a ordem das pastas: a fila anda sozinha."""
        todos = []
        for indice, fonte in enumerate(self.fontes):
            try:
                videos = fonte.list_videos()
            except Exception as e:
                print(f"    ! pasta {indice + 1} indisponivel ({e}) - seguindo para a proxima")
                continue
            for item in videos:
                self._por_item[item.id] = fonte
            todos.extend(videos)
        return todos

    def captions(self):
        juntas = {}
        for fonte in self.fontes:
            try:
                juntas.update(fonte.captions())
            except Exception:
                pass
        return juntas

    def download(self, item):
        fonte = self._por_item.get(item.id)
        if fonte is None:
            # cache vazio (ex: processo reiniciado): tenta descobrir de novo
            self.list_videos()
            fonte = self._por_item.get(item.id)
        if fonte is None:
            raise RuntimeError(f"nao sei de qual pasta veio '{item.name}'")
        return fonte.download(item)
