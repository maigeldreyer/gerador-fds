# Gerador de FDS — ABNT NBR 14725:2023

Sistema para classificar misturas químicas (líquidos e sólidos
pulverulentos) por **cálculo determinístico** — sem uso de IA na decisão
de classificação — e apoiar a elaboração da FDS (Ficha de Dados de
Segurança) conforme a ABNT NBR 14725:2023.

Uso pessoal / privado. Este repositório **não inclui** os arquivos de
dados de origem (ver abaixo o motivo e como obtê-los).

Existem duas versões equivalentes do motor/API, uma em Python e uma em
PHP — a versão em PHP foi portada depois, por preferência pessoal, e
tem paridade numérica confirmada com a versão Python (mesmos casos de
teste, mesma saída). Use a que preferir; não é necessário rodar as duas.

## Estrutura — versão Python

| Arquivo | Função |
|---|---|
| `gerador-fds.html` | Tela de entrada (perfil de empresa, produto, composição, campos opcionais), publicada como artifact e/ou aberta via `api_local.py` / `php/index.php`. |
| `api_local.py` | Servidor Flask local: `POST /api/classificar` (só a classificação), `POST /api/gerar_fds` (classificação + FDS completa em PDF) e `/api/perfis` (CRUD de perfis de empresa); serve a tela em `/`. |
| `banco_substancias.py` | Banco de dados local (SQLite) das substâncias — importação do Anexo VI da ECHA, cadastro manual, resolução de múltiplas linhas por CAS. |
| `motor_toxicidade_aguda.py` | Motor de cálculo — toxicidade aguda (NBR 5.3.1, Tabelas 16/17). |
| `motor_corrosao_irritacao.py` | Motor de cálculo — corrosão/irritação à pele e lesão ocular (NBR 5.3.2/5.3.3, Tabelas 20/21/24/25). |
| `dados_fds.json` | Biblioteca de dados compartilhada entre as versões Python e PHP: textos dos códigos H/P e mapeamentos categoria→H / H→P. |
| `gerador_fds.py` | Monta as 16 seções da FDS (frases padrão + rótulo GHS derivado dos cálculos) e gera o PDF final (layout Fosfeed/Safeeds, via `reportlab`). |
| `perfis_empresa.py` | Armazenamento local (JSON) dos perfis de empresa reaproveitáveis (Seção 1 da FDS). |
| `pubchem_enriquecimento.py` | Enriquecimento opcional via PubChem, só para substâncias sem dado no Anexo VI (nunca sobrescreve dado da ECHA). |
| `teste_visual.py` | Teste funcional (Playwright) do fluxo completo tela → API → motores. |

## Estrutura — versão PHP (`php/`)

| Arquivo | Função |
|---|---|
| `php/index.php` | Front controller: serve `gerador-fds.html` em `/` e expõe `POST /api/classificar`, `POST /api/gerar_fds` e `/api/perfis`. Equivalente a `api_local.py`. |
| `php/BancoSubstancias.php` | Mesma lógica de `banco_substancias.py` (schema SQLite via PDO, importação do Anexo VI via PhpSpreadsheet, resolução de múltiplas linhas por CAS). |
| `php/MotorToxicidadeAguda.php` | Equivalente a `motor_toxicidade_aguda.py`. |
| `php/MotorCorrosaoIrritacao.php` | Equivalente a `motor_corrosao_irritacao.py`. |
| `php/GeradorFds.php` | Equivalente a `gerador_fds.py` — monta as 16 seções e gera o PDF via `dompdf/dompdf` (HTML → PDF). |
| `php/PerfisEmpresa.php` | Equivalente a `perfis_empresa.py`. |
| `php/composer.json` | Dependências: `phpoffice/phpspreadsheet` (leitura do `.xlsx` do Anexo VI) e `dompdf/dompdf` (geração do PDF da FDS). |

