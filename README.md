# tutor-cambridge

Harness local (marker + tutor + painel) para Cambridge IGCSE Physics 0625,
com modelos rodando via Ollama e dataset/notas vindas do **Marking Lab**
(`../marking-lab-server/`). Python 3.11+ (stdlib), sem build step no front.

## Estado (marcos)

- [x] **M0** Reconhecimento do Lab: `docs/marking-lab-contract.md`, `docs/lab-issues.md`, fixtures em `tests/fixtures/`.
- [x] **M1** Esqueleto: `tutor/{config,db,lab,llm,trace,server}.py`, servidor em `TUTOR_PORT` (8780), SQLite em `data/tutor.db`, métricas do Ollama em `llm.py`; testes com Ollama/Lab falsos (`tests/`).
- [x] **M2** Marker: `tutor/{render,parse,marker}.py`, run completa contra o Lab (limit 20 com `qwen3.5:9b`: 0 parse failures, acordo 55%, bias −1.2); perfis em `profiles.toml`.
- [x] **M3** Painel v1: abas Visão geral, Acurácia, Etapas, Desempenho, Confiabilidade e Explorador de traces (`static/dashboard/`, JS puro + SVG); API de stats em `tutor/stats.py`; exportação CSV/JSON.
- [x] **M4** Backend do tutor: sessões, escada de pistas (níveis 0–3), marking interno, leak check determinístico + regeneração + fallback, streaming NDJSON, cache de questões; **teste de contrato garante que nenhuma rota do aluno devolve scheme**. UI do aluno vem no M5.
- [x] **M5** UI do aluno (`static/student/`, JS puro): seleção de questão, resposta por parte, feedback em streaming, escada de pistas visível, Tentar de novo / Dar outra pista / Mostrar solução / 👍👎, marks ocultas por padrão (aparecem no nível 3 ou quando acerta).
- [ ] M6 evals · [ ] M7 acabamento

## Como rodar

```bash
cp .env.example .env      # preencha MARKING_KEY (chave msk_... do Lab; nunca commitada)
python3 -m tutor.server   # http://localhost:8780  (aluno em /student/, painel em /dashboard/)
python3 -m unittest discover -s tests -t .   # suíte offline (fakes, sem Ollama/Lab reais)
```

### Painel (`/dashboard/`)

Filtros por run e modelo no cabeçalho; abas:

| Aba | O que mostra |
|---|---|
| **Visão geral** | Ollama/Lab no ar, modelo carregado (+VRAM), contagens e taxa de sucesso, runs recentes |
| **Acurácia** | Score do Lab (acordo total/linha/ponto, MAE, bias com leitura guiada), lista de discordâncias com link para o trace |
| **Etapas** | Tempo médio por stage, barra empilhada, p50/p95 e % de falhas |
| **Desempenho** | tokens/s, TTFT, load cold vs. warm, tokens de prompt/geração, thinking, histograma de latência |
| **Confiabilidade** | Parse failures com motivo, cortes por max_tokens, falhas por etapa |
| **Traces** | Lista filtrável; clique abre prompt, resposta crua, parse e cascata de spans |

Toda porcentagem vem com o tamanho da amostra (n). Exportação: `/api/export?run_id=N&format=csv|json`.

### Diário de experimentos

`docs/experiment-log.md` registra **o que mudou, por quê, o resultado e a conclusão**
de cada passo, com legenda do que cada parâmetro (`model`, `prompt`, `think`,
`temperature`, `num_ctx`, `max_tokens`, `keep_alive`, `repeats`, `limit`) controla
e das métricas. Toda mudança de perfil deve virar uma entrada lá.

## Marker (corrigir respostas contra o mark scheme)

```bash
python3 -m tutor.marker run                          # perfil [default] do profiles.toml
python3 -m tutor.marker run --profile gemma-fast     # troca de modelo sem tocar em código
python3 -m tutor.marker run --profile default --model qwen3.5:9b --prompt marker-full --think on --limit 20
python3 -m tutor.marker run --repeats 2              # consistência entre repeats
```

### Perfis (`profiles.toml`)

Cada perfil define `model` (tag exata do Ollama), `prompt` (variante em
`tutor/prompts/`), `think`, `temperature`, `num_ctx`, `max_tokens`,
`keep_alive`, `repeats` e `limit` (0 = todas). Todo perfil herda `[default]`;
qualquer flag da CLI sobrepõe o perfil. Ao experimentar, mude **uma coisa por
vez** (modelo OU prompt OU think) e anote no `notes` da run.

`/api/health` mostra Ollama, modelo carregado e o datasetVersion do Lab.

## UI do aluno (`/student/`)

JS puro (ES module, sem build). Seleciona questão → responde por parte →
feedback em streaming com a escada de pistas visível ("tentativa N · pista
nível K"). Botões: **Tentar de novo**, **Dar outra pista** (adianta o nível),
**Mostrar solução** (com confirmação) e 👍/👎. As marks por parte ficam ocultas
por padrão e aparecem no nível 3 ou quando a resposta fica toda correta.

## Tutor (modo socrático; scheme nunca sai do backend)

O aluno responde uma questão e recebe feedback por streaming, com escada de
pistas: tentativa 1 → nível 0 (pergunta-guia), 2 → 1 (aponta a ideia/fórmula),
3 → 2 (passo a passo sem o último passo), 4/"Mostrar solução" → 3 (solução
completa). "Dar outra pista" adianta um nível. Um leak check determinístico
(`tutor/leak.py`) bloqueia vazamento do scheme: valor final A1, n-grama de 6
palavras copiado, ou a linha "MARK SCHEME" → 1 regeneração → fallback
pré-escrito. Rotas: `/api/questions`, `POST /api/sessions`,
`POST /api/sessions/{id}/answer|reveal|hint`, `POST /api/turns/{id}/rating`.
A UI do aluno (`/student/`) entra no M5.

### Lab online (para as runs de avaliação final)

Além do Lab local (`npm run dev`), existe um Lab online com mais questões:
`http://102.202.45.215:3000`. Para usá-lo, descomente as linhas do fim de
`.env.example` e ponha a chave `msk_...` **desse** servidor. Runs feitas lá
contam para a avaliação final do projeto: mantenha a higiene de experimento
(split `open`, uma mudança por vez, `notes` na run).

## Configuração (variáveis de ambiente / .env)

| Var | Default | O que é |
|---|---|---|
| `MARKING_BASE` | `http://localhost:3000` | Marking Lab |
| `MARKING_KEY` | — | chave `msk_...` pessoal (não commitar) |
| `OLLAMA_BASE` | `http://localhost:11434` | Ollama |
| `TUTOR_MODEL` | `qwen3.5:9b` | modelo ativo |
| `TUTOR_PORT` | `8780` | porta deste servidor |
| `TUTOR_NUM_CTX` | `8192` | contexto do modelo |
| `TUTOR_MAX_TOKENS` | `1024` | limite de geração |

Split usado: sempre `open` (ver `docs/marking-lab-contract.md`).
