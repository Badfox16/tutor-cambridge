# Diário de experimentos — tutor-cambridge

Registro de **o que mudou, por quê, o que os resultados mostraram e se ajudou ou atrapalhou**.
Uma entrada por mudança. Regra do guia: mude **uma coisa por vez** entre runs
(modelo OU prompt OU parâmetro) e compare contra a run anterior no mesmo split (`open`).

Formato da entrada:

```
### [nº] data — o que mudou
- **Motivo:** ...
- **Comparação:** run X (antes) vs run Y (depois), mesmas demais condições
- **Resultado:** métricas
- **Conclusão:** melhorou / piorou / neutro — e o que fazer em seguida
```

Métricas de referência do Lab: sempre dar nota cheia já acerta ~39% das clear
cases (baseline a bater). Scores detalhados só existem para run **open fechada**.

---

## Legenda de parâmetros (`profiles.toml` / CLI)

| Parâmetro | Controla | Relevância | Valor atual | Quando mexer |
|---|---|---|---|---|
| `model` | A tag exata do Ollama (ex.: `qwen3.5:9b`) | Define tudo: qualidade do mark, velocidade, uso de RAM/VRAM. Um modelo de cada vez no laptop. | `qwen3.5:9b` (6.6 GB) | Primeira alavanca: trocar modelo é o maior efeito. |
| `prompt` | Variante do prompt (`tutor/prompts/*.txt`) | Modelos pequenos pioram com prompt longo; instruções ambíguas → parse failure. | `marker-compact` | Segunda alavanca, quando o modelo erra **formato** (parse) ou **critério** (bias). |
| `think` | Modo de raciocínio do modelo (`off`/`on`) | Pode melhorar julgamento, mas gera centenas de tokens extras (tempo ↑↑) e pode cortar em `max_tokens`. O thinking nunca aparece ao aluno. | `off` | Testar quando o modelo erra **julgamento** com formato OK; subir `max_tokens` junto. |
| `temperature` | Aleatoriedade da geração (0 = determinístico) | Para marcar, baixo é melhor (replicabilidade). | `0.2` | Quase nunca; 0.0 se quiser máxima consistência. |
| `num_ctx` | Janela de contexto (tokens) | Prompt do marker usa ~250 tokens; 8192 é folga grande. Contexto maior = mais RAM. | `8192` | Só se prompts crescerem muito (few-shot, tutor). |
| `max_tokens` (`num_predict`) | Teto de tokens gerados | Se a resposta exceder → corte (`finish_reason=length`) → parse failure. O reply do marker é curto (~30–40 tokens). | `1024` | Subir se ativar `think` (thinking conta no teto). |
| `keep_alive` | Tempo com o modelo carregado entre chamadas | Cold start do 9b: **~91 s**. Com o modelo quente, load ~0. | `10m` | Runs longas: subir para `30m` evita recarregar no meio. |
| `repeats` | Marca cada resposta N vezes | Mede consistência (`repeatConsistency` no score do Lab). Custo linear. | `1` | Usar ao comparar modelos com `temperature` > 0. |
| `limit` | Quantas respostas da run marcar | 0 = todas (60 no dataset v1). | `0` | Smoke tests rápidos (3–5). |

## Legenda de métricas

**Acurácia (do score do Lab, run fechada):**

| Métrica | O que é | Como ler |
|---|---|---|
| `exactTotalAgreement` | % de respostas cujo total = referência | Métrica principal do marker. Baseline a bater: 39% (sempre nota cheia). |
| `lineAgreement` | % de linhas (partes) com total = referência | Mostra onde o mark erra: por linha. |
| `pointAgreement` | % de pontos de mark que batem | Só existe quando mandamos marks por ponto (com scheme). É a granularidade fina. |
| `meanAbsError` | Média de \|nota − referência\| | Tamanho do erro, sem direção. |
| `bias` | Média de (nota − referência) | **Negativo = modelo severo demais; positivo = generoso.** O sinal diz qual instrução ajustar. |
| `parseFailures` | Respostas que o parser não conseguiu ler | Contam como errado. Cada falha tem motivo no trace. |

**Desempenho (do Ollama, por chamada):**

| Métrica | O que é | Como ler |
|---|---|---|
| `load_ms` | Cold start (carregar pesos) | ~91 s no 9b neste laptop; quente ≈ 0. |
| `prefill_ms` | Processar o prompt (antes de gerar) | Cresce com o tamanho do prompt. ~8 s neste laptop. |
| `gen_ms`, `tokens_per_s` | Geração e velocidade | ~4 tok/s no 9b aqui — hardware-bound. |
| `ttft_ms` | Tempo até o primeiro token (streaming) | O que o aluno "sente" esperar no tutor. |
| `thinking_chars` | Caracteres de raciocínio (`think=on`) | Só contagem; nunca exibido. |
| p50 / p95 | Mediana e cauda por etapa | p95 alto = outliers (ex.: cold start) puxando a experiência. |

