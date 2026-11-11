# Problemas/lacunas encontrados no Marking Lab (só leitura — nada foi alterado)

## 1. Porta default errada em `scripts/llm-run.mjs`

`scripts/llm-run.mjs` linha 9: `const BASE = (process.env.MARKING_BASE || "http://localhost:3001")...`
— o servidor roda em **3000** (default do Next.js, confirmado em `npm run dev` e na documentação/README). Sem `MARKING_BASE` no ambiente, o script aponta para a porta errada.

**Impacto:** nenhum para o harness (sempre definiremos `MARKING_BASE`), mas o script falha sozinho.

## 2. Sem limite de paging em `GET /runs`

`app/api/runs/route.ts::GET` usa `findMany` sem paginação nem limite — com muitas runs a resposta cresce sem freio. Baixa prioridade (uso interno), mas vale saber para o painel.

## 3. `GET /runs` não expõe `closed` de forma filtrável

Só dá para saber se uma run está fechada buscando item a item (`GET /runs/{id}`) ou olhando o score. O painel que lista runs recentes vai fazer N chamadas extras. Lacuna menor.

## 4. `note` do score some quando `undefined`

Em `app/api/runs/[id]/score/route.ts`, a chave `note` é omitida (spread de `undefined`) quando a run open está fechada — comportamento correto, mas quem consome precisa tratar ausência da chave (não é bug, só contrato implícito).
