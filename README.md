# Gerador de FDS — ABNT NBR 14725:2023

Sistema para classificar misturas químicas (líquidos e sólidos pulverulentos) por
cálculo determinístico — sem uso de IA na decisão de classificação — e apoiar a
elaboração da FDS (Ficha de Dados de Segurança) conforme a ABNT NBR 14725:2023.

Uso pessoal / privado. Este repositório não inclui os arquivos de dados de origem
(ver abaixo o motivo e como obtê-los).

**Versão 100% front-end.** Todo o motor de cálculo, o banco de substâncias e a
geração do PDF da FDS rodam inteiramente no navegador — não há mais servidor
Python ou PHP. Nada do que você digita ou importa (composição, dados da empresa,
Anexo VI) sai do seu navegador: tudo fica em `IndexedDB`/`localStorage` locais.

## Estrutura

| Arquivo | Função |
|---|---|
| `gerador-fds.html` | Tela única da aplicação (perfil de empresa, produto, composição, importação do Anexo VI, cálculo e geração do PDF). |
| `js/motorToxicidadeAguda.js` | Motor de cálculo — toxicidade aguda (NBR 5.3.1, Tabelas 16/17). |
| `js/motorCorrosaoIrritacao.js` | Motor de cálculo — corrosão/irritação à pele e lesão ocular (NBR 5.3.2/5.3.3, Tabelas 20/21/24/25). |
| `js/bancoSubstancias.js` | Banco de substâncias em `IndexedDB` — importação do Anexo VI (via SheetJS), cadastro manual, resolução de múltiplas linhas por CAS. |
| `js/geradorFds.js` | Monta as 16 seções da FDS (frases padrão + rótulo GHS derivado dos cálculos) e gera o PDF final (via jsPDF + jspdf-autotable), no layout de duas colunas rótulo/valor. |
| `js/perfisEmpresa.js` | Perfis de empresa reaproveitáveis (Seção 1 da FDS), salvos em `localStorage`. |
| `js/pubchemEnriquecimento.js` | Enriquecimento opcional via PubChem (`fetch`), só para substâncias sem dado no Anexo VI — nunca sobrescreve dado da ECHA. |
| `data/dados_fds.json` | Biblioteca de dados: textos dos códigos H/P e mapeamentos categoria→H / H→P, carregada via `fetch` pela tela. |
| `tests/teste_motores.mjs`, `tests/teste_edge.mjs` | Suíte de regressão (Node, sem navegador) dos dois motores de cálculo — casos normais e de borda. Rode com `node tests/teste_motores.mjs` / `node tests/teste_edge.mjs`. |

## Como rodar

A tela usa módulos ES (`<script type="module">`), e o Chrome/Firefox/Edge
bloqueiam `import` de arquivos locais quando a página é aberta direto do disco
(`file://...`) — é uma restrição de segurança do próprio navegador, não deste
projeto. **Por isso, abra `gerador-fds.html` sempre através de um servidor**,
nunca dando duplo clique no arquivo. Duas formas simples:

**Opção 1 — servidor local (qualquer máquina com Python ou Node):**

```bash
# dentro da pasta do projeto
python3 -m http.server 8000
# ou: npx http-server -p 8000
```

Abra `http://localhost:8000/gerador-fds.html`.

**Opção 2 — GitHub Pages:** ative o GitHub Pages deste repositório (Settings →
Pages → Deploy from branch) e acesse a URL gerada. Como é um repositório
privado, o Pages também fica privado/restrito aos colaboradores (dependendo do
seu plano do GitHub).

Não é necessário instalar nada (sem `pip install`, sem `composer install`, sem
`npm install` para a aplicação em si) — os três pacotes usados (jsPDF,
jspdf-autotable, SheetJS/xlsx) são carregados via CDN (`<script>` no próprio
`gerador-fds.html`), em versões fixas:

- `jspdf@2.5.2`
- `jspdf-autotable@3.8.2`
- `xlsx@0.18.5`

Isso significa que a geração do PDF e a importação do Anexo VI exigem conexão
com a internet no navegador (para baixar esses três scripts); o resto da
aplicação (cálculo de classificação, formulário, perfis de empresa) funciona
totalmente offline depois que a página carrega.

## Como preparar os dados (uma vez por navegador)

O Anexo VI não vem embutido no código nem no repositório (ver "Por que os dados
não estão no repositório", abaixo) — você importa a planilha diretamente pela
tela:

1. Baixe o Anexo VI (CLP Table 3.1) direto do site da ECHA:
   https://echa.europa.eu/information-on-chemicals/annex-vi-to-clp (procure a
   planilha "unofficial" mais recente — ATP em vigor).
2. Na tela, na seção **"Base de dados de substâncias (Anexo VI)"**, escolha o
   arquivo `.xlsx` baixado, confirme/ajuste o número da linha de cabeçalho
   (padrão: 2) e clique em **"Importar Anexo VI"**.
3. O arquivo é lido inteiramente no navegador (via SheetJS) e as substâncias são
   gravadas no `IndexedDB` local — o `.xlsx` em si nunca é enviado a lugar
   nenhum nem salvo em disco pela aplicação.

