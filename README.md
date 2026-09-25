# Umbra PDF

**Umbra PDF** é um aplicativo desktop local para melhorar a legibilidade de PDFs escaneados em lote. Ele permite ajustar contraste, brilho, nitidez e autocontraste com pré-visualização antes/depois, mantendo o processamento no próprio computador.

## Destaques

- processamento local de PDFs, sem envio de documentos para serviços externos;
- presets **Equilibrado**, **Texto forte**, **Scan apagado** e **Leve**;
- perfil **Personalizado** quando os controles são ajustados manualmente;
- visualizador com Original / Resultado / Comparar, zoom, páginas e divisor interativo;
- reprocessamento de arquivos e pastas que já possuem resultados;
- configurações persistentes entre execuções;
- processamento em lote com cancelamento seguro e gravação atômica;
- pasta de saída padrão **Umbra - Resultados**;
- interface dark compacta com ícones próprios;
- suporte a Windows, Linux e macOS via Python.

## Instalação pelo código-fonte

Requer Python 3.10 ou superior.

```bash
python -m pip install -r requirements.txt
python umbra.py
```

## Windows

A página **Releases** disponibiliza o executável empacotado para Windows x64. Não é necessário instalar Python para executar essa versão.

## Atalhos principais

| Atalho | Ação |
| --- | --- |
| `Ctrl + O` | Selecionar pasta de origem |
| `Ctrl + Enter` | Processar / reprocessar |
| `Ctrl + Shift + O` | Abrir pasta de resultados |
| `Ctrl + roda do mouse` | Zoom no visualizador |
| `Page Up / Page Down` | Página anterior / próxima |
| `Esc` | Cancelar processamento |

## Build local no Windows

No PowerShell:

```powershell
./build.ps1
```

O executável será criado em `dist/Umbra PDF.exe`.

## Privacidade

O Umbra PDF foi projetado para funcionar localmente. O conteúdo dos PDFs não é enviado pelo aplicativo para APIs ou servidores externos.

## Versão

Versão atual: **1.0.0**.
