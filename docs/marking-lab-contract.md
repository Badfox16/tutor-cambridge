# Marking Lab — contrato do servidor (Fase 0)

> Fonte da verdade: código em `../marking-lab-server/` (Next.js 16 + Prisma 6 + SQLite).
> Docs do próprio Lab: `../marking-lab-server/docs/API.md` e `docs/DATA-FORMAT.md`.
> Swagger interativo: `http://localhost:3000/swagger`; OpenAPI: `/api/openapi.json`.
> Verificado em 2026-11-11 contra dataset version 1 (16 questões, 60 respostas abertas, 0 ocultas).

## Como subir

```bash
cd marking-lab-server
npm run setup        # primeira vez: cria prisma/dev.db, carrega data/, imprime a chave admin
npm run dev          # desenvolvimento, http://localhost:3000
# ou
npm run build && npm start
# ou Docker:
docker compose up -d --build
```

Sem `npm run setup`, todas as rotas devolvem `404 "No dataset version found. Has the database been seeded?"`.

## Autenticação

- Header: `Authorization: Bearer msk_...` (chave pessoal, criada na página **Users**; admin sai do `npm run setup` e fica em `local-keys.txt`).
- Sem chave ou chave desconhecida → `401 {"error": "Missing or unknown API key..."}`.
- Erro do servidor (inesperado) → `500 {"error": "Server error: ..."}`.
- Papéis (`role`): `maintainer` vs. demais. O papel só importa para runs `hidden` e revisões. Chaves ficam **fora do repositório** (usar `.env` local).

## Erros

Formato único: `{ "error": "...", "details": [...] }` (details é lista de mensagens em palavras). Códigos vistos no código:

| Status | Quando |
|---|---|
| 400 | validação (corpo, campos, linhas/marks inválidos, `runId` inválido, dataset não semeado) |
| 401 | chave ausente/desconhecida |
| 403 | run iniciada por outra pessoa (`POST results`, `close`) |
| 404 | run/questão/resposta inexistente, dataset sem versão |
| 409 | run fechada (`results`), retirada (`withdrawn`), já fechada (`close`) |
| 500 | erro não tratado |

## Conceitos

- **`split`**: só existem `"open"` e `"default"`... **correção: `"open"` e `"hidden"`** (`app/api/runs/route.ts`). `POST /runs` sem `split` assume `open`. `hidden` exige `role=maintainer`. **O harness usa sempre `open`.**
- **`datasetVersion`**: cada mudança de dados cria uma versão congelada (snapshot). A run fixa a versão no `POST /runs` (ou aceita `datasetVersion` no corpo); todas as leituras com `?runId=` vêm dessa versão. Se um resultado mandar `datasetVersion` diferente da run, é recusado. Versão atual: 1 (seed inicial).
- **Snapshot**: `GET /dataset/version` → `{datasetVersion, current, counts: {questions, openAnswers, hiddenAnswers}, versions[]}`.

## Endpoints (todos sob `/api`, todos com Bearer, exceto o Swagger)

### Leitura de dados

| Rota | Observações confirmadas no código |
|---|---|
| `GET /questions` | **Funciona sem `runId`** (usa a versão mais recente, split open) → responde a pergunta da seção 4.1 do guia: o tutor NÃO precisa criar run para listar questões. Filtros: `syllabusRef`, `ao`, `tier`, `totalMarks`, `runId`, `version`. Paging: `page` (default 1), `pageSize` (default 100, **máx 500**). Devolve `{datasetVersion, page, pageSize, total, questions[]}`. Questão pública: `id, topic, syllabusRef, tier, ao, totalMarks, markedMarks, stem, lines[]` (`label, text, marks, answerLineUnit, marked`) — **sem pontos do scheme**. |
| `GET /questions/{id}` | Uma questão (`?runId=` ou `?version=` fixam a versão). 404 se não existir na versão. |
| `GET /questions/{id}/scheme` | `{markedMarks, lines[]}` — só linhas marcadas, com `points[]` (`code` C1/A1/B1/M1, `type`, `marks`, `text`). Linhas não marcadas não aparecem. |
| `GET /answers` | Sem `runId`: split open da versão mais recente. Com `runId`: split da run. Filtros: `questionId`, `tag`, `source`. Paging igual a questions (máx 500). Resposta pública: `{id, questionId, source, split, tags[], lines: {label: texto}}`. **Nunca** devolve marks de referência, `label`/`intent` (o que a resposta testa) nem notas de grey/feedback. |
| `GET /answers/{id}` | Uma resposta (mesma forma pública). |
| `GET /dataset/version` | Versão atual ou `?number=N`. |

