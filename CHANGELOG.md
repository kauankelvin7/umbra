# Changelog

## 1.0.0 — 2026-09-25

Primeira release pública do Umbra PDF.

### Interface
- identidade visual Umbra PDF e ícone próprio;
- navegação lateral compacta;
- botões, sliders, toggles e seletores personalizados;
- visualizador de PDF com zoom, navegação entre páginas e ajuste à página/largura;
- comparação Original × Resultado com divisor interativo.

### Processamento
- processamento de PDFs em lote;
- presets Equilibrado, Texto forte, Scan apagado e Leve;
- configurações persistentes e perfil Personalizado;
- reprocessamento de resultados existentes sem bloquear a pasta;
- processamento em thread com fila segura para Tkinter;
- cancelamento e gravação atômica por arquivo temporário.

### Distribuição
- build Windows x64 com PyInstaller;
- release automática com executável, ZIP portátil, pacote-fonte e hashes SHA-256.
