"""
Umbra PDF
=========
Aplicativo desktop local para refinar PDFs escaneados em lote, com visualização
antes/depois, navegação por páginas, zoom, perfis de tratamento e saída segura.

Dependências:
    pip install pillow PyMuPDF

Destaques:
- identidade própria e ícone embutido; no Windows também aplica AppUserModelID,
  ICO multi-resolução e WM_SETICON para título, Alt+Tab e taskbar;
- barra lateral compacta com SVGs consistentes;
- interface dark de alto contraste com botões, sliders, toggles e seletores
  personalizados, evitando a aparência padrão do Tkinter;
- visualizador rolável com Original / Resultado / Comparar, páginas, zoom,
  ajuste à página/largura e divisor de comparação interativo;
- origem e destino configuráveis, varredura opcional em subpastas e estados por PDF;
- cancelamento seguro e gravação atômica em .part.pdf antes da saída final;
- processamento e prévia em threads, com todas as atualizações Tcl/Tk passando
  por uma fila segura na thread principal.
"""

from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageOps, ImageTk
except ImportError:
    Image = None
    ImageTk = None


APP_NOME = "Umbra PDF"
APP_VERSAO = "1.0.0"
__version__ = APP_VERSAO
APP_SUBTITULO = "Refine scans. Preserve legibility."
APP_ID_WINDOWS = "Kauan.UmbraPDF.Desktop"
PASTA_SAIDA_NOME = "Umbra - Resultados"
FONTE_UI = "Segoe UI"
FONTE_MONO = "Consolas"
MAX_ITENS_LISTA = 1500
MAX_LINHAS_LOG = 1400
CONFIG_VERSION = 2


def caminho_preferencias() -> Path:
    """Retorna um local persistente e apropriado ao sistema operacional."""
    if sys.platform.startswith("win"):
        base = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / "Umbra PDF" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Umbra PDF" / "settings.json"
    base = Path(os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "umbra-pdf" / "settings.json"


def carregar_preferencias() -> dict:
    caminho = caminho_preferencias()
    try:
        if caminho.is_file():
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                return dados
    except (OSError, ValueError, TypeError):
        pass
    return {}


def salvar_preferencias(dados: dict) -> None:
    """Grava de forma atômica para não corromper preferências se o app fechar."""
    caminho = caminho_preferencias()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporario, caminho)

# Paleta: preto suave + superfícies translúcidas simuladas por camadas.
COR_FUNDO = "#080A0D"
COR_RAIL = "#060709"
COR_SUPERFICIE = "#101216"
COR_SUPERFICIE_2 = "#15181D"
COR_SUPERFICIE_HOVER = "#1C2026"
COR_BORDA = "#30353D"
COR_BORDA_SUAVE = "#20242A"
COR_TEXTO = "#F7F8FA"
COR_TEXTO_2 = "#C2C7D0"
COR_TEXTO_3 = "#8D95A1"
COR_ACENTO = "#AAB8FF"
COR_ACENTO_HOVER = "#C0CAFF"
COR_ACENTO_SUAVE = "#20263A"
COR_SUCESSO = "#7BDDA5"
COR_ALERTA = "#F2C879"
COR_ERRO = "#FF8585"
COR_PROGRESSO_FUNDO = "#1B2027"


PRESETS = {
    "Equilibrado": {
        "dpi": 230,
        "cutoff": 1.5,
        "brilho": 0.92,
        "contraste": 1.50,
        "nitidez": 1.30,
        "qualidade": 86,
    },
    "Texto forte": {
        "dpi": 250,
        "cutoff": 2.0,
        "brilho": 0.84,
        "contraste": 1.80,
        "nitidez": 1.45,
        "qualidade": 88,
    },
    "Scan apagado": {
        "dpi": 280,
        "cutoff": 1.0,
        "brilho": 0.78,
        "contraste": 2.05,
        "nitidez": 1.55,
        "qualidade": 90,
    },
    "Leve": {
        "dpi": 200,
        "cutoff": 1.0,
        "brilho": 0.98,
        "contraste": 1.25,
        "nitidez": 1.15,
        "qualidade": 84,
    },
}

# Ícones vetoriais próprios, mantidos em SVG para preservar nitidez em qualquer
# escala. Eles são rasterizados pelo próprio PyMuPDF, que já é dependência do app.
# Assim evitamos fontes de ícones e arquivos externos soltos ao lado do .py.
SVG_ICONES = {
    "settings": '<path d="M4.5 7.2h15M7.7 4.8v4.8M4.5 12h15M15.8 9.6v4.8M4.5 16.8h15M10.5 14.4v4.8"/>',
    "folder": '<path d="M3.8 7.2a2 2 0 0 1 2-2h4.1l2 2.4h6.3a2 2 0 0 1 2 2v7.2a2 2 0 0 1-2 2H5.8a2 2 0 0 1-2-2Z"/>',
    "folder_open": '<path d="M3.8 8.2V7.3a2 2 0 0 1 2-2h4.1l2 2.4h6.3a2 2 0 0 1 2 2v1.1"/><path d="M5.1 18.7h12.8a1.8 1.8 0 0 0 1.7-1.2l1.5-4.5a1.4 1.4 0 0 0-1.3-1.9H6.2a1.8 1.8 0 0 0-1.7 1.2l-1.4 4.3a1.6 1.6 0 0 0 2 2.1Z"/>',
    "play": '<path d="M8.2 5.3v13.4L18.9 12Z"/>',
    "refresh": '<path d="M19.3 8.2V4.6l-2.1 2.1a7.6 7.6 0 1 0 1.6 8.2"/><path d="M19.2 4.6h-3.7"/>',
    "eye": '<path d="M2.8 12s3.4-5.2 9.2-5.2S21.2 12 21.2 12 17.8 17.2 12 17.2 2.8 12 2.8 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    "compare": '<rect x="4.2" y="4.2" width="15.6" height="15.6" rx="2.4"/><path d="M12 4.2v15.6"/><path d="M7.2 9.2h1.9M7.2 12h1.9M14.9 12h1.9M14.9 14.8h1.9"/>',
    "file": '<path d="M6.2 3.7h7.2l4.4 4.4v12.2H6.2Z"/><path d="M13.4 3.7v4.5h4.4M8.9 13h6.2M8.9 16h4.7"/>',
    "check": '<path d="m5.2 12.4 4.1 4.1 9.5-9.3"/>',
    "x": '<path d="m6.2 6.2 11.6 11.6M17.8 6.2 6.2 17.8"/>',
    "info": '<circle cx="12" cy="12" r="8.2"/><path d="M12 10.8v5.1"/><path d="M12 7.8h.01"/>',
    "chevron_left": '<path d="m14.8 6.5-5.5 5.5 5.5 5.5"/>',
    "chevron_right": '<path d="m9.2 6.5 5.5 5.5-5.5 5.5"/>',
    "minus": '<path d="M6.5 12h11"/>',
    "plus": '<path d="M12 6.5v11M6.5 12h11"/>',
    "fit_page": '<rect x="6.5" y="4" width="11" height="16" rx="1.6"/><path d="M4.5 8V4.5H8M19.5 8V4.5H16M4.5 16v3.5H8M19.5 16v3.5H16"/>',
    "fit_width": '<rect x="4" y="6.5" width="16" height="11" rx="1.6"/><path d="m8.2 12-2.4 0M5.8 12l2-2M5.8 12l2 2M15.8 12h2.4M18.2 12l-2-2M18.2 12l-2 2"/>',
    "copy": '<rect x="8" y="8" width="10.5" height="11" rx="1.8"/><path d="M15.8 8V5.5A1.5 1.5 0 0 0 14.3 4H5.5A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>',
}

APP_ICON_SVG = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="3" y="3" width="58" height="58" rx="15" fill="#0A0C10"/>
  <rect x="4.5" y="4.5" width="55" height="55" rx="13.5" fill="none" stroke="#343A46" stroke-width="2"/>
  <path d="M18 12h21l9 9v31H18z" fill="#F5F7FB"/>
  <path d="M39 12v10h9" fill="#C6CEFF"/>
  <path d="M33 22h15v30H33z" fill="#98A9FF" opacity=".94"/>
  <path d="M24 31h18M24 38h18M24 45h12" fill="none" stroke="#11141A" stroke-width="3" stroke-linecap="round"/>
  <path d="M33 27v20" fill="none" stroke="#F5F7FB" stroke-width="2" opacity=".8"/>
