# tutor-cambridge

Harness local (marker + tutor + painel) para Cambridge IGCSE Physics 0625,
com modelos rodando via Ollama e dataset/notas vindas do **Marking Lab**
(`../marking-lab-server/`). Python 3.11+ (stdlib), sem build step no front.

## Estado (marcos)

- [x] **M0** Reconhecimento do Lab: `docs/marking-lab-contract.md`, `docs/lab-issues.md`, fixtures em `tests/fixtures/`.
- [x] **M1** Esqueleto: `tutor/{config,db,lab,llm,trace,server}.py`, servidor em `TUTOR_PORT` (8780), SQLite em `data/tutor.db`, métricas do Ollama em `llm.py`; testes com Ollama/Lab falsos (`tests/`).
- [ ] M2 marker · [ ] M3 painel v1 · [ ] M4 backend do tutor · [ ] M5 UI do aluno · [ ] M6 evals · [ ] M7 acabamento

## Como rodar

```bash
cp .env.example .env      # preencha MARKING_KEY (chave msk_... do Lab; nunca commitada)
python3 -m tutor.server   # http://localhost:8780  (aluno em /student/, painel em /dashboard/)
python3 -m unittest discover -s tests -t .   # suíte offline (fakes, sem Ollama/Lab reais)
```

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
