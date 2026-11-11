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

---

*Próximas entradas entram acima desta linha, com a comparação run vs. run.*