A importação é idempotente: importar de novo (ex.: após baixar uma ATP mais
nova) substitui só as linhas de origem `ECHA_ANEXO_VI`, sem afetar nenhum
cadastro manual que você tenha feito.

O `IndexedDB` é local ao navegador/perfil/máquina — se você usar outro
navegador ou outra máquina, ou limpar os dados do site, precisará importar o
Anexo VI novamente.

## Geração da FDS completa em PDF (16 seções)

Além de calcular a classificação, o sistema monta a Ficha de Dados de
Segurança completa (as 16 seções exigidas pela ABNT NBR 14725:2023) e gera um
PDF pronto para uso, no layout de duas colunas rótulo/valor (mesmo estilo de
fichas como a do Fosfeed/Safeeds).

O que é calculado vs. o que é preenchido:

- **Seções 2 e 11** (perigos e informações toxicológicas): só mostram as
  classes de perigo que o motor realmente calcula hoje — toxicidade aguda e
  corrosão/irritação à pele e olhos. Frases H/P e pictogramas são derivados
  automaticamente dessas categorias.
- **Seções 4 a 8, 10, 12, 13 e 15** (primeiros socorros, combate a incêndio,
  vazamento, manuseio/armazenamento, EPI, estabilidade/reatividade, informações
  ecológicas, destinação final, regulamentações): usam frases padrão, ajustadas
  pela severidade calculada (corrosivo/irritante/nenhum), que você pode
  complementar com os "Dados adicionais" da tela.
- **Seção 9** (propriedades físico-químicas) e **14** (transporte): são campos
  manuais opcionais — o que não for preenchido aparece como "Não disponível" /
  "Não classificado". O sistema nunca inventa um dado de ensaio.
- **Seção 3** (composição): mostra a classificação intrínseca de cada
  matéria-prima (a que já está no Anexo VI/banco), separada do resultado
  calculado da mistura. Substâncias marcadas como segredo industrial têm nome e
  CAS ocultados.

**Perfis de empresa:** os dados do fornecedor (Seção 1) ficam salvos como
perfis reaproveitáveis no `localStorage` do navegador, para você não precisar
redigitá-los a cada produto. Como é `localStorage`, os perfis são por
navegador/máquina — não sincronizam entre dispositivos.

Na tela, use o botão **"Gerar FDS em PDF"** para baixar o documento completo.

## Por que os dados não estão no repositório

Dois arquivos alimentam o sistema e não são código seu:

- **ABNT NBR 14725:2023** (PDF comprado) — usado só como referência para
  extrair valores técnicos (tabelas, fórmulas, limites) para dentro do código.
  O texto da norma em si tem direitos autorais da ABNT e não pode ser
  redistribuído — nem o PDF, nem uma extração de texto dele.
- **Anexo VI da ECHA** (`annex_vi_clp_table_atp23_en.xlsx`) — a própria
  planilha "unofficial" que a ECHA disponibiliza traz o aviso: "this document
  should be treated only for informative purposes not including commercial
  activities or reproduction." Por precaução, nunca commite esse arquivo neste
  repositório, mesmo sendo privado — o `.gitignore` não precisa mais ignorá-lo
  explicitamente (a aplicação não grava mais esse arquivo em disco: ele só é
  lido em memória, no navegador, no momento da importação), mas a regra vale
  para você também: não adicione esse `.xlsx` nem o PDF da norma a este
  repositório.

## Limitações atuais (por escolha, não por esquecimento)

- Classificação só por cálculo (método aditivo/tabelas da norma) — sem uso de
  dados de ensaio da própria mistura, princípios de extrapolação ("bridging"),
  nem classificação assistida por IA.
- Hoje cobre toxicidade aguda e corrosão/irritação à pele e olhos. Outras
  classes de perigo (CMR, toxicidade em órgão-alvo, perigo ao ambiente aquático
  etc.) ainda não foram implementadas.
- Produtos considerados: apenas líquidos e sólidos pulverulentos (nunca gases)
  — a via inalatória usa sempre "vapor" ou "poeira/névoa", conforme o campo
  "Estado físico do produto" informado na tela.
- Quando uma substância tem mais de uma linha no Anexo VI para o mesmo CAS
  (faixa de concentração própria ou variante de forma física) e a concentração
  informada não permite identificar com segurança qual linha se aplica, o
  sistema usa a classificação mais severa entre as candidatas e emite um aviso
  explícito pedindo confirmação manual — nunca escolhe silenciosamente a mais
  branda.
- O enriquecimento via PubChem (`js/pubchemEnriquecimento.js`) depende de
  `fetch` para `pubchem.ncbi.nlm.nih.gov` a partir do navegador; se o PubChem
  bloquear CORS para chamadas diretas do navegador, essa função específica
  pode não funcionar — ela é só um complemento opcional e nunca é exigida para
  calcular a classificação.

## Histórico

Este projeto existia antes como duas versões de backend equivalentes (Python/
Flask e PHP), servindo a mesma tela `gerador-fds.html` por `fetch`. Essas
versões foram descontinuadas e substituídas por esta versão 100% front-end,
que não depende de nenhum servidor de aplicação — só de um servidor estático
qualquer (ou GitHub Pages) para contornar a restrição de `file://` dos
módulos ES.
