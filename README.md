# Índice Composto de Risco Bancário (ICR) — dados públicos do BCB

Código de apoio ao TCC *"Índice Composto de Risco Bancário a partir de dados
públicos do Banco Central do Brasil"* (eEDB-007 / USP).

Pipeline de ponta a ponta: coleta indicadores do **IF.Data**, padroniza por
trimestre, combina num **Índice Composto de Risco (ICR)** inspirado no
**CAMELS**, resolve os **nomes** das instituições e valida contra séries
macroeconômicas do **SGS**. Dados 100% abertos.

> **Status:** funcional e testado com dados reais — **36 trimestres
> (2016T1–2024T4)**, ~1.500 instituições por trimestre.

---

## Correspondência entre a monografia e o código

| Monografia | Script | Principais saídas (`data/processed/`) |
|---|---|---|
| Seções 3.1–3.2 (coleta e painéis) | `01_coletar.py` | `data/raw/<painel>/*.parquet` |
| Seções 3.3–3.4 (indicadores e ICR) | `02_construir_icr.py` | `<painel>/indicadores.parquet`, `<painel>/icr.parquet` |
| Seções 4.2–4.4 e 4.6 (validação e explicabilidade) | `03_validar_explicar.py`, `07_grandes_com_basileia.py` | `<painel>/correlacao_macro.csv`, `<painel>/importancia_indicadores.csv` |
| Seção 4.5 (mercado de capitais) | `04_validar_acoes.py` | `validacao_acoes.csv` |
| Seções 3.5–3.6 e 4.7 (modelo de alerta precoce) | `06_modelo_distress.py` | `distress_metricas.csv`, `distress_avaliacao.csv`, `distress_sensibilidade.csv`, `distress_shap.csv`, `distress_tuning.csv` |
| Tabela 10 e limiar de Youden (Seção 4.7); Seção 5.5 | `10_analises_complementares.py` | `comparacao_classificadores.csv`, `distress_limiar_youden.csv`, `ews2025_oot.csv` |
| Capítulo 5 (ICR 2.0, IFRS 9) | `09_icr2_ifrs9.py` | `icr2_ifrs9.parquet`, `validacao_reforma.csv`, `icr2_metricas.csv`, `icr2_sensibilidade.csv`, `importancia_modelos.csv` |
| Auditoria do pipeline | `08_diagnostico.py` | saída no terminal |

Os dados brutos e processados **não** são versionados (ver `.gitignore`): todo o
conteúdo de `data/` e `figuras/` é regenerado pelos scripts a partir das APIs
públicas do Banco Central e da B3. Como as APIs podem ser revisadas pelo BCB, uma
nova coleta pode produzir diferenças pequenas em relação aos números publicados.

**Divisão temporal do modelo de alerta precoce:** treino 2016T1–2020T3 (17.772
obs.), embargo 2020T4–2021T3, teste 2021T4–2023T4 (7.295 obs.).

---

## 1. Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

python scripts/01_coletar.py          # IF.Data (2 painéis, rel. 1,2,4) + nomes + SGS
python scripts/02_construir_icr.py    # indicadores CAMELS + ICR + ranking (por painel)
python scripts/03_validar_explicar.py # validação temporal/macro + SHAP + comparação
python scripts/04_validar_acoes.py    # validação com ações da B3 (Yahoo Finance)
python scripts/05_exportar_relatorio.py # ranking em HTML interativo + Excel
python scripts/06_modelo_distress.py  # EWS: prevê distress (out-of-time) + watchlist
python scripts/07_grandes_com_basileia.py # grandes bancos COM Basileia (Olinda+portal)
python scripts/08_diagnostico.py      # checagens de sanidade (auditoria do pipeline)
python scripts/09_icr2_ifrs9.py       # ICR 2.0 (IFRS-9, 2025+): CAMELS completo + validação da reforma
python scripts/10_analises_complementares.py # comparação de classificadores, limiar de Youden e EWS 2025 fora do tempo
```

Análise exploratória: abra `notebooks/01_analise.ipynb`.

### Rede corporativa / erro de certificado SSL
Instale o `truststore` (já no `requirements.txt`) para usar o cert store do SO.
Último recurso em dev: `‍$env:ICR_VERIFY_SSL = 'false'`.

---

## 2. Estrutura

```
config/indicadores.yaml     # metodologia parametrizada (pesos, sinais, janela, painéis, séries, tickers)
src/icr/
  http.py        # HTTP robusto (retry + SSL p/ proxy)
  sgs.py         # cliente SGS (macro) + trimestralização
  ifdata.py      # cliente IF.Data (Olinda) + limpeza de colunas
  nomes.py       # resolução CodInst -> nome (backend de arquivos do portal)
  indicadores.py # indicadores CAMELS (rel. 1, 2 e 4)
  score.py       # z-score por trimestre + ICR
  validacao.py   # série do sistema + correlação macro
  explicabilidade.py  # decomposição exata + SHAP
  acoes.py       # cotações B3 (Yahoo) + correlação ICR x ação
  relatorio.py   # exportação HTML interativo + Excel
  distress.py    # rótulo de distress futuro + modelo EWS (split temporal)
  portal.py      # fonte complementar: Basileia dos grandes bancos (portal IF.Data)
  icr2.py        # ICR 2.0 (IFRS 9, 2025+): CAMELS completo, custo de risco (dim. A)