</svg>'''
APP_ICON_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAKo0lEQVR42u1ba2wc1RX+zr2z75192DjvOE5JgJZCUwrhB/xAlSqqJCAa6qLSh1rUQJEIVUEVNEAWh4AqKlqBUNX+6Y+qFSqhBTWhQlVVSEWRSpQ0oMpVk0Bc54mdXe/szuzO7NxHf8za2cS7iddexw7kSkeW7dHce84953znnDmHMPNFmNul52JTAsCRyzEiwlwScjkGgE/3ImgazzMiklpPCD4EIDoHmqABuAB8ACAiaK05ANWOVrRzaEZEqs54IhpNbEhmum+NRqI3MsNYQprYBeWetJJCHPO86rt2sfCG6zq7AFTqgmB1QXRMAByABBBOpLru6+petDmd6VodT5jghgHG2JwYv5IKUvqo2DYs69TBQn7kBadU+FVdK8bPPFMB9HNghwRw49Le1S92L1hyfTxhAlqpaqWiHKfE/JpHDSZxYZwQEULhiE4kUioWjzMixhy7hFOjx/ccHz60GcA/G84+LQEQkCNgQCVT2fsXLel7rrtncQwEWbbGKD96ktllC1IKaK0uvC8mgIiBcwNJM43unkXKTGc1NPip0RPV40eHHqraY78EcgwY0K38ArV8fX8/w44dMp3teWrZitWPp9JdcN2qHDkxzAuFESipwDkDUPfGc4F/OuBL1s+S7V6AhYt6ZSQa4yWrgKOHDz5lWaNb0d/PsWNHU+fImyp9fz8fDJjf1rvyqifMVFba5SINDx1gVjEPxjg455gfiybO4tglOHaJRWNxbaayKpYwb6l5Lty9e95Efz/H4OBUBJBjg4O/UMlU9vu9K6981kxlpVUssOHD/yXPdWEYRkub7DjGt7k456h5LsqlIkWicUqlsyociX2x6tgna/v37gl8wplCOHsXTkSS8+j1K1Zf9faCBUtD5XKRhj74D0nfB3EOtHB2Ukp02hEaRghEaO+9RFBSIhQKo+/yT+ukmdYjHx3zhz/4901CiL31WEE20wDK5XJ46623IouW9L26eGnf8prn6uHDB5jvVcG40ZJ5IoJpmojFYp2haBSxWAzVqgOA2oZZxhiE8FF1bDJTWW2mMiHhy+vLpcJvcrmc3L17dzMNCCAjYXY9ePmV1zwfjyfk8NBBnh89CcMwmt4CEcH3fWQyGbzzzjvIZDLwfX/mTlFrhCIhvPDiS9j+5AOIRBMgRtBKtwWTQvjo7lmM3r7VslKx+QcH3t/slIovNsKjcfr5V6TWSGa7F/wwkTC1VczTWH4EnPPzqiARIZ1OI5s14fu6A6igIQRw19fvhed5ePaZhxCLmePh7pQRgnMDxfwIMtkeSme6dLZr4UNOqfhrolcqWoMA6HEBcK21iEYTGzLZy/qUUio/eoIppcCN1qrfuIQQ8H3dEQ0gAoQEihbD3d/aDCVr+OlPHkE8kWpLCEQEISXyo8eZmcqodOaylaeiRze4rvNy3fxFYFy5nAKAZDqzIZZI6mq1ouyyFcBLG5t1mhhjKFoS377nYfzoke1wbGtir6lrAYddtlCtVlQ8aeqkmb2tjnYKABgAom3bFAAjEkmsMbhBFafEpJTBVcwpwhM4MYwVJb6z6VE8umU7HLvUXvBFBCklKk6JGdygcCy2BoBBtE0BOCODi/GQsZQxjiC2V3Ne6RhngDOGfF7iu5t+jMce31bXhKkJgQBoreDXPGKMwzCMJfX0HeMacHorTQzjuKsxj1ZgDh+NStxz7xY8sXUbnPLUhQBd54kAAjMa+TZwkSyqa8KxEwr33LcFjAEDua2IJ82ZBVvzRMsn/T5B4//XADECEXDkmMKm+7eASOPp7c8gHIkGGek0FpsPAvB9oNaEpASkOvOnUgQCMHRE4867HkZXdxd8vzZt6DXm+uZrPvDnv3P4/mRNkC0iP60Bzgh22YMvCDMpSBnzSQOaXiJNzuK1Dv6uOwDT80IArMHmp1q3og6VoeeFD1BzCLnzQgDGHOrhrG49lSKJwTluvFZg9x5AiNZmEOQG/OISgJmInPeZmgCiUSCVDmBuks3rQCi+D3iuvngEwBjDztf/gn379k0uqBBBKYVIOIyNGzei4gJ/evlVuF4tqP7os0tcAr0rP4+r13ypraLInAhASgkzGcWrr72Ou7/xTQghmufpvkDSTOKGG24AEfD6H59GuVyGYYQmmc14erzpwd9h7c0b4NiiXpKfx05Qaw2lFKhDOaXWGhoXgQlwzlF1BdavX4eXf/8S3nvv/ZYmEA6HsXz5clRcYP3Gx+C6NTDe3ASWrbgW11z3ZbhV3VFnOGs+QCmFO25fhztuX3deJzhSAG7/2g/O6QSFD7gXkxMEgGKpgonKkp5UpQARIRwOQwigWJAQQjeBwSAWZoyDG+GLSwCZVHxKMGgYQKbrEwiD4XAYdzbC4Dl8wMcWBtdegsFLMHgJBi/BoACKYxLC12CMgZrc8EWZDbYFg9kABoWYHbib/zC44zVUnAr6Vn0BV3+u83A3/2HwD9th2w5CoRC+t/m3WHvzBlQcMStqP+9g8HT4q2cN7qaiAVqTVoHXpWmXXNuBwUgdBssOsP7Ox1FxKlixcg0+22m4ozpPGtBQAg1ttI0CqEpfHFNKZkLhiCZiNJN7mCoMVjxg55vAuq88CMY6H/NrBA2VoXBEKyVJCHEcQZP1hAlovXUrAyA8z9kvpNDxREq10xzRapUdDyXbbUllx0Wt5sP1FEqWD6voo1oRnbZFcM4RT6SUkELXqtX9AITWWxkAHfiAgQEGALZV3FV1yhSLxVnSTKOdJgmt9SRijIFzfk4Cgg8jjHEwxkHEmr6rFZ3btwTNEUkzjVgszip2mezy2M7gvwHP4yYgiQiu6+wqjuWHzFR2RXfPYlWyxthUtcAwDIRCBCA05Q+V4/ER4wDnU29I0Tp4nnPjvJfCGUN3zxLFGCOreOqw6zq76n1GZ3SJaa2/yoEd9lh+5Oddly18PpXOqmz3ApyrTa5xI8uyJtrm2hGAL4CKzVt/G2zFGGeoVspo1cnR2CaXSme045TYWOGjnwGo1HmVZ0fdlMvlaGBgILxk2ap/LP/UFdf5nqcOHxpkbtUG462FQERIJBLT+kStddARNl2o9VxnkhAC1ReIxZJYueozKhSOsCOHD+w7fvTQTblcrjYwcLp7vHWr7Kqr3l6wcGmoXCrS0Iez2yrLpv2ls0l+MINW2Tpq5JhSfz3m17xTsXjytlQ6q6LRBNnlIklfBOlqC/yfLo07wPaJTbp5JQRC4QiW912hU+mssooFfvx/hx5wXWdnvVn6DH1rEmns1v39/Xz/v/buqXkuj8XNW1LprIonklSt2uR51SBjo3nRQzbBeKCFAvGEid6VAfN22eLHhg8+WbLyzwXt8pOnR5qGWoODg0B/P/f27vmb51aNSDR+i5nKUjKVlVopVq06kFJO3MCcjczVlTY4C6G7ZxGW9a6S8USKlawCO/Lhgaes4uiTDQMTzYLEcwWQzUdmStYYFUZP1EdmJLRSc3PzbHxkJoXunsUdHZlpWOcbmrKYX6t9LIemzjaV02NzXYs2p7Ndq+OJJLgRAiM2B2OTGkppSOnDscsoWfnZGptrQKtJg5Ndt0YjsbWM88X1DswLxz+UL6U86XnVd61i4Q1/lgcnG59vNjobwYVvt1EAPMxwdHYGGfYnc3h6tt4x05R/2uv/XcRPrLuWJ/4AAAAASUVORK5CYII="
)



def _svg_documento(cor: str, corpo: str, preenchido: bool = False) -> str:
    largura = 2.05 if preenchido else 1.75
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g fill="none" stroke="{cor}" stroke-width="{largura}" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f'{corpo}</g></svg>'
    )


def renderizar_svg_pil(svg: str, tamanho: int):
    if fitz is None or Image is None:
        return None
    try:
        doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
        pagina = doc.load_page(0)
        escala = max(tamanho / max(pagina.rect.width, 1), tamanho / max(pagina.rect.height, 1)) * 2.0
        pix = pagina.get_pixmap(matrix=fitz.Matrix(escala, escala), alpha=True)
        modo = "RGBA" if pix.n == 4 else "RGB"
        img = Image.frombytes(modo, (pix.width, pix.height), pix.samples)
        doc.close()
        if img.size != (tamanho, tamanho):
            img = img.resize((tamanho, tamanho), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


def renderizar_icone_pil(nome: str, tamanho: int, cor: str, preenchido: bool = False):
    corpo = SVG_ICONES.get(nome)
    if not corpo:
        return None
    return renderizar_svg_pil(_svg_documento(cor, corpo, preenchido), tamanho)




def preparar_identidade_windows() -> None:
    """Define a identidade do processo antes da criação de qualquer janela Tk.

    No Windows, fazer isso depois de criar a janela pode deixar o botão da
    taskbar associado ao executável python.exe ou sem o ícone esperado.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID_WINDOWS)
    except Exception:
        pass


class ProcessamentoCancelado(Exception):
    """Interrupção controlada solicitada pelo usuário."""


@dataclass(frozen=True)
class ConfigProcessamento:
    origem: Path
    saida: Path
    dpi: int
    cutoff: float
    brilho: float
    contraste: float
    nitidez: float
    qualidade: int
    recursivo: bool
    sobrescrever: bool


def formatar_tamanho(bytes_: int) -> str:
    unidades = ("B", "KB", "MB", "GB")
    valor = float(max(bytes_, 0))
    for unidade in unidades:
        if valor < 1024 or unidade == unidades[-1]:
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{bytes_} B"


def abrir_no_gerenciador(caminho: Path) -> None:
    caminho = caminho.resolve()
    if not caminho.exists():
        raise FileNotFoundError(str(caminho))

    if sys.platform.startswith("win"):
        os.startfile(str(caminho))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(caminho)])
    else:
        subprocess.Popen(["xdg-open", str(caminho)])


def _imagem_do_pixmap(pix) -> Image.Image:
    """Converte Pixmap em Pillow diretamente, sem PNG intermediário."""
    if pix.n == 1:
        return Image.frombytes("L", (pix.width, pix.height), pix.samples).convert("RGB")
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def aplicar_filtros_imagem(img: Image.Image, config: ConfigProcessamento) -> Image.Image:
    """Aplica o mesmo pipeline visual usado tanto na prévia quanto no PDF final."""
    img = ImageOps.autocontrast(img, cutoff=config.cutoff)
    if config.brilho != 1.0:
        img = ImageEnhance.Brightness(img).enhance(config.brilho)
    if config.contraste != 1.0:
        img = ImageEnhance.Contrast(img).enhance(config.contraste)
    if config.nitidez != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(config.nitidez)
    return img


def processar_pdf(
    caminho_entrada: Path,
    caminho_saida: Path,
    config: ConfigProcessamento,
    cancelar: threading.Event,
    log_callback: Callable[[str], None],
    pagina_callback: Callable[[int, int], None],
) -> None:
    """Rasteriza e melhora um PDF, salvando de forma atômica.

    O arquivo só assume o nome final quando todas as páginas terminam. Assim,
    queda, erro ou cancelamento não deixam um PDF final parcialmente gravado.
    """
    if fitz is None or Image is None:
        raise RuntimeError("PyMuPDF e Pillow precisam estar instalados.")

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho_saida.with_name(f"{caminho_saida.stem}.part.pdf")

    if temporario.exists():
        temporario.unlink(missing_ok=True)

    doc = None
    novo_doc = None

    try:
        doc = fitz.open(str(caminho_entrada))
        if getattr(doc, "needs_pass", False):
            raise RuntimeError("PDF protegido por senha.")
        if doc.page_count == 0:
            raise RuntimeError("PDF sem páginas.")

        novo_doc = fitz.open()

        # Preserva metadados básicos quando disponíveis.
        try:
            metadata = dict(doc.metadata or {})
            metadata = {k: v for k, v in metadata.items() if isinstance(v, str)}
            if metadata:
                novo_doc.set_metadata(metadata)
        except Exception:
            pass

        total_paginas = doc.page_count
        for indice in range(total_paginas):
            if cancelar.is_set():
                raise ProcessamentoCancelado()

            pagina = doc.load_page(indice)
            pix = pagina.get_pixmap(dpi=config.dpi, colorspace=fitz.csRGB, alpha=False)
            img = _imagem_do_pixmap(pix)

            img = aplicar_filtros_imagem(img, config)

            buffer = io.BytesIO()
            img.save(
                buffer,
                format="JPEG",
                quality=config.qualidade,
                optimize=True,
            )
            dados_jpeg = buffer.getvalue()
            buffer.close()
            img.close()

            nova_pagina = novo_doc.new_page(width=pagina.rect.width, height=pagina.rect.height)
            nova_pagina.insert_image(nova_pagina.rect, stream=dados_jpeg)

            pagina_callback(indice + 1, total_paginas)

        if cancelar.is_set():
            raise ProcessamentoCancelado()

        novo_doc.save(str(temporario), deflate=True, garbage=3)
        novo_doc.close()
        novo_doc = None
        doc.close()
        doc = None

        os.replace(temporario, caminho_saida)
        log_callback(f"    salvo em {caminho_saida.name}")

    except Exception:
        try:
            if novo_doc is not None:
                novo_doc.close()
        except Exception:
            pass
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass
        temporario.unlink(missing_ok=True)
        raise


class Tooltip:
    def __init__(self, widget: tk.Widget, texto: str):
        self.widget = widget
        self.texto = texto
        self.janela: tk.Toplevel | None = None
        self._after_id = None
        widget.bind("<Enter>", self._agendar, add="+")
        widget.bind("<Leave>", self._esconder, add="+")
        widget.bind("<ButtonPress>", self._esconder, add="+")

    def _agendar(self, _evento=None):
        self._cancelar_agendamento()
        self._after_id = self.widget.after(450, self._mostrar)

    def _cancelar_agendamento(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _mostrar(self):
        if self.janela or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 10
        y = self.widget.winfo_rooty() + max(0, (self.widget.winfo_height() - 28) // 2)
        self.janela = tk.Toplevel(self.widget)
        self.janela.overrideredirect(True)
        self.janela.geometry(f"+{x}+{y}")
        label = tk.Label(
            self.janela,
            text=self.texto,
            bg="#1A1E24",
            fg=COR_TEXTO,
            font=(FONTE_UI, 9),
            padx=9,
            pady=5,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
        )
        label.pack()

    def _esconder(self, _evento=None):
        self._cancelar_agendamento()
        if self.janela:
            try:
                self.janela.destroy()
            except tk.TclError:
                pass
            self.janela = None


class NavIconButton(tk.Canvas):
    """Botão de navegação compacto com SVG rasterizado e foco acessível."""

    def __init__(self, master, icon: str, tooltip: str, command: Callable[[], None]):
        super().__init__(
            master,
            width=48,
            height=48,
            bg=COR_RAIL,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.icon = icon
        self.command = command
        self.ativo = False
        self.hover = False
        self.focused = False
        self._imgs = {}
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Button-1>", lambda _e: self._ativar())
        self.bind("<Return>", lambda _e: self._ativar())
        self.bind("<space>", lambda _e: self._ativar())
        Tooltip(self, tooltip)
        self._redesenhar()

    @staticmethod
    def _rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, raio, **kwargs):
        pontos = [
            x1 + raio, y1, x2 - raio, y1, x2, y1, x2, y1 + raio,
            x2, y2 - raio, x2, y2, x2 - raio, y2, x1 + raio, y2,
            x1, y2, x1, y2 - raio, x1, y1 + raio, x1, y1,
        ]
        return canvas.create_polygon(pontos, smooth=True, splinesteps=24, **kwargs)

    def _ativar(self):
        self.focus_set()
        self.command()

    def set_ativo(self, ativo: bool):
        self.ativo = ativo
        self._redesenhar()

    def _enter(self, _e=None):
        self.hover = True
        self._redesenhar()

    def _leave(self, _e=None):
        self.hover = False
        self._redesenhar()

    def _focus_in(self, _e=None):
        self.focused = True
        self._redesenhar()

    def _focus_out(self, _e=None):
        self.focused = False
        self._redesenhar()

    def _photo(self, cor: str, preenchido: bool):
        if ImageTk is None:
            return None
        chave = (cor, preenchido)
        if chave not in self._imgs:
            img = renderizar_icone_pil(self.icon, 22, cor, preenchido)
            self._imgs[chave] = ImageTk.PhotoImage(img) if img is not None else None
        return self._imgs[chave]

    def _redesenhar(self):
        self.delete("all")
        if self.ativo:
            fundo = COR_ACENTO_SUAVE
        elif self.hover or self.focused:
            fundo = COR_SUPERFICIE_HOVER
        else:
            fundo = COR_RAIL

        if self.ativo or self.hover or self.focused:
            borda = COR_ACENTO if self.focused else COR_BORDA
            self._rounded_rect(self, 4, 4, 44, 44, 11, fill=fundo, outline=borda)
        if self.ativo:
            self._rounded_rect(self, 0, 14, 3, 34, 1.5, fill=COR_ACENTO, outline="")

        cor = COR_TEXTO if (self.hover or self.ativo or self.focused) else COR_TEXTO_2
        photo = self._photo(cor, self.ativo)
        if photo is not None:
            self.create_image(24, 24, image=photo)
        else:
            self._desenhar_fallback(cor)

    def _desenhar_fallback(self, cor: str):
        # Fallback mínimo caso PyMuPDF/Pillow estejam ausentes na inicialização.
        if self.icon == "play":
            self.create_polygon(19, 15, 34, 24, 19, 33, fill="", outline=cor, width=2)
        elif self.icon.startswith("folder"):
            self.create_rectangle(14, 19, 35, 33, outline=cor, width=2)
        else:
            self.create_oval(17, 17, 31, 31, outline=cor, width=2)


class ModernButton(tk.Canvas):
    """Botão desenhado no Canvas para evitar a aparência nativa antiga do Tk."""

    def __init__(self, master, text: str, command: Callable[[], None], *,
                 primary: bool = False, compact: bool = False,
                 icon: str | None = None, danger: bool = False,
                 width: int | None = None, selected: bool = False):
        self._parent_bg = master.cget("bg") if "bg" in master.keys() else COR_SUPERFICIE
        self._font = tkfont.Font(family=FONTE_UI, size=9,
                                 weight="bold" if primary or selected else "normal")
        self._compact = compact
        self._height = 32 if compact else 38
        self._pad_x = 9 if compact else 14
        self._explicit_width = width
        self._text = text
        self._command = command
        self._primary = primary
        self._danger = danger
        self._icon = icon
        self._state = "normal"
        self._selected = selected
        self._hover = False
        self._focused = False
        self._pressed = False
        self._photo = None
        self._resize_width = 100
        super().__init__(
            master, height=self._height, width=width or 100,
            bg=self._parent_bg, bd=0, highlightthickness=0,
            takefocus=True, cursor="hand2"
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda _e: self.invoke())
        self.bind("<space>", lambda _e: self.invoke())
        self._recalc_width()
        self._draw()

    @staticmethod
    def _rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, raio, **kwargs):
        pontos = [
            x1 + raio, y1, x2 - raio, y1, x2, y1, x2, y1 + raio,
            x2, y2 - raio, x2, y2, x2 - raio, y2, x1 + raio, y2,
            x1, y2, x1, y2 - raio, x1, y1 + raio, x1, y1,
        ]
        return canvas.create_polygon(pontos, smooth=True, splinesteps=28, **kwargs)

    def _recalc_width(self):
        if self._explicit_width:
            largura = self._explicit_width
        else:
            largura = self._font.measure(self._text) + self._pad_x * 2
            if self._icon:
                largura += 22
            largura = max(42 if self._compact else 76, largura)
        self._resize_width = int(largura)
        super().configure(width=self._resize_width)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "text" in kwargs:
            self._text = str(kwargs.pop("text"))
            self._recalc_width()
        if "state" in kwargs:
            self._state = str(kwargs.pop("state"))
            super().configure(cursor="arrow" if self._state == "disabled" else "hand2")
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if kwargs:
            super().configure(**kwargs)
        self._draw()

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return super().cget(key)

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self._font.configure(weight="bold" if self._primary or self._selected else "normal")
        self._draw()

    def invoke(self):
        if self._state == "disabled":
            return "break"
        self.focus_set()
        if self._command:
            self._command()
        return "break"

    def _on_enter(self, _e=None):
        if self._state != "disabled":
            self._hover = True
            self._draw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_focus_in(self, _e=None):
        self._focused = True
        self._draw()

    def _on_focus_out(self, _e=None):
        self._focused = False
        self._pressed = False
        self._draw()

    def _on_press(self, _e=None):
        if self._state != "disabled":
            self._pressed = True
            self._draw()

    def _on_release(self, evento=None):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if self._state != "disabled" and was_pressed:
            if evento is None or (0 <= evento.x <= self.winfo_width() and 0 <= evento.y <= self.winfo_height()):
                self.invoke()

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w = max(self._resize_width, self.winfo_width())
        h = self._height
        disabled = self._state == "disabled"

        if self._primary:
            base = "#EEF1FF"
            hover = "#FFFFFF"
            pressed = "#D9DFFF"
            fg = "#0A0C10"
        elif self._danger:
            base = "#261719"
            hover = "#331D20"
            pressed = "#3B2024"
            fg = COR_ERRO
        elif self._selected:
            base = COR_ACENTO_SUAVE
            hover = "#29314A"
            pressed = "#303A58"
            fg = COR_TEXTO
        else:
            base = COR_SUPERFICIE_2
            hover = COR_SUPERFICIE_HOVER
            pressed = "#22272F"
            fg = COR_TEXTO_2

        if disabled:
            fill = "#13161B"
            fg = "#666E7A"
            outline = COR_BORDA_SUAVE
        else:
            fill = pressed if self._pressed else (hover if self._hover else base)
            outline = COR_ACENTO if self._focused else ("#566078" if self._selected else COR_BORDA)

        self._rounded_rect(self, 1.5, 1.5, w - 1.5, h - 1.5, 9,
                           fill=fill, outline=outline, width=2 if self._focused else 1)

        icon_w = 0
        if self._icon and ImageTk is not None:
            color = fg
            pil = renderizar_icone_pil(self._icon, 16, color, self._primary or self._selected)
            if pil is not None:
                self._photo = ImageTk.PhotoImage(pil)
                icon_w = 19

        text_w = self._font.measure(self._text)
        group_w = text_w + icon_w
        start_x = (w - group_w) / 2
        if self._photo is not None and self._icon:
            self.create_image(start_x + 8, h / 2, image=self._photo)
            text_x = start_x + icon_w
        else:
            text_x = (w - text_w) / 2
        self.create_text(text_x, h / 2, text=self._text, fill=fg,
                         anchor="w", font=self._font)


class SegmentedControl(tk.Frame):
    """Seletor compacto para poucas opções mutuamente exclusivas."""

    def __init__(self, master, options: list[str], variable: tk.StringVar,
                 command: Callable[[str], None] | None = None, compact: bool = True):
        super().__init__(master, bg=COR_SUPERFICIE_2,
                         highlightbackground=COR_BORDA, highlightthickness=1, bd=0)
        self.variable = variable
        self.command = command
        self.buttons: dict[str, ModernButton] = {}
        for i, option in enumerate(options):
            btn = ModernButton(
                self, option, lambda value=option: self._select(value),
                compact=compact, selected=(variable.get() == option)
            )
            btn.pack(side="left", padx=(2 if i == 0 else 1, 2 if i == len(options)-1 else 1), pady=2)
            self.buttons[option] = btn
        self.variable.trace_add("write", lambda *_: self.refresh())

    def _select(self, value: str):
        if self.variable.get() != value:
            self.variable.set(value)
        self.refresh()
        if self.command:
            self.command(value)

    def refresh(self):
        atual = self.variable.get()
        for option, btn in self.buttons.items():
            btn.set_selected(option == atual)



class ModernSlider(tk.Canvas):
    """Slider minimalista desenhado no Canvas, com mouse e teclado."""

    def __init__(self, master, variable, minimo: float, maximo: float, resolucao: float,
                 on_change: Callable[[], None] | None = None):
        super().__init__(master, height=26, bg=COR_SUPERFICIE, bd=0,
                         highlightthickness=0, takefocus=True, cursor="hand2")
        self.variable = variable
        self.minimo = float(minimo)
        self.maximo = float(maximo)
        self.resolucao = float(resolucao)
        self.on_change = on_change
        self.hover = False
        self.focused = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._pointer)
        self.bind("<B1-Motion>", self._pointer)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Left>", lambda _e: self._step(-1))
        self.bind("<Right>", lambda _e: self._step(1))
        self.bind("<Down>", lambda _e: self._step(-1))
        self.bind("<Up>", lambda _e: self._step(1))
        self.variable.trace_add("write", lambda *_: self._draw())
        self.after_idle(self._draw)

    def _normalizar(self, valor: float) -> float:
        valor = max(self.minimo, min(self.maximo, valor))
        if self.resolucao > 0:
            valor = round(valor / self.resolucao) * self.resolucao
        return max(self.minimo, min(self.maximo, valor))

    def _pointer(self, evento):
        self.focus_set()
        margem = 8
        largura = max(1, self.winfo_width() - margem * 2)
        fracao = max(0.0, min(1.0, (evento.x - margem) / largura))
        valor = self.minimo + fracao * (self.maximo - self.minimo)
        valor = self._normalizar(valor)
        if isinstance(self.variable, tk.IntVar):
            self.variable.set(int(round(valor)))
        else:
            self.variable.set(round(valor, 4))
        if self.on_change:
            self.on_change()

    def _step(self, direcao: int):
        valor = self._normalizar(float(self.variable.get()) + self.resolucao * direcao)
        if isinstance(self.variable, tk.IntVar):
            self.variable.set(int(round(valor)))
        else:
            self.variable.set(round(valor, 4))
        if self.on_change:
            self.on_change()
        return "break"

    def _enter(self, _e=None):
        self.hover = True; self._draw()

    def _leave(self, _e=None):
        self.hover = False; self._draw()

    def _focus_in(self, _e=None):
        self.focused = True; self._draw()

    def _focus_out(self, _e=None):
        self.focused = False; self._draw()

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w = max(20, self.winfo_width())
        y = 13
        x1, x2 = 8, w - 8
        try:
            valor = float(self.variable.get())
        except Exception:
            valor = self.minimo
        fracao = (valor - self.minimo) / max(self.maximo - self.minimo, 1e-9)
        fracao = max(0.0, min(1.0, fracao))
        x = x1 + (x2 - x1) * fracao
        self.create_line(x1, y, x2, y, fill="#2B3038", width=4, capstyle=tk.ROUND)
        self.create_line(x1, y, x, y, fill=COR_ACENTO, width=4, capstyle=tk.ROUND)
        if self.focused:
            self.create_oval(x - 8, y - 8, x + 8, y + 8, outline=COR_ACENTO, width=1)
        raio = 5.5 if (self.hover or self.focused) else 5
        self.create_oval(x - raio, y - raio, x + raio, y + raio,
                         fill=COR_TEXTO, outline="#0B0D10", width=1)


class ModernCheckbutton(tk.Frame):
    """Toggle switch compacto, com estado legível por mouse e teclado."""

    def __init__(self, master, text: str, variable: tk.BooleanVar,
                 command: Callable[[], None] | None = None):
        super().__init__(master, bg=COR_SUPERFICIE, takefocus=True, cursor="hand2")
        self.variable = variable
        self.command = command
        self.focused = False
        self.hover = False
        self.box = tk.Canvas(self, width=38, height=22, bg=COR_SUPERFICIE,
                             highlightthickness=0, bd=0, cursor="hand2")
        self.box.pack(side="left")
        self.label = tk.Label(self, text=text, bg=COR_SUPERFICIE, fg=COR_TEXTO_2,
                              font=(FONTE_UI, 9), cursor="hand2")
        self.label.pack(side="left", padx=(8, 0))
        for widget in (self, self.box, self.label):
            widget.bind("<Button-1>", self._toggle, add="+")
            widget.bind("<Enter>", self._enter, add="+")
            widget.bind("<Leave>", self._leave, add="+")
        self.bind("<Return>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
        pts = [x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1]
        return canvas.create_polygon(pts, smooth=True, splinesteps=24, **kwargs)

    def _toggle(self, _e=None):
        self.focus_set()
        self.variable.set(not bool(self.variable.get()))
        if self.command:
            self.command()
        return "break"

    def _enter(self, _e=None):
        self.hover = True; self._draw()

    def _leave(self, _e=None):
        self.hover = False; self._draw()

    def _focus_in(self, _e=None):
        self.focused = True; self._draw()

    def _focus_out(self, _e=None):
        self.focused = False; self._draw()

    def _draw(self):
        self.box.delete("all")
        checked = bool(self.variable.get())
        track = COR_ACENTO if checked else ("#303641" if self.hover else COR_SUPERFICIE_2)
        outline = COR_ACENTO_HOVER if self.focused else (COR_ACENTO if checked else COR_BORDA)
        self._round_rect(self.box, 2, 3, 36, 19, 8, fill=track, outline=outline,
                         width=2 if self.focused else 1)
        cx = 27 if checked else 11
        knob = "#0A0C10" if checked else COR_TEXTO_2
        self.box.create_oval(cx-6, 5, cx+6, 17, fill=knob, outline="")
        self.label.configure(fg=COR_TEXTO if (checked or self.focused or self.hover) else COR_TEXTO_2)


class GlassCard(tk.Frame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("bg", COR_SUPERFICIE)
        kwargs.setdefault("highlightbackground", COR_BORDA)
        kwargs.setdefault("highlightcolor", COR_BORDA)
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("bd", 0)
        super().__init__(master, **kwargs)


class UmbraPDFApp(tk.Tk):
    def __init__(self):
        preparar_identidade_windows()
        super().__init__()
        self.withdraw()
        self.title(f"{APP_NOME} · v{APP_VERSAO}")
        self.geometry("1180x760")
        self.minsize(980, 650)
        self.configure(bg=COR_FUNDO)

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self._icone_app_photos = []
        self._icone_app_ico = None
        self._hicon_handles = []
        self._configurar_icone_aplicativo()
        self.after(20, self._aplicar_acrilico_windows)

        self._preferencias = carregar_preferencias()
        self._salvar_preferencias_after = None
        self._persistencia_pronta = False

        origem_salva = self._preferencias.get("origem")
        try:
            origem_candidata = Path(origem_salva).expanduser().resolve() if origem_salva else None
        except (OSError, TypeError, ValueError):
            origem_candidata = None
        self.caminho_pasta: Path | None = (
            origem_candidata if origem_candidata and origem_candidata.is_dir() else None
        )

        saida_salva = self._preferencias.get("saida_custom")
        try:
            self.caminho_saida_custom: Path | None = (
                Path(saida_salva).expanduser().resolve() if saida_salva else None
            )
        except (OSError, TypeError, ValueError):
            self.caminho_saida_custom = None

        self.pdfs_encontrados: list[Path] = []
        self._tree_iids: dict[Path, str] = {}
        self._cancelar_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self.processando = False
        self.ultima_saida: Path | None = None

        # Prévia: renderizada em thread com debounce para não travar ao mover sliders.
        self._preview_after_id = None
        self._preview_seq = 0
        self._preview_photo = None
        self._preview_pdf: Path | None = None
        preview_modo_salvo = self._preferencias.get("preview_modo", "Comparar")
        if preview_modo_salvo not in {"Original", "Resultado", "Comparar"}:
            preview_modo_salvo = "Comparar"
        self.preview_modo = tk.StringVar(value=preview_modo_salvo)
        self._preview_page_index = 0
        self._preview_total_pages = 0
        self._preview_zoom = 1.0
        self._preview_fit_mode = "page"
        self._preview_compare_ratio = 0.5
        self._preview_image_bbox = None
        self.preview_page_var = tk.StringVar(value="— / —")
        self.preview_zoom_var = tk.StringVar(value="Página")

        # Variáveis de interface.
        if self.caminho_pasta:
            pasta_texto_inicial = str(self.caminho_pasta)
            saida_inicial = self.caminho_saida_custom or (self.caminho_pasta / PASTA_SAIDA_NOME)
            saida_texto_inicial = str(saida_inicial)
            self.ultima_saida = saida_inicial
        else:
            pasta_texto_inicial = "Nenhuma pasta selecionada"
            saida_texto_inicial = "—"

        self.pasta_selecionada = tk.StringVar(value=pasta_texto_inicial)
        self.saida_selecionada = tk.StringVar(value=saida_texto_inicial)
        self.status_var = tk.StringVar(value="Pronto")
        self.status_detalhe_var = tk.StringVar(value="Selecione uma pasta para começar")
        self.progresso_texto_var = tk.StringVar(value="0%")
        self.progresso_pagina_var = tk.StringVar(value="Página —")
        self.arquivo_atual_var = tk.StringVar(value="Nenhum processamento em andamento")
        self.cta_processar_var = tk.StringVar(value="Processar PDFs")
        self.total_var = tk.StringVar(value="0")
        self.pendentes_var = tk.StringVar(value="0")
        self.prontos_var = tk.StringVar(value="0")
        self.resumo_resultado_var = tk.StringVar(value="Ainda não há uma execução concluída.")

        def _numero_pref(chave, padrao, conversor):
            try:
                return conversor(self._preferencias.get(chave, padrao))
            except (TypeError, ValueError):
                return padrao

        preset_salvo = self._preferencias.get("preset", "Equilibrado")
        if preset_salvo not in {*PRESETS.keys(), "Personalizado"}:
            preset_salvo = "Equilibrado"
        self.preset = tk.StringVar(value=preset_salvo)
        self.dpi = tk.IntVar(value=_numero_pref("dpi", 230, int))
        self.cutoff = tk.DoubleVar(value=_numero_pref("cutoff", 1.5, float))
        self.brilho = tk.DoubleVar(value=_numero_pref("brilho", 0.92, float))
        self.contraste = tk.DoubleVar(value=_numero_pref("contraste", 1.50, float))
        self.nitidez = tk.DoubleVar(value=_numero_pref("nitidez", 1.30, float))
        self.qualidade = tk.IntVar(value=_numero_pref("qualidade", 86, int))
        self.recursivo = tk.BooleanVar(value=bool(self._preferencias.get("recursivo", False)))
        self.sobrescrever = tk.BooleanVar(value=bool(self._preferencias.get("sobrescrever", False)))

        self._montar_estilo()
        self._montar_layout()
        self._configurar_atalhos()
        self._configurar_persistencia()
        self._persistencia_pronta = True
        self.after(30, self._drenar_ui_queue)
        self.mostrar_pagina("pasta")
        if self.caminho_pasta:
            self.after(100, self.examinar_pasta)
        self.after(60, self._mostrar_janela_pronta)

    # ------------------------------------------------------------------
    # Estilo e layout
    # ------------------------------------------------------------------
    def _montar_estilo(self):
        estilo = ttk.Style(self)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass

        estilo.configure(
            "Glass.Horizontal.TProgressbar",
            troughcolor=COR_PROGRESSO_FUNDO,
            background=COR_ACENTO,
            bordercolor=COR_PROGRESSO_FUNDO,
            lightcolor=COR_ACENTO,
            darkcolor=COR_ACENTO,
            thickness=7,
        )
        estilo.configure(
            "Subtle.Horizontal.TProgressbar",
            troughcolor=COR_PROGRESSO_FUNDO,
            background="#69738A",
            bordercolor=COR_PROGRESSO_FUNDO,
            lightcolor="#69738A",
            darkcolor="#69738A",
            thickness=4,
        )
        estilo.configure(
            "Dark.Horizontal.TScale",
            background=COR_SUPERFICIE,
            troughcolor=COR_PROGRESSO_FUNDO,
        )
        estilo.configure(
            "Dark.TCheckbutton",
            background=COR_SUPERFICIE,
            foreground=COR_TEXTO_2,
            font=(FONTE_UI, 9),
            focuscolor=COR_SUPERFICIE,
        )
        estilo.map(
            "Dark.TCheckbutton",
            background=[("active", COR_SUPERFICIE)],
            foreground=[("active", COR_TEXTO)],
        )
        estilo.configure(
            "Dark.TCombobox",
            fieldbackground=COR_SUPERFICIE_2,
            background=COR_SUPERFICIE_2,
            foreground=COR_TEXTO,
            arrowcolor=COR_TEXTO_2,
            bordercolor=COR_BORDA,
            lightcolor=COR_BORDA,
            darkcolor=COR_BORDA,
            padding=6,
        )
        estilo.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", COR_SUPERFICIE_2)],
            foreground=[("readonly", COR_TEXTO)],
            selectbackground=[("readonly", COR_SUPERFICIE_2)],
            selectforeground=[("readonly", COR_TEXTO)],
        )
        estilo.configure(
            "Dark.Treeview",
            background=COR_SUPERFICIE,
            fieldbackground=COR_SUPERFICIE,
            foreground=COR_TEXTO_2,
            rowheight=30,
            borderwidth=0,
            relief="flat",
            bordercolor=COR_BORDA,
            lightcolor=COR_BORDA,
            darkcolor=COR_BORDA,
            font=(FONTE_UI, 9),
        )
        estilo.configure(
            "Dark.Treeview.Heading",
            background=COR_SUPERFICIE_2,
            foreground=COR_TEXTO_2,
            relief="flat",
            borderwidth=0,
            font=(FONTE_UI, 9, "bold"),
        )
        estilo.map(
            "Dark.Treeview",
            background=[("selected", "#222936")],
            foreground=[("selected", COR_TEXTO)],
        )
        estilo.map(
            "Dark.Treeview.Heading",
            background=[("active", COR_SUPERFICIE_HOVER)],
        )
        estilo.configure(
            "Dark.Vertical.TScrollbar",
            background=COR_SUPERFICIE_2,
            troughcolor=COR_SUPERFICIE,
            bordercolor=COR_SUPERFICIE,
            arrowcolor=COR_TEXTO_3,
            lightcolor=COR_SUPERFICIE_2,
            darkcolor=COR_SUPERFICIE_2,
            relief="flat",
            width=10,
        )
        estilo.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", COR_SUPERFICIE_HOVER)],
        )
        estilo.configure(
            "Dark.Horizontal.TScrollbar",
            background=COR_SUPERFICIE_2,
            troughcolor=COR_SUPERFICIE,
            bordercolor=COR_SUPERFICIE,
            arrowcolor=COR_TEXTO_3,
            lightcolor=COR_SUPERFICIE_2,
            darkcolor=COR_SUPERFICIE_2,
            relief="flat",
            width=10,
        )
        estilo.map(
            "Dark.Horizontal.TScrollbar",
            background=[("active", COR_SUPERFICIE_HOVER)],
        )

    def _montar_layout(self):
        root = tk.Frame(self, bg=COR_FUNDO)
        root.pack(fill="both", expand=True)

        # Rail estreita: navegação primária sempre no mesmo lugar.
        self.rail = tk.Frame(root, bg=COR_RAIL, width=64,
                             highlightbackground=COR_BORDA_SUAVE, highlightthickness=0)
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)

        logo = tk.Canvas(self.rail, width=48, height=48, bg=COR_RAIL,
                         highlightthickness=0, bd=0)
        logo.pack(pady=(14, 20))
        if ImageTk is not None:
            img = renderizar_svg_pil(APP_ICON_SVG, 38)
            if img is not None:
                self._logo_photo = ImageTk.PhotoImage(img)
                logo.create_image(24, 24, image=self._logo_photo)
            else:
                logo.create_oval(9, 9, 39, 39, outline=COR_ACENTO, width=2)
        Tooltip(logo, APP_NOME)

        self.nav_botoes: dict[str, NavIconButton] = {}
        self._add_nav("ferramenta", "settings", "Ajustes  ·  Ctrl+,",
                      lambda: self.mostrar_pagina("ferramenta"))
        self._add_nav("pasta", "folder", "Arquivos  ·  Ctrl+O",
                      lambda: self.mostrar_pagina("pasta"))
        self._add_nav("processar", "play", "Processar  ·  Ctrl+Enter",
                      lambda: self.mostrar_pagina("processar"))

        spacer = tk.Frame(self.rail, bg=COR_RAIL)
        spacer.pack(fill="both", expand=True)

        abrir_btn = NavIconButton(
            self.rail, "folder_open", "Abrir resultados  ·  Ctrl+Shift+O",
            self.abrir_pasta_saida
        )
        abrir_btn.pack(pady=(0, 14))
        self.nav_botoes["abrir"] = abrir_btn

        self.conteudo = tk.Frame(root, bg=COR_FUNDO)
        self.conteudo.pack(side="left", fill="both", expand=True)

        self.header = tk.Frame(self.conteudo, bg=COR_FUNDO, height=96)
        self.header.pack(fill="x", padx=32, pady=(18, 0))
        self.header.pack_propagate(False)

        header_text = tk.Frame(self.header, bg=COR_FUNDO)
        header_text.pack(side="left", fill="y")
        tk.Label(
            header_text, text="UMBRA PDF", bg=COR_FUNDO, fg=COR_ACENTO,
            font=(FONTE_UI, 8, "bold"), anchor="w"
        ).pack(anchor="w", pady=(3, 0))
        self.titulo_pagina = tk.Label(
            header_text, text="", bg=COR_FUNDO, fg=COR_TEXTO,
            font=(FONTE_UI, 21, "bold"), anchor="w"
        )
        self.titulo_pagina.pack(anchor="w", pady=(1, 1))
        self.subtitulo_pagina = tk.Label(
            header_text, text="", bg=COR_FUNDO, fg=COR_TEXTO_2,
            font=(FONTE_UI, 9), anchor="w"
        )
        self.subtitulo_pagina.pack(anchor="w")

        status_wrap = tk.Frame(self.header, bg=COR_FUNDO)
        status_wrap.pack(side="right", pady=(8, 0), anchor="n")
        self.status_dot = tk.Canvas(status_wrap, width=12, height=30, bg=COR_FUNDO,
                                    highlightthickness=0)
        self.status_dot.pack(side="left")
        self.status_dot.create_oval(3, 11, 9, 17, fill=COR_TEXTO_3, outline="", tags="dot")
        self.status_chip = tk.Label(
            status_wrap,
            textvariable=self.status_var,
            bg=COR_SUPERFICIE_2,
            fg=COR_TEXTO_2,
            font=(FONTE_UI, 9, "bold"),
            padx=12,
            pady=7,
            highlightbackground=COR_BORDA,
            highlightthickness=1,
        )
        self.status_chip.pack(side="left")

        self.page_container = tk.Frame(self.conteudo, bg=COR_FUNDO)
        self.page_container.pack(fill="both", expand=True, padx=32, pady=(0, 18))
        self.page_container.grid_rowconfigure(0, weight=1)
        self.page_container.grid_columnconfigure(0, weight=1)

        self.paginas: dict[str, tk.Frame] = {}
        self._criar_pagina_ferramenta()
        self._criar_pagina_pasta()
        self._criar_pagina_processar()

        # Barra de rodapé discreta: atalhos e destino ficam visíveis sem competir.
        footer = tk.Frame(self.conteudo, bg=COR_FUNDO, height=28)
        footer.pack(fill="x", padx=32, pady=(0, 10))
        footer.pack_propagate(False)
        tk.Label(
            footer, text="Ctrl+O abrir pasta   •   F5 reexaminar   •   Ctrl+Enter processar",
            bg=COR_FUNDO, fg=COR_TEXTO_3, font=(FONTE_UI, 8)
        ).pack(side="left")
        tk.Label(
            footer, text=f"Umbra PDF v{APP_VERSAO}  ·  processamento local  ·  gravação segura", bg=COR_FUNDO, fg=COR_TEXTO_3,
            font=(FONTE_UI, 8)
        ).pack(side="right")

    def _add_nav(self, chave: str, icon: str, tooltip: str, command: Callable[[], None]):
        botao = NavIconButton(self.rail, icon, tooltip, command)
        botao.pack(pady=4)
        self.nav_botoes[chave] = botao

    def _pagina_base(self, chave: str) -> tk.Frame:
        pagina = tk.Frame(self.page_container, bg=COR_FUNDO)
        pagina.grid(row=0, column=0, sticky="nsew")
        self.paginas[chave] = pagina
        return pagina

    def _criar_pagina_ferramenta(self):
        pagina = self._pagina_base("ferramenta")
        pagina.grid_columnconfigure(0, weight=5)
        pagina.grid_columnconfigure(1, weight=5)
        pagina.grid_rowconfigure(0, weight=1)

        card = GlassCard(pagina)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        topo = tk.Frame(card, bg=COR_SUPERFICIE)
        topo.pack(fill="x", padx=22, pady=(18, 8))
        titulo_wrap = tk.Frame(topo, bg=COR_SUPERFICIE)
        titulo_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(titulo_wrap, text="Tratamento", bg=COR_SUPERFICIE,
                 fg=COR_TEXTO, font=(FONTE_UI, 12, "bold")).pack(anchor="w")
        tk.Label(titulo_wrap, text="Refine o documento e confira o resultado antes do lote.",
                 bg=COR_SUPERFICIE, fg=COR_TEXTO_3,
                 font=(FONTE_UI, 8)).pack(anchor="w", pady=(2, 0))
        reset_btn = self._botao(
            topo, "", lambda: self._aplicar_preset("Equilibrado"),
            compacto=True, icon="refresh", width=34
        )
        reset_btn.pack(side="right", padx=(10, 0))
        Tooltip(reset_btn, "Restaurar perfil Equilibrado")

        preset_wrap = tk.Frame(card, bg=COR_SUPERFICIE)
        preset_wrap.pack(fill="x", padx=22, pady=(7, 10))
        tk.Label(preset_wrap, text="Perfil", bg=COR_SUPERFICIE, fg=COR_TEXTO_2,
                 font=(FONTE_UI, 8, "bold")).pack(side="left", padx=(0, 10))
        self.preset_selector = SegmentedControl(
            preset_wrap, [*PRESETS.keys(), "Personalizado"], self.preset,
            command=self._aplicar_preset, compact=True,
        )
        self.preset_selector.pack(side="left")
        tk.Label(
            preset_wrap, text="Salvo automaticamente", bg=COR_SUPERFICIE,
            fg=COR_TEXTO_3, font=(FONTE_UI, 7)
        ).pack(side="right")

        divisoria = tk.Frame(card, bg=COR_BORDA_SUAVE, height=1)
        divisoria.pack(fill="x", padx=22, pady=(0, 8))

        scroll_wrap = tk.Frame(card, bg=COR_SUPERFICIE)
        scroll_wrap.pack(fill="both", expand=True, padx=(14, 6), pady=(0, 8))
        scroll_wrap.grid_rowconfigure(0, weight=1)
        scroll_wrap.grid_columnconfigure(0, weight=1)
        self.settings_canvas = tk.Canvas(
            scroll_wrap, bg=COR_SUPERFICIE, bd=0, highlightthickness=0,
            yscrollincrement=24,
        )
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll = ttk.Scrollbar(
            scroll_wrap, orient="vertical", command=self.settings_canvas.yview,
            style="Dark.Vertical.TScrollbar"
        )
        settings_scroll.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)

        settings_inner = tk.Frame(self.settings_canvas, bg=COR_SUPERFICIE)
        settings_window = self.settings_canvas.create_window((0, 0), window=settings_inner, anchor="nw")
        settings_inner.bind(
            "<Configure>",
            lambda _e: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")),
        )
        self.settings_canvas.bind(
            "<Configure>",
            lambda e: self.settings_canvas.itemconfigure(settings_window, width=e.width),
        )
        self.settings_canvas.bind(
            "<MouseWheel>",
            lambda e: self.settings_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"),
        )

        opcoes = tk.Frame(settings_inner, bg=COR_SUPERFICIE)
        opcoes.pack(fill="x", padx=8, pady=(4, 9))
        ModernCheckbutton(
            opcoes, "Incluir subpastas", self.recursivo, self._opcao_arquivo_alterada
        ).pack(anchor="w")
        ModernCheckbutton(
            opcoes, "Reprocessar resultados existentes", self.sobrescrever, self._opcao_arquivo_alterada
        ).pack(anchor="w", pady=(6, 0))
        tk.Frame(settings_inner, bg=COR_BORDA_SUAVE, height=1).pack(fill="x", padx=8, pady=(0, 6))

        sliders = tk.Frame(settings_inner, bg=COR_SUPERFICIE)
        sliders.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._controle_slider(sliders, "Resolução", "Detalhe usado na rasterização", self.dpi, 150, 400, 1, " dpi")
        self._controle_slider(sliders, "Autocontraste", "Recorta os extremos do histograma", self.cutoff, 0, 5, 0.1, "%")
        self._controle_slider(sliders, "Escurecimento", "Valores menores deixam o scan mais denso", self.brilho, 0.65, 1.10, 0.01, "x")
        self._controle_slider(sliders, "Contraste", "Separa melhor o fundo e o texto", self.contraste, 1.0, 2.6, 0.05, "x")
        self._controle_slider(sliders, "Nitidez", "Reforça bordas sem alterar a geometria", self.nitidez, 1.0, 2.3, 0.05, "x")
        self._controle_slider(sliders, "Qualidade JPEG", "Equilíbrio entre tamanho e artefatos", self.qualidade, 55, 100, 1, "%")

        # Visualizador: canvas rolável com navegação por página, zoom e comparação.
        preview = GlassCard(pagina)
        preview.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        preview.grid_rowconfigure(2, weight=1)
        preview.grid_columnconfigure(0, weight=1)

        pheader = tk.Frame(preview, bg=COR_SUPERFICIE)
        pheader.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 8))
        ptitle = tk.Frame(pheader, bg=COR_SUPERFICIE)
        ptitle.pack(fill="x")
        tk.Label(ptitle, text="Visualizador", bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 11, "bold")).pack(anchor="w")
        tk.Label(ptitle, text="Página selecionada · prévia não altera o arquivo original",
                 bg=COR_SUPERFICIE, fg=COR_TEXTO_3,
                 font=(FONTE_UI, 8)).pack(anchor="w", pady=(1, 0))
        self.preview_selector = SegmentedControl(
            pheader, ["Original", "Resultado", "Comparar"], self.preview_modo,
            command=self._set_preview_modo, compact=True,
        )
        self.preview_selector.pack(anchor="e", pady=(7, 0))

        toolbar = tk.Frame(preview, bg=COR_SUPERFICIE)
        toolbar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))

        self.preview_prev_btn = self._botao(
            toolbar, "", lambda: self._mudar_pagina_preview(-1),
            compacto=True, width=34, icon="chevron_left"
        )
        Tooltip(self.preview_prev_btn, "Página anterior · Page Up")
        self.preview_prev_btn.pack(side="left")
        self.preview_next_btn = self._botao(
            toolbar, "", lambda: self._mudar_pagina_preview(1),
            compacto=True, width=34, icon="chevron_right"
        )
        Tooltip(self.preview_next_btn, "Próxima página · Page Down")
        self.preview_next_btn.pack(side="left", padx=(5, 0))
        tk.Label(toolbar, textvariable=self.preview_page_var, bg=COR_SUPERFICIE,
                 fg=COR_TEXTO_2, font=(FONTE_UI, 8, "bold"), width=9).pack(side="left", padx=(7, 12))

        sep = tk.Frame(toolbar, bg=COR_BORDA_SUAVE, width=1, height=20)
        sep.pack(side="left", padx=(0, 10))

        zoom_out = self._botao(
            toolbar, "", lambda: self._zoom_preview(-0.12),
            compacto=True, width=34, icon="minus"
        )
        zoom_out.pack(side="left")
        Tooltip(zoom_out, "Diminuir zoom")
        self.preview_zoom_chip = tk.Label(
            toolbar, textvariable=self.preview_zoom_var, bg=COR_SUPERFICIE_2,
            fg=COR_TEXTO_2, font=(FONTE_UI, 8, "bold"), width=8,
            padx=6, pady=6, highlightbackground=COR_BORDA, highlightthickness=1
        )
        self.preview_zoom_chip.pack(side="left", padx=5)
        zoom_in = self._botao(
            toolbar, "", lambda: self._zoom_preview(0.12),
            compacto=True, width=34, icon="plus"
        )
        zoom_in.pack(side="left")
        Tooltip(zoom_in, "Aumentar zoom")
        fit_page_btn = self._botao(
            toolbar, "", lambda: self._definir_fit_preview("page"),
            compacto=True, width=34, icon="fit_page"
        )
        fit_page_btn.pack(side="right")
        Tooltip(fit_page_btn, "Ajustar página inteira")
        fit_width_btn = self._botao(
            toolbar, "", lambda: self._definir_fit_preview("width"),
            compacto=True, width=34, icon="fit_width"
        )
        fit_width_btn.pack(side="right", padx=(0, 5))
        Tooltip(fit_width_btn, "Ajustar à largura")

        preview_stage = tk.Frame(preview, bg="#07090C", highlightbackground=COR_BORDA_SUAVE,
                                 highlightthickness=1)
        preview_stage.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 9))
        preview_stage.grid_rowconfigure(0, weight=1)
        preview_stage.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_stage, bg="#07090C", bd=0, highlightthickness=0,
            xscrollincrement=20, yscrollincrement=20, takefocus=True,
            cursor="crosshair"
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_scroll_y = ttk.Scrollbar(
            preview_stage, orient="vertical", command=self.preview_canvas.yview,
            style="Dark.Vertical.TScrollbar"
        )
        self.preview_scroll_y.grid(row=0, column=1, sticky="ns")
        self.preview_scroll_x = ttk.Scrollbar(
            preview_stage, orient="horizontal", command=self.preview_canvas.xview,
            style="Dark.Horizontal.TScrollbar"
        )
        self.preview_scroll_x.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.configure(
            yscrollcommand=self.preview_scroll_y.set,
            xscrollcommand=self.preview_scroll_x.set,
        )
        self.preview_canvas.bind("<Configure>", lambda _e: self._agendar_preview(180))
        self.preview_canvas.bind("<MouseWheel>", self._preview_mousewheel)
        self.preview_canvas.bind("<Control-MouseWheel>", self._preview_ctrl_mousewheel)
        self.preview_canvas.bind("<Button-1>", self._preview_compare_drag)
        self.preview_canvas.bind("<B1-Motion>", self._preview_compare_drag)
        self.preview_canvas.bind("<Prior>", lambda _e: self._mudar_pagina_preview(-1))
        self.preview_canvas.bind("<Next>", lambda _e: self._mudar_pagina_preview(1))
        self.preview_canvas.bind("<plus>", lambda _e: self._zoom_preview(0.12))
        self.preview_canvas.bind("<minus>", lambda _e: self._zoom_preview(-0.12))
        self._mostrar_placeholder_preview("Selecione uma pasta com PDFs para visualizar o documento.")

        self.preview_info = tk.Label(
            preview, text="A prévia é otimizada para navegação; o PDF final usa o DPI configurado.",
            bg=COR_SUPERFICIE, fg=COR_TEXTO_3, font=(FONTE_UI, 8), anchor="w"
        )
        self.preview_info.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))
        self._atualizar_botoes_preview()

    def _criar_pagina_pasta(self):
        pagina = self._pagina_base("pasta")
        pagina.grid_columnconfigure(0, weight=1)
        pagina.grid_rowconfigure(2, weight=1)

        seletor = GlassCard(pagina)
        seletor.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        seletor.grid_columnconfigure(0, weight=1)

        # Origem
        origem_row = tk.Frame(seletor, bg=COR_SUPERFICIE)
        origem_row.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        origem_row.grid_columnconfigure(0, weight=1)
        origem_text = tk.Frame(origem_row, bg=COR_SUPERFICIE)
        origem_text.grid(row=0, column=0, sticky="ew")
        tk.Label(origem_text, text="Origem", bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 9, "bold")).pack(anchor="w")
        tk.Label(origem_text, textvariable=self.pasta_selecionada, bg=COR_SUPERFICIE,
                 fg=COR_TEXTO_2, font=(FONTE_UI, 9), anchor="w").pack(fill="x", pady=(3, 0))
        origem_actions = tk.Frame(origem_row, bg=COR_SUPERFICIE)
        origem_actions.grid(row=0, column=1, padx=(14, 0))
        self.botao_reexaminar = self._botao(
            origem_actions, "Reexaminar", self.examinar_pasta, compacto=True, icon="refresh"
        )
        self.botao_reexaminar.pack(side="left", padx=(0, 6))
        self.botao_selecionar = self._botao(
            origem_actions, "Escolher pasta", self.selecionar_pasta, primario=True, icon="folder"
        )
        self.botao_selecionar.pack(side="left")

        tk.Frame(seletor, bg=COR_BORDA_SUAVE, height=1).grid(
            row=1, column=0, sticky="ew", padx=20
        )

        # Destino configurável, usando 'Umbra - Resultados' como padrão.
        saida_row = tk.Frame(seletor, bg=COR_SUPERFICIE)
        saida_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 15))
        saida_row.grid_columnconfigure(0, weight=1)
        saida_text = tk.Frame(saida_row, bg=COR_SUPERFICIE)
        saida_text.grid(row=0, column=0, sticky="ew")
        tk.Label(saida_text, text="Destino", bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 9, "bold")).pack(anchor="w")
        tk.Label(saida_text, textvariable=self.saida_selecionada, bg=COR_SUPERFICIE,
                 fg=COR_TEXTO_3, font=(FONTE_UI, 8), anchor="w").pack(fill="x", pady=(3, 0))
        saida_actions = tk.Frame(saida_row, bg=COR_SUPERFICIE)
        saida_actions.grid(row=0, column=1, padx=(14, 0))
        self._botao(
            saida_actions, "Padrão", self.restaurar_pasta_saida,
            compacto=True
        ).pack(side="left", padx=(0, 6))
        self._botao(
            saida_actions, "Alterar", self.selecionar_pasta_saida,
            compacto=True, icon="folder"
        ).pack(side="left", padx=(0, 6))
        self._botao(
            saida_actions, "Abrir", self.abrir_pasta_saida,
            compacto=True, icon="folder_open"
        ).pack(side="left")

        stats = tk.Frame(pagina, bg=COR_FUNDO)
        stats.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        stats.grid_columnconfigure((0, 1, 2), weight=1, uniform="stats")
        self._stat_card(stats, 0, "PDFs encontrados", self.total_var)
        self._stat_card(stats, 1, "Pendentes", self.pendentes_var)
        self._stat_card(stats, 2, "Já processados", self.prontos_var)

        lista_card = GlassCard(pagina)
        lista_card.grid(row=2, column=0, sticky="nsew")
        lista_card.grid_rowconfigure(1, weight=1)
        lista_card.grid_columnconfigure(0, weight=1)

        list_header = tk.Frame(lista_card, bg=COR_SUPERFICIE)
        list_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(13, 8))
        titulo_wrap = tk.Frame(list_header, bg=COR_SUPERFICIE)
        titulo_wrap.pack(side="left")
        tk.Label(titulo_wrap, text="Arquivos", bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 10, "bold")).pack(anchor="w")
        tk.Label(titulo_wrap, text="Clique para usar o PDF na prévia · duplo clique para abrir.",
                 bg=COR_SUPERFICIE, fg=COR_TEXTO_3,
                 font=(FONTE_UI, 8)).pack(anchor="w", pady=(1, 0))
        self._botao(
            list_header, "Ver prévia", lambda: self.mostrar_pagina("ferramenta"),
            compacto=True, icon="eye"
        ).pack(side="right")

        tree_wrap = tk.Frame(lista_card, bg=COR_SUPERFICIE)
        tree_wrap.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_wrap, columns=("arquivo", "tamanho", "status"),
            show="headings", style="Dark.Treeview", selectmode="browse"
        )
        self.tree.heading("arquivo", text="Arquivo")
        self.tree.heading("tamanho", text="Tamanho")
        self.tree.heading("status", text="Status")
        self.tree.column("arquivo", width=650, minwidth=280, anchor="w")
        self.tree.column("tamanho", width=110, minwidth=90, anchor="e")
        self.tree.column("status", width=150, minwidth=120, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._ao_selecionar_pdf)
        self.tree.bind("<Double-1>", self._abrir_pdf_selecionado)
        self.tree.tag_configure("pendente", foreground=COR_TEXTO_2)
        self.tree.tag_configure("pronto", foreground=COR_SUCESSO)
        self.tree.tag_configure("processando", foreground=COR_ACENTO_HOVER)
        self.tree.tag_configure("erro", foreground=COR_ERRO)
        self.tree.tag_configure("cancelado", foreground=COR_ALERTA)

        scroll = ttk.Scrollbar(
            tree_wrap, orient="vertical", command=self.tree.yview,
            style="Dark.Vertical.TScrollbar"
        )
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

    def _criar_pagina_processar(self):
        pagina = self._pagina_base("processar")
        pagina.grid_columnconfigure(0, weight=1)
        pagina.grid_rowconfigure(1, weight=1)

        hero = GlassCard(pagina)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        hero.grid_columnconfigure(0, weight=1)

        textos = tk.Frame(hero, bg=COR_SUPERFICIE)
        textos.grid(row=0, column=0, sticky="ew", padx=22, pady=(17, 10))
        tk.Label(textos, textvariable=self.arquivo_atual_var, bg=COR_SUPERFICIE,
                 fg=COR_TEXTO, font=(FONTE_UI, 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(textos, textvariable=self.status_detalhe_var, bg=COR_SUPERFICIE,
                 fg=COR_TEXTO_2, font=(FONTE_UI, 9), anchor="w").pack(fill="x", pady=(3, 0))

        botoes = tk.Frame(hero, bg=COR_SUPERFICIE)
        botoes.grid(row=0, column=1, padx=(10, 20), pady=16)
        self.botao_processar = self._botao(
            botoes, "Processar PDFs", self.iniciar_processamento,
            primario=True, icon="play"
        )
        self.botao_processar.pack(side="left")
        self.botao_cancelar = self._botao(
            botoes, "Cancelar", self.cancelar_processamento, icon="x", danger=True
        )
        self.botao_cancelar.pack(side="left", padx=(8, 0))
        self.botao_cancelar.configure(state="disabled")

        progress_wrap = tk.Frame(hero, bg=COR_SUPERFICIE)
        progress_wrap.grid(row=1, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 17))
        progress_wrap.grid_columnconfigure(0, weight=1)

        linha_overall = tk.Frame(progress_wrap, bg=COR_SUPERFICIE)
        linha_overall.grid(row=0, column=0, sticky="ew")
        linha_overall.grid_columnconfigure(0, weight=1)
        self.barra_progresso = ttk.Progressbar(
            linha_overall, mode="determinate", maximum=100,
            style="Glass.Horizontal.TProgressbar"
        )
        self.barra_progresso.grid(row=0, column=0, sticky="ew")
        tk.Label(linha_overall, textvariable=self.progresso_texto_var,
                 bg=COR_SUPERFICIE, fg=COR_TEXTO_2, font=(FONTE_UI, 8, "bold"),
                 width=5).grid(row=0, column=1, padx=(10, 0))

        linha_pagina = tk.Frame(progress_wrap, bg=COR_SUPERFICIE)
        linha_pagina.grid(row=1, column=0, sticky="ew", pady=(9, 0))
        linha_pagina.grid_columnconfigure(0, weight=1)
        self.barra_pagina = ttk.Progressbar(
            linha_pagina, mode="determinate", maximum=100,
            style="Subtle.Horizontal.TProgressbar"
        )
        self.barra_pagina.grid(row=0, column=0, sticky="ew")
        tk.Label(linha_pagina, textvariable=self.progresso_pagina_var,
                 bg=COR_SUPERFICIE, fg=COR_TEXTO_3, font=(FONTE_UI, 8),
                 width=12, anchor="e").grid(row=0, column=1, padx=(10, 0))

        log_card = GlassCard(pagina)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)

        log_header = tk.Frame(log_card, bg=COR_SUPERFICIE)
        log_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        tk.Label(log_header, text="Atividade", bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 10, "bold")).pack(side="left")
        tk.Label(log_header, text="O arquivo final só aparece depois de concluído.",
                 bg=COR_SUPERFICIE, fg=COR_TEXTO_3,
                 font=(FONTE_UI, 8)).pack(side="left", padx=(10, 0))
        self._botao(log_header, "Limpar", lambda: self._log("", limpar=True),
                    compacto=True).pack(side="right")
        self._botao(log_header, "Copiar", self.copiar_log,
                    compacto=True, icon="copy").pack(side="right", padx=(0, 6))
        self._botao(log_header, "Abrir resultados", self.abrir_pasta_saida,
                    compacto=True, icon="folder_open").pack(side="right", padx=(0, 6))

        self.texto_log = tk.Text(
            log_card, bg="#0B0D10", fg=COR_TEXTO_2,
            insertbackground=COR_TEXTO, selectbackground="#252D39",
            relief="flat", borderwidth=0, highlightthickness=0,
            font=(FONTE_MONO, 9), wrap="word", padx=14, pady=12,
        )
        self.texto_log.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))
        self.texto_log.insert("end", "Selecione uma pasta e inicie o processamento.\n")
        self.texto_log.configure(state="disabled")

    def _botao(self, master, texto: str, command: Callable[[], None],
               primario=False, compacto=False, icon: str | None = None,
               danger: bool = False, width: int | None = None):
        return ModernButton(
            master, texto, command,
            primary=primario, compact=compacto,
            icon=icon, danger=danger, width=width,
        )

    def _stat_card(self, master, col: int, titulo: str, var: tk.StringVar):
        card = GlassCard(master)
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0 if col == 2 else 6))
        tk.Label(card, text=titulo, bg=COR_SUPERFICIE, fg=COR_TEXTO_3,
                 font=(FONTE_UI, 8)).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(card, textvariable=var, bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 17, "bold")).pack(anchor="w", padx=16, pady=(0, 12))

    def _controle_slider(self, master, titulo, descricao, variavel, minimo, maximo, resolucao, sufixo):
        bloco = tk.Frame(master, bg=COR_SUPERFICIE)
        bloco.pack(fill="x", pady=(2, 9))

        linha = tk.Frame(bloco, bg=COR_SUPERFICIE)
        linha.pack(fill="x")
        tk.Label(linha, text=titulo, bg=COR_SUPERFICIE, fg=COR_TEXTO,
                 font=(FONTE_UI, 9, "bold")).pack(side="left")
        valor_label = tk.Label(linha, bg=COR_SUPERFICIE_2, fg=COR_TEXTO_2,
                               font=(FONTE_UI, 8, "bold"), padx=7, pady=2)
        valor_label.pack(side="right")

        tk.Label(bloco, text=descricao, bg=COR_SUPERFICIE, fg=COR_TEXTO_3,
                 font=(FONTE_UI, 8)).pack(anchor="w", pady=(2, 3))

        def formatar_valor():
            valor = variavel.get()
            if isinstance(variavel, tk.IntVar):
                return f"{int(round(valor))}{sufixo}"
            return f"{float(valor):.2f}{sufixo}"

        def atualizar(_valor=None):
            if isinstance(variavel, tk.IntVar):
                variavel.set(int(round(float(variavel.get()) / resolucao) * resolucao))
            else:
                novo = round(float(variavel.get()) / resolucao) * resolucao
                variavel.set(round(novo, 3))
            valor_label.configure(text=formatar_valor())

        slider = ModernSlider(
            bloco, variable=variavel, minimo=minimo, maximo=maximo,
            resolucao=resolucao, on_change=lambda: atualizar()
        )
        slider.pack(fill="x")
        atualizar()
        def ao_mudar(*_args):
            valor_label.configure(text=formatar_valor())
            if hasattr(self, "preview_canvas"):
                self._agendar_preview()
        variavel.trace_add("write", ao_mudar)

    # ------------------------------------------------------------------
    # Navegação / status
    # ------------------------------------------------------------------
    def mostrar_pagina(self, chave: str):
        textos = {
            "ferramenta": ("Ferramenta", "Ajustes de processamento e comportamento"),
            "pasta": ("Arquivos", "Escolha a origem e revise o que será processado"),
            "processar": ("Processar", "Acompanhe o lote e cancele com segurança quando necessário"),
        }
        pagina = self.paginas[chave]
        pagina.tkraise()
        titulo, subtitulo = textos[chave]
        self.titulo_pagina.configure(text=titulo)
        self.subtitulo_pagina.configure(text=subtitulo)
        for nome, botao in self.nav_botoes.items():
            if nome != "abrir":
                botao.set_ativo(nome == chave)
        if chave == "ferramenta":
            self._agendar_preview(80)

    def _set_status(self, texto: str, detalhe: str | None = None, cor: str | None = None):
        self.status_var.set(texto)
        if detalhe is not None:
            self.status_detalhe_var.set(detalhe)
        cor_final = cor or COR_TEXTO_2
        self.status_chip.configure(fg=cor_final)
        if hasattr(self, "status_dot"):
            self.status_dot.itemconfigure("dot", fill=cor_final)

    # ------------------------------------------------------------------
    # Integração visual / atalhos / prévia
    # ------------------------------------------------------------------
    def _configurar_icone_aplicativo(self):
        """Aplica um PNG embutido e, quando possível, um ICO multi-resolução."""
        # Primeiro caminho: PNG embutido suportado pelo próprio Tk. Isso garante
        # que a janela nunca dependa da presença de um arquivo de ícone externo.
        try:
            photo_embutida = tk.PhotoImage(data=APP_ICON_PNG_BASE64)
            self._icone_app_photos = [photo_embutida]
            self.iconphoto(True, photo_embutida)
        except tk.TclError:
            self._icone_app_photos = []

        if Image is None:
            return
        try:
            base = renderizar_svg_pil(APP_ICON_SVG, 256)
            if base is None:
                # Ainda mantemos o PNG embutido aplicado acima.
                return

            # Adiciona tamanhos extras quando ImageTk está disponível.
            if ImageTk is not None:
                extras = []
                for tamanho in (16, 24, 32, 48, 64, 128):
                    redimensionada = base.resize((tamanho, tamanho), Image.Resampling.LANCZOS)
                    extras.append(ImageTk.PhotoImage(redimensionada))
                self._icone_app_photos.extend(extras)
                if self._icone_app_photos:
                    self.iconphoto(True, *self._icone_app_photos)

            if sys.platform.startswith("win"):
                caminho_ico = Path(tempfile.gettempdir()) / "umbra_pdf_app.ico"
                base.save(
                    caminho_ico,
                    format="ICO",
                    sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                           (48, 48), (64, 64), (128, 128), (256, 256)],
                )
                self._icone_app_ico = caminho_ico
                try:
                    self.iconbitmap(default=str(caminho_ico))
                except tk.TclError:
                    pass
                self.after(1, self._aplicar_icone_hwnd_windows)
        except Exception:
            traceback.print_exc()

    def _janela_hwnd_windows(self):
        if not sys.platform.startswith("win"):
            return None
        try:
            import ctypes
            self.update_idletasks()
            hwnd = int(self.winfo_id())
            pai = int(ctypes.windll.user32.GetParent(hwnd) or 0)
            return pai or hwnd
        except Exception:
            return None

    def _aplicar_icone_hwnd_windows(self):
        """Força os ícones grande/pequeno no HWND (taskbar, Alt+Tab e título)."""
        if not sys.platform.startswith("win") or not self._icone_app_ico:
            return
        try:
            import ctypes
            hwnd = self._janela_hwnd_windows()
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            caminho = str(self._icone_app_ico)
            hbig = user32.LoadImageW(None, caminho, IMAGE_ICON, 64, 64, LR_LOADFROMFILE)
            hsmall = user32.LoadImageW(None, caminho, IMAGE_ICON, 20, 20, LR_LOADFROMFILE)
            if hbig:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hbig)
                self._hicon_handles.append(hbig)
            if hsmall:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hsmall)
                self._hicon_handles.append(hsmall)
        except Exception:
            pass

    def _mostrar_janela_pronta(self):
        """Exibe a janela apenas depois de tema, layout e ícone estarem aplicados."""
        try:
            self.update_idletasks()
            self._aplicar_icone_hwnd_windows()
            self.deiconify()
            self.lift()
        except tk.TclError:
            pass

    def _aplicar_acrilico_windows(self):
        """Ativa dark title bar, cantos arredondados e Mica quando o Windows suporta."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            hwnd = self.winfo_id()
            pai = ctypes.windll.user32.GetParent(hwnd)
            if pai:
                hwnd = pai
            dwm = ctypes.windll.dwmapi
            valor = ctypes.c_int(1)
            # DWMWA_USE_IMMERSIVE_DARK_MODE
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(valor), ctypes.sizeof(valor))
            # DWMWA_WINDOW_CORNER_PREFERENCE = ROUND
            canto = ctypes.c_int(2)
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(canto), ctypes.sizeof(canto))
            # DWMWA_SYSTEMBACKDROP_TYPE = Mica (Windows 11). Ignorado em versões antigas.
            mica = ctypes.c_int(2)
            dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(mica), ctypes.sizeof(mica))
        except Exception:
            pass

    def _configurar_atalhos(self):
        self.bind_all("<Control-o>", lambda _e: self.selecionar_pasta())
        self.bind_all("<Control-O>", lambda _e: self.selecionar_pasta())
        self.bind_all("<Control-comma>", lambda _e: self.mostrar_pagina("ferramenta"))
        self.bind_all("<Control-Return>", lambda _e: self.iniciar_processamento())
        self.bind_all("<Control-Shift-O>", lambda _e: self.abrir_pasta_saida())
        self.bind_all("<F5>", lambda _e: self.examinar_pasta())
        self.bind_all("<Escape>", lambda _e: self.cancelar_processamento() if self.processando else None)

    def _set_preview_modo(self, modo: str):
        if modo not in {"Original", "Resultado", "Comparar"}:
            return
        if self.preview_modo.get() != modo:
            self.preview_modo.set(modo)
        self._atualizar_botoes_preview()
        self._agendar_preview(20)

    def _atualizar_botoes_preview(self):
        if hasattr(self, "preview_selector"):
            self.preview_selector.refresh()

    def _mostrar_placeholder_preview(self, texto: str):
        if not hasattr(self, "preview_canvas"):
            return
        self.preview_canvas.delete("all")
        w = max(320, self.preview_canvas.winfo_width())
        h = max(280, self.preview_canvas.winfo_height())
        cx, cy = w / 2, h / 2
        # Pequeno pictograma de documento desenhado no próprio Canvas.
        self.preview_canvas.create_rectangle(
            cx - 24, cy - 64, cx + 24, cy - 8,
            fill="#0F1217", outline=COR_BORDA, width=1,
        )
        self.preview_canvas.create_line(
            cx - 13, cy - 45, cx + 13, cy - 45,
            fill=COR_TEXTO_3, width=2,
        )
        self.preview_canvas.create_line(
            cx - 13, cy - 34, cx + 8, cy - 34,
            fill=COR_TEXTO_3, width=2,
        )
        self.preview_canvas.create_text(
            cx, cy + 20, text=texto, fill=COR_TEXTO_3,
            font=(FONTE_UI, 9), width=min(330, w - 60), justify="center",
        )
        self.preview_canvas.configure(scrollregion=(0, 0, w, h))
        self.preview_page_var.set("— / —")
        self._preview_photo = None
        self._preview_image_bbox = None
        self._atualizar_estado_navegacao_preview()

    def _atualizar_estado_navegacao_preview(self):
        if not hasattr(self, "preview_prev_btn"):
            return
        total = int(self._preview_total_pages or 0)
        self.preview_prev_btn.configure(
            state="normal" if total > 0 and self._preview_page_index > 0 else "disabled"
        )
        self.preview_next_btn.configure(
            state="normal" if total > 0 and self._preview_page_index < total - 1 else "disabled"
        )

    def _agendar_preview(self, atraso: int = 260):
        if not hasattr(self, "preview_canvas"):
            return
        if self._preview_after_id:
            try:
                self.after_cancel(self._preview_after_id)
            except tk.TclError:
                pass
        self._preview_after_id = self.after(atraso, self._iniciar_preview)

    def _mudar_pagina_preview(self, delta: int):
        total = int(self._preview_total_pages or 0)
        if total <= 0:
            return
        novo = max(0, min(total - 1, self._preview_page_index + delta))
        if novo == self._preview_page_index:
            return
        self._preview_page_index = novo
        self._agendar_preview(10)

    def _zoom_preview(self, delta: float):
        if self._preview_fit_mode != "manual":
            self._preview_zoom = 1.0
        self._preview_zoom = max(0.55, min(2.8, self._preview_zoom + delta))
        self._preview_fit_mode = "manual"
        self.preview_zoom_var.set(f"{round(self._preview_zoom * 100):.0f}%")
        self._agendar_preview(20)

    def _definir_fit_preview(self, modo: str):
        if modo not in {"page", "width"}:
            return
        self._preview_fit_mode = modo
        self._preview_zoom = 1.0
        self.preview_zoom_var.set("Página" if modo == "page" else "Largura")
        self._agendar_preview(20)

    def _preview_mousewheel(self, evento):
        if not hasattr(self, "preview_canvas"):
            return
        delta = -1 if getattr(evento, "delta", 0) > 0 else 1
        self.preview_canvas.yview_scroll(delta * 3, "units")
        return "break"

    def _preview_ctrl_mousewheel(self, evento):
        self._zoom_preview(0.12 if getattr(evento, "delta", 0) > 0 else -0.12)
        return "break"

    def _preview_compare_drag(self, evento):
        if self.preview_modo.get() != "Comparar" or not self._preview_image_bbox:
            self.preview_canvas.focus_set()
            return
        x, _y, largura, _altura = self._preview_image_bbox
        canvas_x = self.preview_canvas.canvasx(evento.x)
        ratio = (canvas_x - x) / max(largura, 1)
        ratio = max(0.08, min(0.92, ratio))
        if abs(ratio - self._preview_compare_ratio) >= 0.01:
            self._preview_compare_ratio = ratio
            self._agendar_preview(35)
        self.preview_canvas.focus_set()
        return "break"

    def _iniciar_preview(self):
        self._preview_after_id = None
        if fitz is None or Image is None or ImageTk is None:
            self._mostrar_placeholder_preview("Prévia indisponível sem Pillow e PyMuPDF.")
            return
        if not self.caminho_pasta or not self.pdfs_encontrados:
            self._mostrar_placeholder_preview("Selecione uma pasta com PDFs para visualizar o documento.")
            return

        pdf = self._preview_pdf if self._preview_pdf in self.pdfs_encontrados else self.pdfs_encontrados[0]
        self._preview_pdf = pdf
        try:
            config = self._capturar_config()
        except Exception:
            return

        modo = self.preview_modo.get()
        largura = max(260, self.preview_canvas.winfo_width() - 38)
        altura = max(260, self.preview_canvas.winfo_height() - 38)
        pagina_indice = max(0, self._preview_page_index)
        fit_mode = self._preview_fit_mode
        zoom = self._preview_zoom
        compare_ratio = self._preview_compare_ratio
        self._preview_seq += 1
        seq = self._preview_seq

        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            max(160, self.preview_canvas.winfo_width()/2),
            max(130, self.preview_canvas.winfo_height()/2),
            text="Renderizando página…", fill=COR_TEXTO_3,
            font=(FONTE_UI, 9),
        )

        def worker():
            doc = None
            try:
                doc = fitz.open(str(pdf))
                if doc.page_count == 0 or getattr(doc, "needs_pass", False):
                    raise RuntimeError("PDF sem página acessível para prévia")
                total = doc.page_count
                indice = min(pagina_indice, total - 1)
                pagina = doc.load_page(indice)
                # Render acima da resolução de tela para manter o zoom nítido.
                pix = pagina.get_pixmap(
                    matrix=fitz.Matrix(2.05, 2.05),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                original = _imagem_do_pixmap(pix)
                resultado = aplicar_filtros_imagem(original.copy(), config)

                if modo == "Original":
                    composta = original
                    resultado.close()
                elif modo == "Resultado":
                    composta = resultado
                    original.close()
                else:
                    composta = original.copy()
                    meio = int(composta.width * compare_ratio)
                    direita = resultado.crop((meio, 0, resultado.width, resultado.height))
                    composta.paste(direita, (meio, 0))
                    direita.close()
                    draw = ImageDraw.Draw(composta)
                    draw.line((meio, 0, meio, composta.height), fill=(170, 184, 255), width=4)
                    original.close()
                    resultado.close()

                page_scale = min(largura / max(composta.width, 1), altura / max(composta.height, 1))
                if fit_mode == "width":
                    escala = largura / max(composta.width, 1)
                elif fit_mode == "manual":
                    escala = page_scale * zoom
                else:
                    escala = page_scale
                escala = max(0.06, min(2.8, escala))
                novo_tam = (
                    max(1, int(composta.width * escala)),
                    max(1, int(composta.height * escala)),
                )
                if novo_tam != composta.size:
                    exibida = composta.resize(novo_tam, Image.Resampling.LANCZOS)
                    composta.close()
                else:
                    exibida = composta

                self._ui(
                    lambda img=exibida, q=seq, nome=pdf.name, m=modo,
                           i=indice, t=total, fm=fit_mode:
                    self._aplicar_preview(img, q, nome, m, i, t, fm)
                )
            except Exception as exc:
                self._ui(lambda q=seq, e=str(exc): self._falha_preview(q, e))
            finally:
                try:
                    if doc is not None:
                        doc.close()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _aplicar_preview(self, img: Image.Image, seq: int, nome: str, modo: str,
                         pagina_indice: int, total_paginas: int, fit_mode: str):
        if seq != self._preview_seq or not self.winfo_exists():
            try:
                img.close()
            except Exception:
                pass
            return
        try:
            self._preview_page_index = pagina_indice
            self._preview_total_pages = total_paginas
            self.preview_page_var.set(f"{pagina_indice + 1} / {total_paginas}")
            self._atualizar_estado_navegacao_preview()

            self._preview_photo = ImageTk.PhotoImage(img)
            self.preview_canvas.delete("all")
            cw = max(1, self.preview_canvas.winfo_width())
            ch = max(1, self.preview_canvas.winfo_height())
            pad = 22
            content_w = max(cw, img.width + pad * 2)
            content_h = max(ch, img.height + pad * 2)
            x = max(pad, (content_w - img.width) / 2)
            y = max(pad, (content_h - img.height) / 2)

            # Sombra curta para destacar a página sobre o viewer.
            self.preview_canvas.create_rectangle(
                x + 5, y + 7, x + img.width + 5, y + img.height + 7,
                fill="#030405", outline="",
            )
            self.preview_canvas.create_image(x, y, image=self._preview_photo, anchor="nw")
            self.preview_canvas.create_rectangle(
                x - 1, y - 1, x + img.width + 1, y + img.height + 1,
                outline="#353B46", width=1,
            )

            self._preview_image_bbox = (x, y, img.width, img.height)

            if modo == "Comparar":
                meio = x + img.width * self._preview_compare_ratio
                self.preview_canvas.create_line(
                    meio, y, meio, y + img.height,
                    fill=COR_ACENTO, width=2,
                )
                self.preview_canvas.create_rectangle(
                    x + 10, y + 10, x + 78, y + 32,
                    fill="#0B0D11", outline="#323844",
                )
                self.preview_canvas.create_text(
                    x + 44, y + 21, text="ORIGINAL", fill=COR_TEXTO_2,
                    font=(FONTE_UI, 7, "bold"),
                )
                self.preview_canvas.create_rectangle(
                    x + img.width - 88, y + 10, x + img.width - 10, y + 32,
                    fill="#151A27", outline=COR_ACENTO_SUAVE,
                )
                self.preview_canvas.create_text(
                    x + img.width - 49, y + 21, text="RESULTADO", fill=COR_ACENTO_HOVER,
                    font=(FONTE_UI, 7, "bold"),
                )

            self.preview_canvas.configure(scrollregion=(0, 0, content_w, content_h))
            if content_w > cw:
                self.preview_canvas.xview_moveto(max(0, (content_w - cw) / 2 / content_w))
            else:
                self.preview_canvas.xview_moveto(0)
            if content_h > ch and fit_mode == "manual":
                self.preview_canvas.yview_moveto(max(0, (content_h - ch) / 2 / content_h))
            else:
                self.preview_canvas.yview_moveto(0)

            self.preview_info.configure(
                text=f"{nome}  ·  página {pagina_indice + 1} de {total_paginas}  ·  {modo}"
            )
        finally:
            try:
                img.close()
            except Exception:
                pass

    def _falha_preview(self, seq: int, erro: str):
        if seq != self._preview_seq:
            return
        self._preview_total_pages = 0
        self._preview_photo = None
        self._mostrar_placeholder_preview(f"Não foi possível gerar a prévia.\n{erro}")
        self.preview_info.configure(text="Os ajustes continuam disponíveis; a falha afeta apenas a prévia.")

    def _ao_selecionar_pdf(self, _evento=None):
        if not hasattr(self, "tree"):
            return
        selecao = self.tree.selection()
        if not selecao:
            return
        iid = selecao[0]
        for pdf, item_id in self._tree_iids.items():
            if item_id == iid:
                self._preview_pdf = pdf
                self._preview_page_index = 0
                self._preview_total_pages = 0
                self._preview_fit_mode = "page"
                self._preview_zoom = 1.0
                self.preview_zoom_var.set("Página")
                self._agendar_preview(60)
                break

    def _abrir_pdf_selecionado(self, _evento=None):
        selecao = self.tree.selection() if hasattr(self, "tree") else ()
        if not selecao:
            return
        iid = selecao[0]
        for pdf, item_id in self._tree_iids.items():
            if item_id == iid:
                try:
                    abrir_no_gerenciador(pdf)
                except Exception as exc:
                    messagebox.showerror(APP_NOME, f"Não foi possível abrir o PDF:\n{exc}")
                break

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    def _aplicar_preset(self, nome: str):
        if nome == "Personalizado":
            self.preset.set("Personalizado")
            self._agendar_salvar_preferencias()
            return
        dados = PRESETS.get(nome)
        if not dados:
            return
        self.dpi.set(dados["dpi"])
        self.cutoff.set(dados["cutoff"])
        self.brilho.set(dados["brilho"])
        self.contraste.set(dados["contraste"])
        self.nitidez.set(dados["nitidez"])
        self.qualidade.set(dados["qualidade"])
        self.preset.set(nome)
        self._agendar_preview(80)
        self._agendar_salvar_preferencias()

    def _detectar_preset_atual(self):
        atual = {
            "dpi": int(self.dpi.get()),
            "cutoff": float(self.cutoff.get()),
            "brilho": float(self.brilho.get()),
            "contraste": float(self.contraste.get()),
            "nitidez": float(self.nitidez.get()),
            "qualidade": int(self.qualidade.get()),
        }
        encontrado = "Personalizado"
        for nome, dados in PRESETS.items():
            if (
                atual["dpi"] == dados["dpi"]
                and abs(atual["cutoff"] - dados["cutoff"]) < 1e-6
                and abs(atual["brilho"] - dados["brilho"]) < 1e-6
                and abs(atual["contraste"] - dados["contraste"]) < 1e-6
                and abs(atual["nitidez"] - dados["nitidez"]) < 1e-6
                and atual["qualidade"] == dados["qualidade"]
            ):
                encontrado = nome
                break
        if self.preset.get() != encontrado:
            self.preset.set(encontrado)

    def _configurar_persistencia(self):
        for variavel in (self.dpi, self.cutoff, self.brilho, self.contraste, self.nitidez, self.qualidade):
            variavel.trace_add("write", self._ao_parametro_alterado)
        for variavel in (self.recursivo, self.sobrescrever, self.preview_modo, self.preset):
            variavel.trace_add("write", lambda *_: self._agendar_salvar_preferencias())

    def _ao_parametro_alterado(self, *_):
        if not self._persistencia_pronta:
            return
        self.after_idle(self._detectar_preset_atual)
        self._agendar_salvar_preferencias()

    def _opcao_arquivo_alterada(self):
        self._reexaminar_se_possivel()
        self._agendar_salvar_preferencias()

    def _dados_preferencias(self) -> dict:
        return {
            "version": CONFIG_VERSION,
            "preset": self.preset.get(),
            "dpi": int(self.dpi.get()),
            "cutoff": float(self.cutoff.get()),
            "brilho": float(self.brilho.get()),
            "contraste": float(self.contraste.get()),
            "nitidez": float(self.nitidez.get()),
            "qualidade": int(self.qualidade.get()),
            "recursivo": bool(self.recursivo.get()),
            "sobrescrever": bool(self.sobrescrever.get()),
            "preview_modo": self.preview_modo.get(),
            "origem": str(self.caminho_pasta) if self.caminho_pasta else None,
            "saida_custom": str(self.caminho_saida_custom) if self.caminho_saida_custom else None,
        }

    def _agendar_salvar_preferencias(self, atraso: int = 250):
        if not self._persistencia_pronta:
            return
        if self._salvar_preferencias_after is not None:
            try:
                self.after_cancel(self._salvar_preferencias_after)
            except tk.TclError:
                pass
        self._salvar_preferencias_after = self.after(atraso, self._salvar_preferencias_agora)

    def _salvar_preferencias_agora(self):
        self._salvar_preferencias_after = None
        try:
            salvar_preferencias(self._dados_preferencias())
        except OSError as exc:
            self._log(f"Aviso: não foi possível salvar as preferências: {exc}")

    def _capturar_config(self) -> ConfigProcessamento:
        if not self.caminho_pasta:
            raise ValueError("Nenhuma pasta selecionada.")
        saida = self.caminho_saida_custom or (self.caminho_pasta / PASTA_SAIDA_NOME)
        return ConfigProcessamento(
            origem=self.caminho_pasta,
            saida=saida,
            dpi=max(72, int(self.dpi.get())),
            cutoff=max(0.0, min(10.0, float(self.cutoff.get()))),
            brilho=max(0.1, float(self.brilho.get())),
            contraste=max(0.1, float(self.contraste.get())),
            nitidez=max(0.0, float(self.nitidez.get())),
            qualidade=max(40, min(100, int(self.qualidade.get()))),
            recursivo=bool(self.recursivo.get()),
            sobrescrever=bool(self.sobrescrever.get()),
        )

    # ------------------------------------------------------------------
    # Arquivos
    # ------------------------------------------------------------------
    def selecionar_pasta(self):
        if self.processando:
            messagebox.showwarning(APP_NOME, "Cancele o processamento antes de trocar a pasta.")
            return
        pasta = filedialog.askdirectory(title="Selecione a pasta com os PDFs")
        if not pasta:
            return
        self.caminho_pasta = Path(pasta).resolve()
        self.caminho_saida_custom = None
        self.pasta_selecionada.set(str(self.caminho_pasta))
        self.saida_selecionada.set(str(self.caminho_pasta / PASTA_SAIDA_NOME))
        self.ultima_saida = self.caminho_pasta / PASTA_SAIDA_NOME
        self._preview_page_index = 0
        self._preview_total_pages = 0
        self.examinar_pasta()
        self._log(f"Pasta selecionada: {self.caminho_pasta}", limpar=True)
        self._agendar_salvar_preferencias()
        self.mostrar_pagina("pasta")

    def selecionar_pasta_saida(self):
        if self.processando:
            messagebox.showwarning(APP_NOME, "Cancele o processamento antes de trocar o destino.")
            return
        if not self.caminho_pasta:
            messagebox.showinfo(APP_NOME, "Escolha primeiro a pasta de origem.")
            return
        pasta = filedialog.askdirectory(
            title="Selecione a pasta de destino",
            initialdir=str(self.caminho_saida_custom or self.caminho_pasta),
        )
        if not pasta:
            return
        destino = Path(pasta).resolve()
        if destino == self.caminho_pasta.resolve():
            messagebox.showwarning(
                APP_NOME,
                "A pasta de destino não pode ser a mesma pasta de origem.\n\n"
                "Escolha outra pasta ou use o destino padrão 'Umbra - Resultados'.",
            )
            return
        self.caminho_saida_custom = destino
        self.ultima_saida = destino
        self.saida_selecionada.set(str(destino))
        self.examinar_pasta()
        self._agendar_salvar_preferencias()

    def restaurar_pasta_saida(self):
        if not self.caminho_pasta:
            return
        self.caminho_saida_custom = None
        destino = self.caminho_pasta / PASTA_SAIDA_NOME
        self.ultima_saida = destino
        self.saida_selecionada.set(str(destino))
        self.examinar_pasta()
        self._agendar_salvar_preferencias()

    def _reexaminar_se_possivel(self):
        if self.caminho_pasta and not self.processando:
            self.examinar_pasta()

    def _iterar_pdfs(self, config: ConfigProcessamento) -> Iterable[Path]:
        iterator = config.origem.rglob("*") if config.recursivo else config.origem.iterdir()
        saida_resolvida = config.saida.resolve()
        for caminho in iterator:
            try:
                if not caminho.is_file() or caminho.suffix.lower() != ".pdf":
                    continue
                resolvido = caminho.resolve()
                if resolvido == saida_resolvida or saida_resolvida in resolvido.parents:
                    continue
                yield caminho
            except OSError:
                continue

    def _destino_para(self, pdf: Path, config: ConfigProcessamento) -> Path:
        if config.recursivo:
            relativo = pdf.relative_to(config.origem)
            return config.saida / relativo
        return config.saida / pdf.name

    def examinar_pasta(self):
        if not self.caminho_pasta:
            return
        try:
            config = self._capturar_config()
            pdfs = sorted(self._iterar_pdfs(config), key=lambda p: str(p).lower())
        except Exception as exc:
            messagebox.showerror(APP_NOME, f"Não foi possível ler a pasta:\n{exc}")
            return

        self.pdfs_encontrados = pdfs
        existentes = 0
        for pdf in pdfs:
            if self._destino_para(pdf, config).exists():
                existentes += 1
        pendentes = len(pdfs) - existentes
        selecionados = len(pdfs) if config.sobrescrever else pendentes

        self.total_var.set(str(len(pdfs)))
        self.pendentes_var.set(str(pendentes))
        self.prontos_var.set(str(existentes))
        self._popular_tree(config)
        if self._preview_pdf not in pdfs:
            self._preview_pdf = pdfs[0] if pdfs else None
        if hasattr(self, "botao_processar"):
            if not pdfs:
                texto_cta = "Processar PDFs"
                estado_cta = "disabled"
            elif selecionados > 0:
                texto_cta = f"Processar {selecionados} PDF" + ("s" if selecionados != 1 else "")
                estado_cta = "disabled" if self.processando else "normal"
            else:
                # Todos já têm saída: não bloqueie o usuário. O clique explícito
                # em "Reprocessar" autoriza substituir esses resultados.
                texto_cta = f"Reprocessar {len(pdfs)} PDF" + ("s" if len(pdfs) != 1 else "")
                estado_cta = "disabled" if self.processando else "normal"
            self.botao_processar.configure(text=texto_cta, state=estado_cta)

        if not pdfs:
            self._set_status("Sem PDFs", "Nenhum PDF encontrado nessa pasta", COR_ALERTA)
        elif pendentes == 0 and not config.sobrescrever:
            self._set_status(
                "Pronto para reprocessar",
                f"Os {len(pdfs)} arquivo(s) já têm resultado; você pode processá-los novamente",
                COR_SUCESSO,
            )
        elif config.sobrescrever and existentes:
            self._set_status(
                "Pronto",
                f"{len(pdfs)} arquivo(s) selecionado(s) · {existentes} serão reprocessado(s)",
                COR_TEXTO_2,
            )
        else:
            self._set_status(
                "Pronto",
                f"{pendentes} pendente(s) de {len(pdfs)} arquivo(s)",
                COR_TEXTO_2,
            )
        self._agendar_preview(80)

    def _popular_tree(self, config: ConfigProcessamento):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._tree_iids.clear()

        for indice, pdf in enumerate(self.pdfs_encontrados):
            if indice >= MAX_ITENS_LISTA:
                break
            try:
                tamanho = formatar_tamanho(pdf.stat().st_size)
            except OSError:
                tamanho = "—"
            destino = self._destino_para(pdf, config)
            if destino.exists():
                status = "Reprocessar" if config.sobrescrever else "Pronto"
            else:
                status = "Pendente"
            try:
                nome = str(pdf.relative_to(config.origem))
            except ValueError:
                nome = pdf.name
            tag = "pronto" if status in {"Pronto", "Reprocessar"} else "pendente"
            iid = self.tree.insert("", "end", values=(nome, tamanho, status), tags=(tag,))
            self._tree_iids[pdf] = iid

        if len(self.pdfs_encontrados) > MAX_ITENS_LISTA:
            self.tree.insert(
                "", "end",
                values=(f"… {len(self.pdfs_encontrados) - MAX_ITENS_LISTA} arquivo(s) não exibido(s)", "", ""),
            )

    def _atualizar_status_arquivo(self, pdf: Path, status: str):
        def atualizar():
            iid = self._tree_iids.get(pdf)
            if iid and self.tree.exists(iid):
                valores = list(self.tree.item(iid, "values"))
                if len(valores) >= 3:
                    valores[2] = status
                    mapa_tags = {
                        "Pendente": "pendente",
                        "Pronto": "pronto",
                        "Reprocessar": "pronto",
                        "Concluído": "pronto",
                        "Processando": "processando",
                        "Erro": "erro",
                        "Cancelado": "cancelado",
                    }
                    self.tree.item(iid, values=valores, tags=(mapa_tags.get(status, "pendente"),))
        self._ui(atualizar)

    # ------------------------------------------------------------------
    # Processamento
    # ------------------------------------------------------------------
    def iniciar_processamento(self):
        if self.processando:
            return
        if fitz is None or Image is None:
            messagebox.showerror(
                "Dependências faltando",
                "Instale as bibliotecas necessárias:\n\npip install pillow PyMuPDF",
            )
            return
        if not self.caminho_pasta:
            messagebox.showwarning(APP_NOME, "Selecione uma pasta com PDFs primeiro.")
            self.mostrar_pagina("pasta")
            return

        self.examinar_pasta()
        config = self._capturar_config()
        if not self.pdfs_encontrados:
            messagebox.showinfo(APP_NOME, "Nenhum PDF foi encontrado nessa pasta.")
            return

        pdfs = [
            p for p in self.pdfs_encontrados
            if config.sobrescrever or not self._destino_para(p, config).exists()
        ]
        # Se todos já possuem resultado e o usuário clicou explicitamente em
        # Reprocessar, inclua todos e autorize a substituição apenas nesta execução.
        reprocessamento_explicito = not pdfs and bool(self.pdfs_encontrados)
        if reprocessamento_explicito:
            pdfs = list(self.pdfs_encontrados)
            config = replace(config, sobrescrever=True)
            self._log("Reprocessamento explícito: resultados existentes serão substituídos.", limpar=True)

        self.processando = True
        self._cancelar_event.clear()
        self.ultima_saida = config.saida
        self.botao_processar.configure(state="disabled")
        self.botao_cancelar.configure(state="normal")
        self.botao_selecionar.configure(state="disabled")
        self.barra_progresso.configure(value=0)
        self.barra_pagina.configure(value=0)
        self.progresso_texto_var.set("0%")
        self.progresso_pagina_var.set("Página —")
        self._set_status("Processando", f"0 de {len(pdfs)} arquivos", COR_ACENTO)
        inicio_log = f"Encontrados {len(self.pdfs_encontrados)} PDF(s); {len(pdfs)} entrarão no lote."
        if reprocessamento_explicito:
            inicio_log += "\nTodos já tinham resultado; reprocessamento autorizado pelo botão Reprocessar."
        self._log(inicio_log, limpar=True)
        self.mostrar_pagina("processar")

        self._thread = threading.Thread(
            target=self._processar_em_lote,
            args=(pdfs, config),
            daemon=True,
        )
        self._thread.start()

    def cancelar_processamento(self):
        if not self.processando:
            return
        self._cancelar_event.set()
        self.botao_cancelar.configure(state="disabled")
        self._set_status("Cancelando", "Finalizando a página atual com segurança…", COR_ALERTA)
        self._log("Solicitação de cancelamento recebida.")

    def _processar_em_lote(self, pdfs: list[Path], config: ConfigProcessamento):
        sucesso = 0
        falhas = 0
        cancelado = False
        total = len(pdfs)

        config.saida.mkdir(parents=True, exist_ok=True)

        for indice, pdf in enumerate(pdfs, start=1):
            if self._cancelar_event.is_set():
                cancelado = True
                break

            destino = self._destino_para(pdf, config)
            self._atualizar_status_arquivo(pdf, "Processando")
            self._ui(lambda p=pdf, i=indice: self.arquivo_atual_var.set(f"{i}/{total}  {p.name}"))
            self._ui(lambda i=indice: self.status_detalhe_var.set(f"Arquivo {i} de {total}"))
            self._log(f"[{indice}/{total}] {pdf.name}")

            try:
                def pagina_callback(atual: int, paginas: int):
                    self._ui(lambda a=atual, t=paginas, i=indice: self._atualizar_progresso(i, total, a, t))

                processar_pdf(
                    pdf,
                    destino,
                    config,
                    self._cancelar_event,
                    self._log,
                    pagina_callback,
                )
                sucesso += 1
                self._atualizar_status_arquivo(pdf, "Concluído")
            except ProcessamentoCancelado:
                cancelado = True
                self._atualizar_status_arquivo(pdf, "Cancelado")
                self._log("    cancelado antes de concluir o arquivo")
                break
            except Exception as exc:
                falhas += 1
                self._atualizar_status_arquivo(pdf, "Erro")
                self._log(f"    ERRO: {exc}")
                traceback.print_exc()

            # Garante avanço do arquivo mesmo se não houver callback de página.
            self._ui(lambda i=indice: self._atualizar_progresso(i, total, 1, 1))

        ignorados = len(self.pdfs_encontrados) - total
        self._ui(lambda: self._finalizar_processamento(sucesso, falhas, ignorados, cancelado, config))

    def _atualizar_progresso(self, indice_arquivo: int, total_arquivos: int, pagina: int, total_paginas: int):
        fracao_pagina = pagina / max(total_paginas, 1)
        progresso = ((indice_arquivo - 1) + fracao_pagina) / max(total_arquivos, 1) * 100
        progresso = max(0.0, min(100.0, progresso))
        self.barra_progresso.configure(value=progresso)
        self.progresso_texto_var.set(f"{progresso:.0f}%")
        progresso_pagina = max(0.0, min(100.0, pagina / max(total_paginas, 1) * 100))
        self.barra_pagina.configure(value=progresso_pagina)
        self.progresso_pagina_var.set(f"Página {pagina}/{total_paginas}")
        self.status_detalhe_var.set(
            f"Arquivo {indice_arquivo}/{total_arquivos} · página {pagina}/{total_paginas}"
        )

    def _finalizar_processamento(self, sucesso: int, falhas: int, ignorados: int,
                                 cancelado: bool, config: ConfigProcessamento):
        self.processando = False
        self.botao_processar.configure(state="normal")
        self.botao_cancelar.configure(state="disabled")
        self.botao_selecionar.configure(state="normal")

        self.resumo_resultado_var.set(
            f"{sucesso} processado(s) · {falhas} erro(s) · saída em {config.saida}"
        )
        self.ultima_saida = config.saida
        # Atualiza contadores e a lista primeiro; depois restaura o estado final
        # para que a varredura não troque "Concluído" por "Pronto".
        self.examinar_pasta()

        if cancelado:
            self._set_status("Cancelado", f"{sucesso} concluído(s), {falhas} erro(s)", COR_ALERTA)
            self.arquivo_atual_var.set("Processamento cancelado")
            self._log(f"\nCancelado: {sucesso} concluído(s), {falhas} erro(s).")
        else:
            self.barra_progresso.configure(value=100)
            self.barra_pagina.configure(value=100)
            self.progresso_texto_var.set("100%")
            self.progresso_pagina_var.set("Concluído")
            cor = COR_SUCESSO if falhas == 0 else COR_ALERTA
            self._set_status("Concluído", f"{sucesso} concluído(s), {falhas} erro(s)", cor)
            self.arquivo_atual_var.set("Lote finalizado")
            self._log(f"\nConcluído: {sucesso} processado(s), {falhas} com erro, {ignorados} já existente(s).")

        if not cancelado:
            messagebox.showinfo(
                APP_NOME,
                f"Processamento finalizado.\n\nConcluídos: {sucesso}\nErros: {falhas}\n\nSaída:\n{config.saida}",
            )

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def copiar_log(self):
        if not hasattr(self, "texto_log"):
            return
        try:
            texto = self.texto_log.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.update_idletasks()
            self._set_status("Log copiado", "Conteúdo enviado para a área de transferência", COR_SUCESSO)
        except tk.TclError:
            pass

    def abrir_pasta_saida(self):
        pasta = self.ultima_saida
        if pasta is None and self.caminho_pasta:
            pasta = self.caminho_pasta / PASTA_SAIDA_NOME
        if pasta is None:
            messagebox.showinfo(APP_NOME, "Selecione uma pasta primeiro.")
            return
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            abrir_no_gerenciador(pasta)
        except Exception as exc:
            messagebox.showerror(APP_NOME, f"Não foi possível abrir a pasta:\n{exc}")

    def _ui(self, callback: Callable[[], None]):
        """Agenda trabalho de UI sem chamar Tcl a partir de threads secundárias."""
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except tk.TclError:
                pass
            return
        self._ui_queue.put(callback)

    def _drenar_ui_queue(self):
        try:
            for _ in range(120):
                try:
                    callback = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    callback()
                except tk.TclError:
                    pass
                except Exception:
                    traceback.print_exc()
            if self.winfo_exists():
                self.after(30, self._drenar_ui_queue)
        except tk.TclError:
            pass

    def _log(self, mensagem: str, limpar: bool = False):
        def atualizar():
            if not hasattr(self, "texto_log") or not self.texto_log.winfo_exists():
                return
            self.texto_log.configure(state="normal")
            if limpar:
                self.texto_log.delete("1.0", "end")
            if mensagem:
                self.texto_log.insert("end", mensagem + "\n")
            try:
                linhas = int(float(self.texto_log.index("end-1c").split(".")[0]))
                if linhas > MAX_LINHAS_LOG:
                    self.texto_log.delete("1.0", f"{linhas - MAX_LINHAS_LOG}.0")
            except Exception:
                pass
            self.texto_log.see("end")
            self.texto_log.configure(state="disabled")
        self._ui(atualizar)

    def _cancelar_callbacks_agendados(self):
        """Cancela callbacks Tcl/Tk pendentes antes de destruir a janela."""
        try:
            ids = self.tk.call("after", "info")
            if isinstance(ids, str):
                ids = self.tk.splitlist(ids)
            for after_id in ids:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _ao_fechar(self):
        if self.processando:
            resposta = messagebox.askyesno(
                APP_NOME,
                "Há um processamento em andamento. Cancelar e fechar o aplicativo?",
            )
            if not resposta:
                return
            self._cancelar_event.set()
        try:
            salvar_preferencias(self._dados_preferencias())
        except OSError:
            pass
        if sys.platform.startswith("win") and getattr(self, "_hicon_handles", None):
            try:
                import ctypes
                for handle in self._hicon_handles:
                    try:
                        ctypes.windll.user32.DestroyIcon(handle)
                    except Exception:
                        pass
            except Exception:
                pass
            self._hicon_handles.clear()
        self._cancelar_callbacks_agendados()
        self.destroy()


if __name__ == "__main__":
    app = UmbraPDFApp()
    app.mainloop()