**Etapas do pipeline (spans):** `lab.fetch` (buscar questão/scheme/resposta) →
`render` (montar prompt) → `model.load` → `model.prefill` → `model.generate` →
`parse` → `lab.submit` → (fechar run) `lab.score`. Cada falha vira span com
`ok=false` — nada é escondido.

---

## Registro

### [1] 2026-11-11 — Smoke test do Lab (sem modelo, nota cheia fake)
- **Motivo:** validar o contrato do Lab de ponta a ponta antes de gastar tempo de modelo.
- **Resultado:** loop completo OK (criar run → buscar → submeter → fechar → score). 2/3 de acordo com nota cheia.
- **Conclusão:** pipeline do Lab OK; fixtures salvas para testes offline. Nada a mudar.

### [2] 2026-11-11 — marker v1 (`marker-compact`, qwen3.5:9b, 3 respostas) — bug de merge
- **Motivo:** primeira run real do marker.
- **Resultado:** o parse "passou" mas o Lab recusou os resultados (400: *0 marks sent*). Causa: o parser lia os pontos da **questão pública** (que não traz `points`) em vez do scheme.
- **Conclusão:** **bug corrigido** — questões agora são mescladas com o scheme (`merge_scheme`) antes de render/parse. Lição: o endpoint `/questions/{id}` nunca traz pontos; sempre merge com `/scheme`.

### [3] 2026-11-11 — parser estrito vs. eco do template (mesmo modelo/prompt, 3 respostas)
- **Motivo:** após o fix [2], o modelo (`qwen3.5:9b`) respondia só `MARK b: 3 / 3` sem as linhas `b.1..b.3` (ou ecoava o template `b.1: <1>`). Parser estrito → 3/3 parse failures.
- **Comparação:** run 3 (3/3 falhas de parse) vs run 4 depois do ajuste (0/3).
- **Mudança:** (a) prompt agora diz *"Replace each `<...>` with the mark (number only)"*; (b) parser tolera valores entre colchetes (`<1>`, `[1]`) mas **rejeita** o eco do range do template (`<0-1>`).
- **Resultado:** 0 parse failures; 2/3 de acordo exato.
- **Conclusão:** **melhorou** — tolerância a formato ≠ tolerância a conteúdo. Eco literal do template continua virando parse failure (correto: não é um mark).

### [4] 2026-11-11 — aceite M2 (20 respostas, `marker-compact`, think off)
- **Motivo:** critério de aceite do marco (run de 20 no Lab).
- **Resultado:** 20/20 parseadas (0 falhas), `exactTotalAgreement` **55%**, `pointAgreement` **80%**, MAE 1.2, **bias −1.2** (severo demais), 11 discordâncias.
- **Conclusão:** formato resolvido; problema atual é **julgamento**: o modelo não concede pontos de método que a referência aceita (bias negativo forte). vs. baseline de nota-cheia (39%) estamos à frente, mas com margem clara para melhorar.
- **Próximas hipóteses (mudar uma por vez):** (a) variante `marker-full` (instruções mais explícitas sobre awarding); (b) `think=on` + `max_tokens=2048`; (c) modelo maior/diferente (ex. `gemma4:e4b`) no mesmo prompt.
- **Desempenho anotado:** cold start ~91 s; prefill ~8 s; geração ~4 tok/s (~15–20 s por resposta). Com `keep_alive=10m` as chamadas seguintes ficam quentes (load ≈ 0). Run de 20 ≈ 15,7 min.

### [5] 2026-11-11 — perfis em `profiles.toml`
- **Motivo:** facilitar a troca de modelo/parâmetros para experimentar (pedido do usuário).
- **Resultado:** CLI `--profile` + overrides; perfil, temperatura, num_ctx, think e prompt completo ficam gravados na run (SQLite + Lab).
- **Conclusão:** infraestrutura (não afeta métricas); de agora em diante toda entrada do diário cita o **perfil** usado.