> A versão PHP não inclui um equivalente a `pubchem_enriquecimento.py`
> nem a `teste_visual.py` — o enriquecimento via PubChem continua opcional
> e pouco usado; se quiser esse módulo em PHP também, é só pedir.
>
> **Sobre `php/GeradorFds.php`:** a montagem dos dados das 16 seções
> (`montarDadosFds`, `derivarRotuloGhs` etc.) foi testada normalmente
> (`php GeradorFds.php`) e tem paridade confirmada com a versão Python. A
> função `gerarPdfFds()` (que depende do `dompdf/dompdf` via Composer) não
> pôde ser testada no ambiente onde este código foi escrito, porque esse
> ambiente não tinha acesso ao Packagist (mesma limitação já documentada
> para `phpoffice/phpspreadsheet` ao portar o importador do Anexo VI) —
> rode `composer install` e teste com `php GeradorFds.php` na sua máquina
> antes de usar em produção. Se aparecer algum erro, me avise com a
> mensagem completa.

## Geração da FDS completa em PDF (16 seções)

Além de calcular a classificação, o sistema monta a Ficha de Dados de
Segurança completa (as 16 seções exigidas pela ABNT NBR 14725:2023) e
gera um PDF pronto para uso, no layout de duas colunas rótulo/valor
(mesmo estilo de fichas como a do Fosfeed/Safeeds).

**O que é calculado vs. o que é preenchido:**
- Seções 2 e 11 (perigos e informações toxicológicas): só mostram as
  classes de perigo que o motor realmente calcula hoje — toxicidade
  aguda e corrosão/irritação à pele e olhos. Frases H/P e pictogramas são
  derivados automaticamente dessas categorias.
- Seções 4 a 8, 10, 12, 13 e 15 (primeiros socorros, combate a incêndio,
  vazamento, manuseio/armazenamento, EPI, estabilidade/reatividade,
  informações ecológicas, destinação final, regulamentações): usam
  **frases padrão**, ajustadas pela severidade calculada (corrosivo/
  irritante/nenhum), que você pode complementar com os "Dados adicionais"
  da tela.
- Seção 9 (propriedades físico-químicas) e 14 (transporte): são campos
  manuais opcionais — o que não for preenchido aparece como "Não
  disponível" / "Não classificado". O sistema nunca inventa um dado de
  ensaio.
- Seção 3 (composição): mostra a classificação intrínseca de cada
  matéria-prima (a que já está no Anexo VI/banco), separada do resultado
  calculado da mistura. Substâncias marcadas como segredo industrial têm
  nome e CAS ocultados.

**Perfis de empresa:** os dados do fornecedor (Seção 1) ficam salvos como
perfis reaproveitáveis (`perfis_empresa.json` / `php/perfis_empresa.json`
— arquivo local, fora do controle de versão), para você não precisar
redigitá-los a cada produto.