scripts/01..10_*.py   # 08 = diagnóstico; 09 = ICR 2.0 (IFRS 9); 10 = análises complementares

notebooks/01_analise.ipynb
notebooks/pipeline_passo_a_passo.ipynb   # pipeline completo passo a passo (11 etapas)
data/raw/<painel>/  data/processed/<painel>/  figuras/<painel>/  (+ comparações na raiz)
```

> **Multi-painel:** o pipeline roda dois painéis em paralelo (`config: paineis`):
> **prudencial** (tipo 1, com Basileia) e **sistêmico** (tipo 3, com os grandes
> bancos). Cada um gera saídas próprias; `03` ainda produz `figuras/comparacao_paineis.png`.

---

## 3. Metodologia

### 3.1 Fontes (todas validadas ao vivo) e ACHADOS importantes

| Fonte | Endpoint |
|---|---|
| IF.Data (dados) | `olinda.bcb.gov.br/.../IFDATA/.../IfDataValores` |
| IF.Data (nomes) | `www3.bcb.gov.br/ifdata/rest/arquivos?nomeArquivo=...` |
| SGS | `api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados` |

Achados de engenharia de dados (documentados no código — rendem boa discussão
metodológica na monografia):

1. **`Relatorio` é o NÚMERO** do relatório como string (`'1'`=Resumo,
   `'2'`=Ativo, `'4'`=DRE), não o nome.
2. **`TipoInstituicao` define o universo — e há um trade-off central:**
   | Tipo | Universo | Basileia? | Grandes bancos? |
   |---|---|---|---|
   | **1** Prudencial | cooperativas + bancos médios | ✅ sim | ❌ não |
   | **2** Financeiro | BNDES, fintechs | ❌ não | ❌ não |
   | **3** Individual | **todos, incl. BB/Itaú/Caixa/Bradesco/Santander** | ❌ não | ✅ sim |

   A API Olinda **não expõe os conglomerados dos 5 grandes bancos**; eles só
   aparecem como *instituição individual* (tipo 3), nível em que o BCB não
   publica o Índice de Basileia. Ou seja: **ou Basileia (tipo 1) ou os grandes
   bancos (tipo 3)** — escolha em `config: coleta.tipo_instituicao`.
3. **`IfDataCadastro` (nomes via Olinda) retorna HTTP 500.** Contornado: os
   nomes vêm do backend de arquivos do portal (`cadastro<periodo>_<tipo>.json`),
   onde `c0`=código (= `CodInst` sem zeros à esquerda) e `c2`=nome. Como nomes
   são estáveis, usamos o cadastro mais recente disponível (cobertura ~97%).
4. **SGS limita séries diárias a ~10 anos/requisição** (HTTP 406) — por isso
   usamos a Selic mensal (4390) em vez da diária (432).

### 3.2 Indicadores (CAMELS) — relatórios 1, 2 e 4

| Indicador | CAMELS | Cálculo | Relatório | Sinal |
|---|---|---|---|---|
| Basileia* | C | direto | 1 | + |
| Alavancagem | C | Ativo / PL | 1 | − |
| ROA | E | Lucro Líq. anualizado / Ativo | 1 | + |
| ROE | E | Lucro Líq. anualizado / PL | 1 | + |
| Imobilização* | M | direto | 1 | − |
| Liquidez | L | (Disponib.+Aplic.Interfin.+TVM) / Ativo | 2 | + |
| Eficiência | M | (Desp.Pessoal+Adm.) / Receita oper. | 4 | − |

\* Basileia e Imobilização só existem no **tipo 1**. No tipo 3 o ICR usa os
demais 5 indicadores (Capital representado pela alavancagem) — o código
renormaliza os pesos automaticamente conforme os indicadores disponíveis.

> Rentabilidade anualizada por `12/(mês no semestre)` — no IF.Data o resultado é
> acumulado **por semestre** (reinicia em jan/jul, balancete do COSIF): ×4 no
> 1º/3º tri., ×2 no 2º/4º tri. A Eficiência é razão de dois fluxos do mesmo
> período → sem anualização. O script `08_diagnostico.py` verifica isso
> automaticamente (checagem de sazonalidade do ROE).

### 3.3 Padronização e índice
Filtro de porte (Ativo total ≥ R$ 1 milhão; o IF.Data informa valores em reais) → winsorização (1/99%) → **z-score por
trimestre** → `ICR_i = Σ peso_j·sinal_j·z_ij` (pesos renormalizados) → zona de
risco = percentil inferior (10%). Orientação padrão `solidez` (ICR maior = mais
sólido); configurável para `risco`.

### 3.4 Validação e explicabilidade
- **Temporal:** `figuras/icr_temporal.png`, `serie_sistema.csv`.
- **Macro:** correlação ICR do sistema × SGS (`correlacao_macro.csv`).
- **Explicabilidade:** decomposição exata (`peso·z`) + SHAP sobre a zona de risco.

---

## 4. Resultados (run real, 36 trimestres 2016–2024)

- **Validação macro (painel sistêmico, n=36):** correlação **negativa** com
  spread PF (−0,82), inadimplência PJ (−0,70), spread PJ (−0,71) e inadimplência
  total (−0,62). Sistema mais sólido ⇒ menor inadimplência/spread.
- **Painel prudencial** correlaciona na mesma direção, porém mais fraco
  (inadimplência PJ −0,49; spread PF −0,48) — cooperativas/bancos médios são
  menos sensíveis à dinâmica macro sistêmica. (Bom ponto de discussão.)
- **Tendência temporal:** ambos os ICRs sobem de 2016 a 2021–24 (recuperação
  pós-recessão), com o mergulho da COVID (2020T1) visível
  (`figuras/comparacao_paineis.png`).
- **Ranking dos grandes bancos (2024T4):** BTG e Itaú no topo; Caixa e Santander
  em "Crítico" (liquidez/eficiência mais fracas).
- **Validação com ações (B3):** correlação **positiva** entre ICR e preço da
  ação em todos os 5 bancos listados (SANB11 0,52; BBAS3 0,46; BPAC11 0,38) —
  bancos mais sólidos, ações mais valorizadas (`validacao_acoes.csv`).
- **Ranking exportado:** `data/processed/ranking_ICR.html` (interativo) e
  `ranking_ICR.xlsx`.
- **EWS de distress (etapa 06):** prevê quebra de capital/prejuízo severo em até
  4 trimestres. **AUC-ROC = 0,83, KS = 0,52** out-of-time (split temporal com
  embargo de 4 trimestres), taxa-base de *distress* no teste 4,4%. ROE é o maior preditor, seguido de
  ROA e eficiência. Gera `watchlist` com as instituições de maior risco.
- **Grandes bancos COM Basileia (etapa 07):** combinando Olinda (balanço) +
  portal (Basileia prudencial via crosswalk), obtém-se o indicador de capital
  para Itaú, Bradesco, BB, Caixa, Santander, BTG, Nubank, Safra etc. no recorte
  recente (2025+). Como esse período já está sob o novo plano de contas (ver
  limitação abaixo), usa apenas indicadores estáveis (sem eficiência). Nubank no
  topo; BB, Bradesco e Caixa em "Crítico".
- **ICR 2.0 / IFRS-9 (etapa 09):** sob o plano de contas de 2025, constrói o índice
  com o **CAMELS completo** (dimensão *Asset quality* via **custo de risco**, 3º
  indicador mais influente: 15,7%). Validação em dois planos: (i) as faixas do ICR de
  2024 preveem o custo de risco realizado em 2025 (Spearman −0,28; n=1.534); (ii) o
  próprio ICR 2.0, usado como escore, prevê *distress* no trimestre seguinte com
  **AUC-ROC = 0,87** (estável 0,82–0,93 em 2025–2026). Saídas: `icr2_ifrs9.parquet`,
  `validacao_reforma.csv`, `icr2_preditividade.csv` e figuras `icr2_*`.

---

## 5. Limitações e próximos passos

0. **Reforma contábil de 2025 (Res. CMN 4.966 / IFRS 9).** A partir de 2025 o
   BCB reestruturou os relatórios de Ativo e DRE do IF.Data (modelo de perda
   esperada), renomeando/dividindo contas e mudando a definição do resultado de
   intermediação. Isso quebra a comparabilidade de **liquidez** e **eficiência**
   no limite 2024→2025. Por isso a janela padrão encerra em `202412`. O código
   já reconhece as duas convenções de TVM (liquidez), mas a eficiência tem
   quebra definicional; reconciliar os planos de contas é trabalho futuro.
1. **Trade-off Basileia × grandes bancos** (ver 3.1.2). Já contornado para os
   trimestres recentes pela etapa 07 (Olinda + portal). O endpoint do portal
   serve bem 2025+; períodos antigos seguem instáveis no servidor do BCB, então
   a série histórica COM Basileia para os grandes bancos ainda depende do BCB
   normalizar o backend antigo (ou de download manual dos CSVs do portal).
2. **Rótulo de distress (etapa 06)** usa limiares prudenciais futuros (Basileia
   < 10,5% ou ROE < −30%). Extensão natural para um EWS pleno: usar eventos
   reais de regime especial / liquidação (lista do BCB) como alvo.
3. **Eficiência em instituições minúsculas** explode quando a receita é ~0
   (fintechs). A winsorização trata isso no z-score, mas vale subir o corte de
   porte para focar em bancos de fato.
4. **Nomenclatura:** com `orientacao: solidez`, "ICR maior = mais saudável" →
   considere chamar de *Índice de Solidez* ou usar `orientacao: risco`.