### [6] 2026-11-11 — M4 backend do tutor (escada de pistas + leak check + streaming)
- **Motivo:** marco M4 — sessão do aluno com feedback socrático, sem vazar o scheme.
- **O que mudou:** `tutor/tutor.py` (pipeline de turno: marking interno → feedback → leak check → fallback), `tutor/leak.py` (3 heurísticas determinísticas, sem LLM), prompt `tutor.txt` (curto, PT), streaming NDJSON em `/api/sessions/{id}/answer` e `/reveal`; rotas `/api/questions`, `/api/sessions*`, `/api/turns/{id}/rating`; cache de questões em SQLite (`question_cache`) para funcionar offline após a 1ª busca.
- **Escada de pistas:** tentativa 1→nível 0, 2→1, 3→2, 4+/reveal→3; "dar outra pista" soma +1 (cap 3).
- **Leak check:** (a) valor final A1 do scheme no feedback com nível<3; (b) n-grama de 6 palavras copiado do scheme; (c) linha "MARK SCHEME" (qualquer nível). Vazou → 1 regeneração com instrução rígida → ainda vazou → pergunta-guia genérica pré-escrita (contabilizado em `leak_flag`/`regenerated`).
- **Teste de contrato:** suíte automatizada garante que **nenhuma** rota do aluno devolve texto de scheme (`test_contract_student.py`).
- **Ambiente:** 75 testes offline OK (fakes). Lab online anotado (`http://102.202.45.215:3000`, mais questões; runs lá contam para a avaliação final — usar só com autorização do usuário).
- **Smoke real (qwen3.5:9b, `dens-001` b, resposta correta):** marking interno `b 3/3` ✓; o 1º feedback citou "mark scheme" e o valor final → **leak check pegou ao vivo** (`leak_flag=1`, `regenerated=1`) → regeneração rígida entregou feedback limpo e socrático. Nenhum texto de scheme na rota de sessão (verificado contra o fixture).
- **Conclusão:** infraestrutura do tutor pronta; qualidade do feedback (juiz, tamanho, PT) será medida no M6.
- **Nota de higiene:** não usar schemes de questões avaliadas como exemplos few-shot do tutor.

### [7] 2026-11-11 — M5 UI do aluno
- **Motivo:** marco M5 — fluxo completo no navegador, mobile-friendly, em português.
- **O que mudou:** `static/student/{index.html,style.css,app.js}` (JS puro, ES module, sem build); leitor de NDJSON streaming com `fetch` + `ReadableStream`; marks ocultas por padrão (aparecem no nível 3 ou quando o aluno acerta); estados de erro claros ("Ollama não está respondendo").
- **Smoke real:** T1 nível 0 (`b 0/3` → pergunta-guia), `/hint` +1, T2 nível 2 com feedback socrático, 👍 gravado. 16 questões do Lab local listadas.
- **Conclusão:** fluxo completo OK; aderência a tamanho/idioma do feedback será medida no M6 (evals).
- **Nota:** fórmulas do modelo vêm com LaTeX cru (`$\rho = m/V$`) — renderizar bonito é opcional, registrar no M6 se incomodar no juiz de clareza.

### [8] 2026-11-18 — Simplificação: só o marker, Lab local, venv
- **Motivo:** o objetivo é o melhor harness de marking (o Lab é o juiz comum); tutor/painel/UI do aluno não entram na nota. Máquina limitada (MX250, 2 GB VRAM).
- **O que mudou:** pacote `harness/` com 5 módulos (config, lab, llm, prompt, run) no lugar de `tutor/` (14 módulos), sem SQLite: cada run grava `runs/<id>.json`; `python -m harness.run list` compara runs. `.venv` + `requirements.txt` (só stdlib). `.env` aponta para o Lab **local**. `limit = 5` por padrão, filtro `--question`. Cut-off agora vem do `done_reason` do Ollama. Versão anterior na tag `v0-tutor-completo`.
- **Smoke (run 7, qwen3.5:9b, marker-compact, 2 respostas):** 0 parse failures, 1/2 de acordo, 20 s/resposta, 3,7 tok/s; modelo 94% CPU / 6% GPU.
- **Observação:** a discordância (dens-001-a02) repete o padrão do [4]: o modelo tira marks de método quando a resposta final está certa, mas a referência dá todas as marks se a questão não pede "show your working". Boa hipótese para a próxima variante de prompt.

### [9] 2026-11-18 — gemma4:e4b vs qwen3.5:9b (mesmo prompt, mesmas 2 respostas)
- **Runs:** 7 (qwen) vs 8 (gemma), `marker-compact`, think off, `--limit 2` (dens-001-a01, a02).
- **Resultado:** gemma 2/2 de acordo (qwen 1/2); gemma ~10 s/resposta a quente e 8–10 tok/s vs qwen 20 s e 3,7 tok/s. Cold load do gemma: ~5 min (disco lento).
- **Conclusão:** gemma vira o padrão pela **velocidade** (confirmado). Acurácia com n=2 é ruído: confirmar com `--limit 5`+ nos dois antes de concluir algo.