Na tela, use o botão **"Gerar FDS em PDF"** (ao lado de "Calcular
classificação") para baixar o documento completo.

## Por que os dados não estão no repositório

Dois arquivos alimentam o sistema e **não são código seu**:

1. **ABNT NBR 14725:2023** (PDF comprado) — usado só como referência para
   extrair valores técnicos (tabelas, fórmulas, limites) para dentro do
   código. O texto da norma em si tem direitos autorais da ABNT e não
   pode ser redistribuído — nem o PDF, nem uma extração de texto dele.

2. **Anexo VI da ECHA** (`annex_vi_clp_table_atp23_en.xlsx`) — a própria
   planilha "unofficial" que a ECHA disponibiliza traz o aviso: *"this
   document should be treated only for informative purposes not
   including commercial activities or reproduction."* Por precaução, o
   arquivo (e o `substancias.db` gerado a partir dele) fica de fora do
   controle de versão, mesmo em repositório privado — o ideal é que cada
   máquina baixe a versão mais atual direto da fonte oficial.

O `.gitignore` já exclui `*.pdf`, `annex_vi_*.xlsx`, `nbr_full.txt` e
`*.db`.

## Como preparar os dados (uma vez por máquina)

1. **Baixe o Anexo VI (CLP Table 3.1)** direto do site da ECHA:
   https://echa.europa.eu/information-on-chemicals/annex-vi-to-clp
   (procure a planilha "unofficial" mais recente — ATP em vigor).
   Salve como `annex_vi_clp_table_atp23_en.xlsx` (ou ajuste o nome no
   comando abaixo) na raiz do projeto.

2. **Tenha a cópia da ABNT NBR 14725:2023** (PDF comprado) disponível
   localmente, se quiser conferir/ajustar algum valor no futuro. Não é
   necessário para rodar o sistema no dia a dia — os valores já estão
   embutidos em `motor_toxicidade_aguda.py` e `motor_corrosao_irritacao.py`.

3. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Gere o banco de dados local:**
   ```bash
   python3 -c "
   from banco_substancias import BancoSubstancias
   banco = BancoSubstancias('substancias.db')
   resumo = banco.importar_anexo_vi(
       'annex_vi_clp_table_atp23_en.xlsx',
       sheet_name='ATP23',   # ajuste conforme a aba do arquivo baixado
       header_row=2,         # ajuste se o layout mudar em ATPs futuras
   )
   print(resumo)
   banco.close()
   "
   ```
   A importação é idempotente: rodar de novo (ex.: após baixar uma ATP
   mais nova) substitui só as linhas de origem `ECHA_ANEXO_VI`, sem
   afetar cadastros manuais feitos via `upsert_toxicidade_aguda()` /
   `upsert_pele_olhos()`.

## Como rodar — versão Python

```bash
python3 api_local.py
```

Abre em `http://localhost:5000` (a própria tela é servida por lá). Se a
tela estiver publicada em outro lugar (ex.: um artifact do Claude), ela
faz `fetch` para `http://localhost:5000/api/classificar` — então este
servidor precisa estar rodando localmente para o botão "Calcular
classificação e gerar FDS" funcionar.

## Como rodar — versão PHP

1. **Instale as dependências** (dentro da pasta `php/`):
   ```bash
   cd php
   composer install
   ```

2. **Copie a tela para dentro da pasta `php/`** (o `index.php` serve
   `gerador-fds.html` a partir do seu próprio diretório):
   ```bash
   cp ../gerador-fds.html .
   ```

3. **Gere o banco de dados local** a partir do Anexo VI (mesmo arquivo
   baixado da ECHA, ver seção acima — coloque-o dentro de `php/` ou
   ajuste o caminho abaixo):
   ```bash
   php -r '
   require "BancoSubstancias.php";
   $banco = new BancoSubstancias("substancias.db");
   $resumo = $banco->importarAnexoVi(
       "annex_vi_clp_table_atp23_en.xlsx",
       null,
       "ATP23",   // ajuste conforme a aba do arquivo baixado
       2          // header_row — ajuste se o layout mudar em ATPs futuras
   );
   echo json_encode($resumo, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";
   '
   ```
   Mesma idempotência da versão Python: rodar de novo substitui só as
   linhas `ECHA_ANEXO_VI`, sem afetar cadastros manuais.

4. **Suba o servidor embutido do PHP:**
   ```bash
   php -S localhost:5000 index.php
   ```
   Abre em `http://localhost:5000`, com o mesmo comportamento da versão
   Python (mesma URL, mesmo formato de resposta JSON) — então qualquer
   uma das duas serve para a tela publicada funcionar.

   Se preferir hospedar num servidor de verdade (Apache/Nginx +
   PHP-FPM) em vez do servidor embutido, aponte o document root para a
   pasta `php/` e garanta que todas as requisições passem por
   `index.php` (num Apache, um `.htaccess` simples com
   `FallbackResource /index.php` resolve isso; num Nginx,
   `try_files $uri /index.php;`).

## Limitações atuais (por escolha, não por esquecimento)

- Classificação só por **cálculo** (método aditivo/tabelas da norma) —
  sem uso de dados de ensaio da própria mistura, princípios de
  extrapolação ("bridging"), nem classificação assistida por IA.
- Hoje cobre **toxicidade aguda** e **corrosão/irritação à
  pele e olhos**. Outras classes de perigo (CMR, toxicidade em órgão-alvo,
  perigo ao ambiente aquático etc.) ainda não foram implementadas.
- Produtos considerados: apenas líquidos e sólidos pulverulentos (nunca
  gases) — a via inalatória usa sempre "vapor" ou "poeira/névoa",
  conforme o campo "Estado físico do produto" informado na tela.
- Quando uma substância tem mais de uma linha no Anexo VI para o mesmo
  CAS (faixa de concentração própria ou variante de forma física) e a
  concentração informada não permite identificar com segurança qual
  linha se aplica, o sistema usa a classificação **mais severa** entre
  as candidatas e emite um aviso explícito pedindo confirmação manual —
  nunca escolhe silenciosamente a mais branda.
