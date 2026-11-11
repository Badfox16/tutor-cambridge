# tutor-cambridge

Harness local (marker + tutor + painel) para Cambridge IGCSE Physics 0625,
com modelos rodando via Ollama e dataset/notas vindas do **Marking Lab**
(`../marking-lab-server/`). Python 3.11+ (stdlib), sem build step no front.

## Estado (marcos)

- [x] **M0** Reconhecimento do Lab: `docs/marking-lab-contract.md`, `docs/lab-issues.md`, fixtures em `tests/fixtures/`.
- [x] **M1** Esqueleto: `tutor/{config,db,lab,llm,trace,server}.py`, servidor em `TUTOR_PORT` (8780), SQLite em `data/tutor.db`, métricas do Ollama em `llm.py`; testes com Ollama/Lab falsos (`tests/`).
- [x] **M2** Marker: `tutor/{render,parse,marker}.py`, run completa contra o Lab (limit 20 com `qwen3.5:9b`: 0 parse failures, acordo 55%, bias −1.2); perfis em `profiles.toml`.
- [ ] M3 painel v1 · [ ] M4 backend do tutor · [ ] M5 UI do aluno · [ ] M6 evals · [ ] M7 acabamento

## Como rodar

```bash
cp .env.example .env      # preencha MARKING_KEY (chave msk_... do Lab; nunca commitada)
python3 -m tutor.server   # http://localhost:8780  (aluno em /student/, painel em /dashboard/)
python3 -m unittest discover -s tests -t .   # suíte offline (fakes, sem Ollama/Lab reais)
```

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