### Ciclo de run

| Rota | Detalhes |
|---|---|
| `POST /runs` | Obrigatórios: `harnessName`, `gitCommit`, `model`, `usedMarkingScheme` (bool). Opcionais: `dirty` (bool), `modelSettings` (objeto), `promptTemplate`, `notes`, `extra` (objeto), `datasetVersion`, `split` (default `open`). Validação falha o POST inteiro com 400. → `201 {runId, datasetVersion, run}`. |
| `GET /runs` | Filtros: `harness`, `model`, `usedMarkingScheme`, `datasetVersion`, `from`, `to`, `includeWithdrawn`. Sem paging (`findMany` completo). |
| `GET /runs/{id}` | Uma run. |
| `POST /runs/{id}/results` | Aceita um objeto, `{results: [...]}` ou array. **Tudo ou nada**: se qualquer item tiver problema, nada é gravado (400 com `details`). Só o dono da run (ou maintainer). |
| `POST /runs/{id}/close` | Só o dono (ou maintainer); 409 se já fechada. → `{runId, closed: true, endedAt}`. |
| `GET /runs/{id}/score` | Ver abaixo. Funciona com run aberta (só resumo) e fechada (com detalhes). |
| `POST /results/{id}/review` | Maintainer: nota do examinador para custom answer. |
| `POST /runs/{id}/withdraw` | Maintainer: retira a run com motivo. |

### Regras de validação de resultado (`lib/results.ts`, `lib/validate.ts`)

- `answerId` **xor** `customAnswer` (`{questionId, lines: {label: texto}}`) — nunca ambos, nunca nenhum.
- `answerId` deve existir no split da run.
- `repeat`: inteiro ≥ 1 (default 1). Par `(answerId, repeat)` é único na run; resultado **nunca muda** — refazer = `repeat` novo. Duplicado no mesmo lote também recusa.
- `prompt` (string não vazia) e `rawOutput` (string, pode ser vazia) obrigatórios.
- `parseFailed: true` → não pode ter `lines`; conta como errado no score.
- `lines`: objeto por **cada** linha respondida (as linhas com texto na resposta); cada `{marks?: [...], total}`:
  - `marks` opcional (harness sem scheme manda só totals), se presente: 1 valor por ponto, na ordem do scheme, inteiro `0..ponto.marks`;
  - `total`: inteiro `0..linha.marks`;
  - linha inexistente/não marcada/não pertencente à resposta → recusa.
- `usedMarkingScheme` por resultado é opcional (herda o da run).

## O que o score devolve (`lib/scoring.ts`)

```json
{
  "runId": 1, "split": "open", "closed": true, "withdrawn": false,
  "datasetVersion": 1, "answersMarked": 60, "answersInSplit": 60,
  "overall":  { "results": n, "parseFailures": n, "exactTotalAgreement": 0..1,
                "lineAgreement": .., "pointAgreement": .., "meanAbsError": .., "bias": .. },
  "clearCases": {…}, "greyCases": {…},
  "repeatConsistency": { "answersWithRepeats": n, "consistent": n, "rate": .. | null },
  "errorHistogram": [ {"bucket": "≤−3|−2|−1|0|+1|+2|≥+3|parse failed", "count": n} ],
  "custom": { "submitted": n, "examinerMarked": n, "awaitingExaminer": n, "stats": {…} },
  "detail": true,
  "byQuestion": {"dens-002": {…stats}}, "byLine": {"dens-002 (b)": {…}},
  "bySyllabusRef": {"1.4": {…}}, "byTag": {"rounding": {…}}, "bySource": {"synthetic": {…}},
  "disagreements": [ … ], "customDisagreements": [ … ], "awaiting": [ … ]
}
```

