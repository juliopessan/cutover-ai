# Dashboard Template System

Professional dashboard template system para criar dashboards executivos reutilizáveis.

## 📦 Arquivos

- **`dashboard.template.html`** — Template HTML base com todas as seções e animações
- **`example-config.json`** — Exemplo de configuração JSON
- **`../scripts/generate_dashboard.py`** — Script Python para gerar novos dashboards

## 🚀 Como Usar

### Opção 1: Usando o Script Python (Recomendado)

```bash
# Abra um terminal na pasta do projeto
cd c:\Users\julio.cesar.d.pessan\cutover-ai

# Ative o ambiente virtual
.venv\Scripts\Activate.ps1

# Execute o script com um arquivo de configuração JSON
python scripts/generate_dashboard.py \
  --name "Meu Novo Projeto" \
  --output outputs/<projeto>/novo_dashboard.html \
  --config templates/meu-config.json
```

### Opção 2: Copiar e Editar Manualmente

1. Copie `dashboard.template.html`
2. Substitua as variáveis `{{VAR_NAME}}` pelos seus valores
3. Salve como um novo arquivo HTML

## 📝 Variáveis de Template

### Seção Meta
```
{{PAGE_TITLE}}          — Título da página no browser
{{PAGE_DESCRIPTION}}    — Meta description
{{LOADING_TEXT}}        — Texto durante o preloader
```

### Navegação
```
{{LOGO_TEXT}}           — Texto do logo (primeira parte)
{{LOGO_SUFFIX}}         — Sufixo do logo (após o ponto)
{{NAV_LINKS}}           — Links de navegação gerados automaticamente
```

### Hero Section
```
{{EYEBROW}}             — Label acima do título
{{HERO_TITLE}}          — Título principal (suporta HTML)
{{HERO_SUBTITLE}}       — Subtítulo
{{HERO_BUTTONS}}        — Botões de ação gerados automaticamente
```

### Medidor KPI
```
{{METER_TITLE}}         — Título do meter
{{METER_SUBTITLE}}      — Subtítulo
{{METER_CELLS}}         — Células KPI geradas automaticamente
```

### Conteúdo Principal
```
{{MAIN_SECTIONS}}       — Seções principais geradas automaticamente
```

### CTA Final
```
{{CTA_TITLE}}           — Título da CTA
{{CTA_SUBTITLE}}        — Subtítulo
{{CTA_LINK}}            — Link do botão
{{CTA_BUTTON_TEXT}}     — Texto do botão
```

### Footer
```
{{FOOTER_LEFT}}         — Texto esquerdo do footer
{{FOOTER_RIGHT}}        — Texto direito do footer
```

## 🎨 Design System

O template inclui:

- **Tipografia:** Space Grotesk (display), Inter (body), JetBrains Mono (code)
- **Cores:**
  - `--paper`: #FAF8F4 (fundo claro)
  - `--ink`: #121610 (texto escuro)
  - `--ember`: #FF5800 (destaque laranja)
  - `--graphite`: #3D3C39 (cinza médio)
  - `--smoke`: #8B8A86 (cinza claro)

- **Animações:** GSAP com ScrollTrigger
  - Preloader com contador (0-100%)
  - Scroll progress bar (top 3px)
  - Parallax background com orbs
  - Reveal animations ao scroll
  - Cursor glow effect
  - Stagger animations

## 📋 Exemplo de Configuração JSON

```json
{
  "page_title": "Novo Projeto | Dashboard",
  "hero_title": "Novo <span class=\"word\">Projeto</span>",
  "hero_subtitle": "Descrição do projeto",
  
  "metrics": [
    { "value": "100", "label": "Métrica 1", "emphasize": true },
    { "value": "200", "label": "Métrica 2", "emphasize": false }
  ],
  
  "sections": [
    {
      "type": "benefits",
      "title": "Benefícios",
      "items": [
        { "emoji": "⚡", "title": "Rápido", "description": "Muito rápido" }
      ]
    },
    {
      "type": "table",
      "title": "Dados",
      "columns": ["Col 1", "Col 2"],
      "rows": [["A", "B"], ["C", "D"]]
    }
  ]
}
```

## 🔧 Personalização

### Adicionar Seção Personalizada

No arquivo JSON, adicione uma nova seção em `sections`:

```json
{
  "type": "custom",
  "label": "MINHA SEÇÃO",
  "title": "Título",
  "intro": "Introdução",
  "content": "<div>Seu HTML aqui</div>"
}
```

Depois edite `scripts/generate_dashboard.py` para processar o tipo `custom`.

### Cores Personalizadas

Abra o template HTML e modifique as variáveis CSS no `:root`:

```css
:root {
  --ember: #FF5800;      /* Sua cor aqui */
  --ink: #121610;
  /* ... */
}
```

## 📱 Responsividade

O template é totalmente responsivo com breakpoints em:
- 1244px — Ajuste nav
- 920px — Hero grid
- 820px — Grid 2 colunas
- 760px — Mobile nav

## ✨ Features

- ✅ Preloader com contador animado
- ✅ Progress bar de scroll
- ✅ Navegação fixa com hide ao scroll
- ✅ Parallax background
- ✅ Reveal animations ao scroll
- ✅ Cursor glow effect
- ✅ Tabelas com hover effects
- ✅ Badges customizados
- ✅ Dark/Light sections
- ✅ CTA box com animation
- ✅ Totalmente acessível (WCAG)

## 📚 Referências

- Template inspirado em: Julio Pessan Portfolio
- Design System: Orange DNA (Avanade)
- Animations: GSAP 3.12.5

## 🤝 Suporte

Para adicionar novas funcionalidades:
1. Edite o template HTML
2. Atualize o script `generate_dashboard.py`
3. Adicione exemplos ao `example-config.json`
4. Teste com `python scripts/generate_dashboard.py`

---

**Criado em:** 2026-07-13  
**Versão:** 1.0  
**Compatibilidade:** Chrome, Firefox, Safari, Edge (últimas 2 versões)
