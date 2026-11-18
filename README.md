# tutor-cambridge

Harness de **marker** para Cambridge IGCSE Physics 0625: um modelo local (Ollama)
corrige respostas de alunos contra o mark scheme, e o **Marking Lab** dá a nota
contra a referência. Cada participante tenta a sua abordagem; o Lab é o juiz comum.

> A versão anterior (tutor socrático, painel, UI do aluno) está guardada na tag
> `v0-tutor-completo`: `git checkout v0-tutor-completo` para ver/recuperar.

## Estrutura

```
harness/
  config.py   .env + perfis (profiles.toml)
  lab.py      cliente do Marking Lab
  llm.py      chamada ao Ollama + métricas (load, prefill, tok/s, TTFT, cut-off)
  prompt.py   render do prompt + parser da resposta (mesmo layout do Lab)
  run.py      CLI: faz a run, grava runs/<id>.json, imprime o resumo
prompts/      variantes de prompt (marker-compact.txt, marker-full.txt)
profiles.toml perfis de run (modelo, prompt, think, limit...)
runs/         um JSON por run (ignorado pelo git)
tests/        testes offline (Lab e modelo falsos)
docs/         contrato do Lab, diário de experimentos
```

## Instalação

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt     # só stdlib por enquanto; o arquivo fica pronto para deps
cp .env.example .env                # ponha a chave do Lab local (../marking-lab-server/local-keys.txt)
```

## Uso

1. Suba o Lab local (outro terminal): `cd ../marking-lab-server && npm run dev`
2. Garanta o Ollama no ar: `ollama ps`
3. Rode:

```bash
python -m harness.run                                   # perfil [default], 5 respostas
python -m harness.run --limit 2 --notes "teste rápido"
python -m harness.run --question dens-001               # só uma questão
python -m harness.run --profile qwen --notes "qwen vs gemma, mesmo prompt"
python -m harness.run --prompt marker-full --notes "prompt full vs compact"
python -m harness.run list                              # tabela comparando as runs
python -m unittest discover -s tests -t .               # testes (sem Lab/Ollama)
```

Durante a run aparece uma linha por resposta (marks, segundos, tok/s, `CUT-OFF`
se bateu em `max_tokens`). No fim: acordo total / por parte / por ponto, MAE,
bias, parse failures, tempo, e cada discordância com o raciocínio da referência.
O JSON em `runs/` guarda tudo: perfil, template, prompt e resposta crua de cada
resposta, métricas e o score completo do Lab. O painel do Lab
(http://localhost:3000) também mostra as runs.

## Hardware (MX250, 2 GB de VRAM)

Modelo padrão: `gemma4:e4b` (~10 s/resposta, ~9 tok/s depois de carregado).
O `qwen3.5:9b` (perfil `qwen`) roda 94% na CPU: ~20 s/resposta, ~4 tok/s.
O primeiro carregamento de qualquer modelo demora de 1,5 a 5 min. Por isso: `limit = 5` por padrão,
`num_ctx = 4096`, `keep_alive = 10m` (evita recarregar entre respostas) e um
modelo por vez. Modelos menores (2–4B) cabem melhor na GPU e permitem iterar
mais rápido; teste-os com `--model <tag>`.

## Higiene de experimento

- Sempre `split: "open"` (o harness fixa isso).
- Uma mudança por vez (modelo **ou** prompt **ou** think), descrita em `--notes`.
- Poucas respostas = muito ruído: compare runs com o mesmo `--limit`/`--question`.
- Registre cada conclusão em `docs/experiment-log.md`.
- Lab online (`102.202.45.215`) só para a avaliação final: troque no `.env`.