- Métricas (definem o painel de acurácia — seção 4.2 do guia):
  - `exactTotalAgreement`: fração de resultados cujo total = referência (parseFailed conta como errado);
  - `lineAgreement`: fração de linhas com total igual à referência;
  - `pointAgreement`: fração de pontos que batem (só resultados com `marks`);
  - `meanAbsError`: média |harness − referência|;
  - `bias`: média (harness − referência); negativo = severo demais.
  - `null` quando não há amostra (n=0) — o painel deve mostrar "—" e não 0%.
- Detalhe (`byQuestion`, `byLine`, `bySyllabusRef`, `byTag`, `bySource`, `disagreements`) só para **runs `open` fechadas**. Run aberta/hidden → só resumo (`detail: false`, com `note`).
- `disagreements[]`: `{resultId, answerId, questionId, custom, repeat, label, grey, greyNote, tags, parseFailed, usedMarkingScheme, harness: {total, lines, reason}, reference: {total, reason, lines}, lines: [{label, text, marks, points}], prompt, rawOutput}` — ou seja, o discordância traz o prompt e a saída crua do modelo, suficiente para o explorador de traces (link direto trace ↔ discordância por `answerId`).
- Disagreement = parseFailed, total ≠ referência, ou qualquer linha/ponto diferente (`isDisagreement`).
- `awaiting`: custom answers sem nota do examinador (ficam fora do score até review).
- Baseline do Lab: sempre dar nota cheia já acerta ~39% das clear cases (`README` do Lab).

## Impressões do smoke test (run 1, local)

Fluxo completo executado com sucesso em 2026-11-11 (script `smoke_lab.py`):
`POST /runs` (split open) → `GET /answers` → `GET /questions/{id}` + `/scheme` (3 respostas) → `POST /runs/1/results` (3 resultados, nota cheia fake) → `POST /runs/1/close` → `GET /runs/1/score`. Score consistente (2/3 exato, 1 disagreement com detalhe completo). Fixtures salvas em `tests/fixtures/smoke-open.json`.

## Respostas às perguntas da seção 4 do guia

1. **Listar questões sem run?** Sim — `GET /questions` sem `runId` funciona (versão mais recente, split open). O modo tutor lista questões direto; o cache em SQLite continua útil para offline.
2. **Score:** além de `disagreements`, devolve as 6 métricas (`exactTotalAgreement`, `lineAgreement`, `pointAgreement`, `meanAbsError`, `bias`, `parseFailures`) em 3 níveis (overall/clear/grey), histograma de erros, consistência de repeats, quebras por questão/linha/syllabus/tag/origem e custom answers. O detalhe exige run open **fechada**.
3. **Limites:** paging máx 500 itens/página (default 100); sem limite de runs, de taxa ou de tamanho de lote no código (resultados grandes devem ser fatiados por bom senso). `GET /runs` não pagina.
4. **Splits:** só `open` e `hidden`; `hidden` é exclusivo de maintainers e nunca é servido depois de fechada. **Usamos sempre `open`.**

## Discrepâncias guia ↔ realidade (levantadas ao usuário)

1. A pasta de referência `reference/` do guia (`harness.py`, `marking-rules.md`, `gemma-best.txt`, `compact-v1.txt`) **não existe** no workspace. O servidor do Lab está em `marking-lab-server/` (não `marking-lab/`).
2. `scripts/llm-run.mjs` usa `MARKING_BASE` com default `http://localhost:3001` — porta diferente do servidor real (3000). O harness não deve copiar esse default.

## Decisão registrada (2026-11-11, com o usuário)

- O modo marker é portado a partir das implementações de referência do próprio Lab: `lib/llm.ts` (`buildExaminerPrompt` + `parseMarks`) e `scripts/llm-run.mjs` (fluxo de run). As variantes de prompt (`marker-full`, `marker-compact`) nascem desse layout (`b.1: <0-1>`, `MARK b: <total> / 3`).
- `MARKING_KEY` de desenvolvimento: chave admin do `local-keys.txt` num `.env` local (fora do git).
- Modelo inicial: `qwen3.5:9b` (o único instalado no Ollama). Os demais candidatos serão puxados depois; trocar de modelo é só variável de ambiente/flag.