### [10] 2026-11-18 — `marker-rules` vs `marker-compact` (gemma4:e4b, mesmas 12 respostas)
- **Motivo:** as 6 discordâncias da run 9 (75%) caíam em 3 padrões: C1 implícito por resposta final certa (dens-001-a06), arredondamento 13,6 → 14 (dens-003-a01), e pontos além do teto marcados 0 (therm-001/002). O `marker-rules` explica as convenções da Cambridge no prompt.
- **Comparação:** run 9 (compact) vs run 10 (rules), think off, temp 0,2.
- **Resultado:** acordo total 75% → **67%**, por ponto 72% → 68%, bias −0,42 → −0,25. Os casos-alvo **não mudaram** (dens-001-a06 e dens-003-a01 continuaram 2/3; pontos extras continuaram 0), e o modelo ficou generoso numa contradição (therm-002-a06).
- **Conclusão:** **piorou.** Um modelo de 4B não aplica regras gerais escritas no prompt. Convenções que não exigem julgamento devem ir para **código**.

### [11] 2026-11-18 — pós-processamento determinístico (`harness/post.py`) + `replay`
- **O que mudou:** regras aplicadas depois do parse (chave `post` no perfil / `--post`):
  `numeric` (A1=0 mas o último número da resposta, arredondado aos algarismos significativos do scheme, bate → A1=1; só sobe nota),
  `implied` (A1 dado → todos os C1 da parte), `sum` (total = soma dos pontos com teto, ignorando a linha MARK do modelo).
  Novo comando `python -m harness.run replay <run> --post ...`: reaproveita as saídas cruas da run salva, **sem chamar o modelo**, e submete como nova run no Lab → isola o efeito da regra.
- **Comparação:** run 9 (compact, sem post) vs run 11 (replay da 9 com `numeric,implied,sum`) — saídas do modelo idênticas.
- **Resultado:** acordo total 75% → **92%**, por parte 71% → 86%, por ponto 72% → 76%, MAE 0,42 → 0,25. Corrigiu exatamente dens-001-a06 (C1 implícito) e dens-003-a01 (13,6 ~ 14).
- **Conclusão:** **melhorou muito, custo zero de modelo.** Estratégia para modelos pequenos: o modelo julga ponto a ponto, o código faz a contabilidade da Cambridge. Discordâncias restantes: dens-002-a06 (*grey*, disputado) e pontos extras = 0 (só afetam `pointAgreement`).

### [12] 2026-11-18 — `marker-points` (compact + "julgue cada ponto sozinho, mesmo após o teto"), ambos com post
- **Comparação:** run 11 (compact+post) vs run 12 (points+post), mesmas 12, temp 0,2.
- **Resultado:** por ponto 76% → **80%**, mas acordo total 92% → **75%**. Ganhou therm-002-a01 (5/5 pontos), perdeu therm-002-a06 (contradição: deu 3, referência 1) e dens-003-a06 (*grey*, 13 600 kg/m³; mesma resposta virou de 3 para 2).
- **Conclusão:** **inconclusivo.** A instrução ajuda nos pontos extras mas deixa o modelo generoso com contradições. Com n=12 e temp 0,2, uma única virada move 8 pontos percentuais → próxima etapa: as duas variantes nas **60 respostas, temp 0**.
- **Hipótese anotada:** `numeric` poderia aceitar conversão de unidade (kg/m³ ↔ g/cm³, fator 1000) quando a unidade está escrita — regra geral da Cambridge (resposta certa em outra unidade certa), não específica da questão.

### [13] 2026-11-18 — `numeric` com conversão de unidades
- **O que mudou:** `numeric` agora lê o valor final como o aluno escreve ("13 600", "1,36 × 10⁴", "8.8 x 10^-7") e a unidade dele, e converte para a unidade do scheme (entre parênteses no A1, ou `answerLineUnit`) antes de comparar com arredondamento. Tabela de unidades por grandeza (densidade, massa, comprimento, volume, tempo, energia, potência…; temperatura fora por causa do offset). Mesmo número com unidade errada da mesma grandeza (14 kg/m³ para 14 g/cm³) ou de outra grandeza **não** ganha A1. Sem unidade → compara como escrito (como antes). Só sobe nota.
- **Bug evitado:** o leitor anterior pegava "600" de "13 600".
- **Comparação (replay, mesmas saídas do modelo):** run 9 → run 14: 92% (igual à run 11, nada regrediu). Run 12 → run 15: acordo total 75% → **83%**, por ponto 80% → 82%, bias −0,17 → −0,08; dens-003-a06 (13 600 kg/m³ = 13,6 g/cm³ ~ 14) agora certo.
- **Conclusão:** **melhorou** (regra geral da Cambridge, não específica de questão). Nota: a run de 60 do compact que estava rodando usou o `numeric` antigo; comparar com o points só depois do replay dela com o código novo.

---

*Próximas entradas entram acima desta linha, com a comparação run vs. run.*
