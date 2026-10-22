# Gerador de FDS — ABNT NBR 14725:2023

Classifica misturas químicas (líquidos e sólidos pulverulentos) por cálculo
determinístico — sem uso de IA na decisão de classificação — e gera a Ficha de
Dados de Segurança completa (16 seções) em PDF, conforme a ABNT NBR 14725:2023.

**Acesso:** https://maigeldreyer.github.io/gerador-fds/gerador-fds.html
(exige login).

Não há servidor de aplicação: cálculo, base de substâncias e geração do PDF
rodam no navegador. O único serviço externo é o de login (ver
[Login e usuários](#login-e-usuários)).

## Como usar

1. Entre com usuário e senha. Marque **"Manter conectado neste navegador"** para
   não precisar entrar de novo.
2. A base de substâncias (Anexo VI) carrega sozinha no primeiro acesso — leva
   alguns segundos. O card **"Base de dados de substâncias"** mostra quantas
   foram carregadas. Nas visitas seguintes ela já está pronta.
3. Preencha **nome**, **uso recomendado** e **estado físico** do produto.
4. Informe a **composição**: nome, **Nº CAS** (obrigatório — a classificação é
   buscada pelo CAS) e concentração no produto final. A soma precisa dar 100%.
   Marque "Segredo industrial" para ocultar nome e CAS na FDS.
5. Opcionalmente, preencha os **dados adicionais**: número da revisão, pH, dados
   de transporte (Nº ONU, classe de risco, grupo de embalagem) e regulamentações
   adicionais.
6. **"Calcular classificação"** mostra o resultado na tela; **"Gerar FDS em
   PDF"** baixa a ficha completa.

Os dados do fornecedor (Seção 1 da FDS) são preenchidos automaticamente a
partir do login.

## Onde fica cada dado

| Dado | Onde fica |
|---|---|
| Composição / fórmula do produto | Só no formulário aberto. Não é salva em lugar nenhum nem enviada para fora do navegador. |
| Dados da empresa (Seção 1) | Planilha privada no Google, lida a cada login. Não ficam neste repositório nem gravados no navegador. |
| Usuários e senhas | Mesma planilha privada (senhas guardadas só como hash). |
| Base de substâncias | `js/anexo_vi_compacto.json` neste repositório, copiada para o `IndexedDB` do navegador no primeiro acesso. |
| Sessão de login | Token em `sessionStorage` (ou `localStorage`, com "Manter conectado"). |

## Base de substâncias (Anexo VI)

A classificação de cada matéria-prima vem do Anexo VI do Regulamento CLP
(tabela de classificações harmonizadas da ECHA), já embutida no repositório:

- Arquivo: `js/anexo_vi_compacto.json` — versão **ATP23 (Reg. (UE) 2025/1222)**,
  3.857 linhas com CAS (3.823 substâncias distintas). Linhas da ECHA sem Nº CAS
  ficam de fora, porque o sistema busca tudo pelo CAS.
- Formato: `{ fonte, fonte_versao, campos: [cas, nome, ec, classificacao, h_codes], linhas: [[...], ...] }`.
- No primeiro acesso a página baixa o arquivo, processa e grava no `IndexedDB`.
  Depois só reimporta se a versão mudar.

**Para atualizar para uma ATP mais nova:**

1. Baixe a planilha "unofficial" mais recente em
   https://echa.europa.eu/information-on-chemicals/annex-vi-to-clp.
2. Gere um novo `js/anexo_vi_compacto.json` no mesmo formato (aba da ATP,
   cabeçalho na 3ª linha; colunas *CAS No*, *Chemical Name*, *EC No*,
   *Hazard Class and Category Code(s)* e *Classification Hazard Statement
   Code(s)*; descartar linhas sem CAS) e atualize `fonte_versao`.
3. Em `gerador-fds.html`, altere a constante `VERSAO_ANEXO_VI_EMBUTIDO` para o
   mesmo valor de `fonte_versao`.
4. Publique. Cada navegador reimporta a base sozinho na próxima visita; a
   reimportação substitui só as linhas de origem ECHA.

**Sobre a fonte:** a tabela "unofficial" da ECHA traz o aviso de que deve ser
usada "only for informative purposes" e não reproduzida nem usada em atividades
comerciais. Embuti-la neste repositório foi uma decisão explícita do
responsável pelo projeto, ciente desse aviso. O texto legal do Regulamento CLP
e de seus anexos é de reuso livre (Decisão 2011/833/UE); a planilha de
conveniência da ECHA especificamente não é.

## Login e usuários

O login usa um Google Apps Script publicado como App da Web, ligado a uma
planilha privada ("GeradorFDS — Login") com as abas `Usuarios`, `Acessos`,
`Auditoria`, `Config` e `Empresa`. Nem a planilha nem o código do Apps Script
estão neste repositório; `js/auth.js` só contém o endereço público do
endpoint, que não dá acesso a nada sem usuário e senha válidos.

- Senhas guardadas como hash SHA-256 com sal e várias iterações; sessões com
  token assinado (HMAC-SHA256).
- Bloqueio temporário após várias tentativas com senha errada (limite e
  duração definidos na aba `Config`).
- Administração pela própria planilha, no menu **GeradorFDS Admin**: criar
  usuário, resetar senha, desativar/reativar usuário e encerrar sessões.
- Cada usuário pode trocar a própria senha pelo botão **"Trocar senha"** na
  tela.
- Para mudar os dados do fornecedor que saem na FDS, edite a aba `Empresa` da
  planilha.

## Geração da FDS em PDF

- **Seções 2, 3 e 11** (perigos, composição, toxicologia): classes de perigo
  calculadas pelo motor — toxicidade aguda e corrosão/irritação à pele e aos
  olhos — com frases H/P e pictogramas derivados das categorias. A Seção 3
  mostra também a classificação de cada matéria-prima.
- **Seções 4 a 8, 10, 12, 13 e 15**: frases padrão ajustadas pela severidade
  calculada (corrosivo, irritante ou sem classificação).
- **Seções 9 e 14** (propriedades físico-químicas e transporte): só o que for
  preenchido na tela (pH, Nº ONU, classe de risco, grupo de embalagem). O
  restante, incluindo cor e odor, sai como "Não disponível" — o sistema nunca
  inventa dado de ensaio.

## Estrutura do repositório

| Arquivo | Função |
|---|---|
| `gerador-fds.html` | Tela única: login, produto, composição, dados adicionais, cálculo e geração do PDF. Também dispara a carga automática da base. |
| `js/auth.js` | Cliente de login/sessão e leitura dos dados da empresa (fala com o Apps Script). |
| `js/bancoSubstancias.js` | Banco de substâncias em `IndexedDB`: importação do Anexo VI, resolução de múltiplas linhas por CAS e ponte com os motores. |
| `js/anexo_vi_compacto.json` | Base do Anexo VI (ECHA) embutida. |
| `js/motorToxicidadeAguda.js` | Motor de cálculo — toxicidade aguda (NBR 5.3.1, Tabelas 16/17). |
| `js/motorCorrosaoIrritacao.js` | Motor de cálculo — corrosão/irritação à pele e lesão ocular (NBR 5.3.2/5.3.3, Tabelas 20/21/24/25). |
| `js/geradorFds.js` | Monta as 16 seções e gera o PDF (jsPDF + jspdf-autotable). |
| `js/pubchemEnriquecimento.js` | Consulta opcional à PubChem para substâncias sem dado no Anexo VI. Existe no código, mas não está ligada à tela. |
| `data/dados_fds.json` | Textos das frases H/P e mapeamentos categoria→H e H→P. |
| `tests/teste_motores.mjs`, `tests/teste_edge.mjs` | Testes de regressão dos dois motores (Node, sem navegador): `node tests/teste_motores.mjs`. |

Bibliotecas externas, carregadas por CDN em versões fixas: `jspdf@2.5.2`,
`jspdf-autotable@3.8.2` e `xlsx@0.18.5` (esta última só é usada pelo
importador de planilha `.xlsx`, que continua no código mas não aparece na tela).
O login e a geração do PDF exigem internet.

Mudanças enviadas a este repositório aparecem no site depois do build do
GitHub Pages (aba **Actions**, "pages build and deployment", ~1 min) e do
cache do CDN (até 10 min).

### Rodar localmente

A página usa módulos ES, que o navegador bloqueia quando o arquivo é aberto
direto do disco (`file://`). Sirva a pasta com qualquer servidor estático:

```bash
python3 -m http.server 8000
# abra http://localhost:8000/gerador-fds.html
```

## O que não vai para o repositório

- **ABNT NBR 14725:2023** (PDF comprado): usada só como referência para os
  valores técnicos do código. O texto da norma tem direitos autorais da ABNT —
  não adicione o PDF nem extrações de texto dele.
- **Planilha de login e código do Apps Script**: ficam só na conta Google do
  responsável.

## Limitações atuais

- Classificação só por cálculo (método aditivo e tabelas da norma) — sem dados
  de ensaio da própria mistura, princípios de extrapolação ("bridging") ou IA.
- Cobre toxicidade aguda e corrosão/irritação à pele e aos olhos. Outras classes
  (CMR, toxicidade para órgãos-alvo, perigo ao ambiente aquático etc.) ainda não
  foram implementadas.
- Apenas líquidos e sólidos pulverulentos (nunca gases): a via inalatória usa
  "vapor" ou "poeira/névoa", conforme o estado físico informado.
- Quando o Anexo VI tem mais de uma linha para o mesmo CAS e a concentração não
  permite saber qual se aplica, o sistema usa a classificação mais severa e
  emite um aviso pedindo confirmação manual — nunca escolhe a mais branda em
  silêncio.
