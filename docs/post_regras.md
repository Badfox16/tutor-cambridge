
# Regras de pós-processamento (`harness/post.py`)

## Por que existem

O modelo padrão (`gemma4:e4b`, ~4B parâmetros) julga bem ponto a ponto, mas
**não aplica regras gerais de marking escritas no prompt**. No experimento [10],
o prompt `marker-rules` explicava as convenções da Cambridge (C1 implícito,
arredondamento, unidades...) e o acordo **caiu** de 75% para 67%: o modelo
ignorou as regras justamente nos casos que elas deviam corrigir.

Daí a divisão de trabalho:

- **O modelo** decide o que exige julgamento: o aluno fez este ponto?
- **O código** cuida da contabilidade da Cambridge, que não exige julgamento.

As regras são **gerais** (vêm das convenções de marking da Cambridge e do texto
do scheme), nunca específicas de uma questão do dataset.

## Como usar

Chave `post` no perfil (`profiles.toml`) ou `--post` na CLI, separada por vírgulas:

    python -m harness.run --post numeric,a1check,subst,implied,sum

As regras sempre rodam nesta ordem: `numeric → a1check → subst → implied → sum`.

O comando `replay` re-marca as saídas salvas de uma run **sem chamar o modelo**.
Assim dá para medir o efeito exato de cada regra:

    python -m harness.run replay 16 --post numeric,a1check

## As regras

### `numeric` (sobe nota)

**Regra:** A1 = 0, mas o valor final do aluno, arredondado aos algarismos
significativos do scheme, é igual ao valor do A1 → A1 = 1.

- Lê o número do jeito que o aluno escreve: `13 600`, `1.36 × 10⁴`,
  `8.8 x 10^-7`, vírgula decimal (`2,4`).
- **Converte unidades** quando as duas são conhecidas: `13 600 kg/m³` = 13,6 g/cm³ ~ 14.
  A unidade do scheme vem dos parênteses do A1 (`14 (g/cm³)`) ou do `answerLineUnit`.
- O mesmo número com unidade errada (`14 kg/m³` quando o scheme pede 14 g/cm³)
  **não** ganha A1.
- Sem unidade escrita, compara o número como está.

**Por quê:** o modelo tirava o A1 de respostas certas com mais algarismos
(13,6 para 14) ou em outra unidade correta (dens-003-a01, dens-003-a06).
Na Cambridge, uma resposta mais precisa ou em unidade equivalente vale a marca.

### `a1check` (desce nota)

**Regra:** A1 = 1, mas **nenhum** número da resposta (com conversão de unidade)
bate com o valor do scheme → A1 = 0.

**Por quê:** o modelo aceitava erros de potência de dez: 0,14 ou 1,4 para 14,
89 para 8,9, 0,024 para 2,4. O A1 é a marca da resposta final correta.
A regra é generosa de propósito: basta *qualquer* número da resposta bater
para o A1 ficar, então ela só age quando o valor está claramente errado.

### `subst` (desce nota)

**Regra:** um C1 cujo texto no scheme é só uma substituição numérica
(ex.: `12 ÷ 0.88`) foi dado, o A1 não foi, e algum desses números não aparece
na resposta → C1 = 0.

**Por quê:** o modelo dava a marca de substituição com os números errados
(`12 ÷ 8.8`, `0.984 ÷ 41`, `148 ÷ 3.8`). Se o A1 está certo, a regra não age,
porque aí vale o `implied`.

### `implied` (sobe nota)

**Regra:** A1 dado → todos os C1 daquela parte são dados.

**Por quê:** na Cambridge, as marcas C são implícitas por uma resposta final
correta, mesmo sem working ou com working errado (dens-001-a06).

### `sum` (contabilidade)

**Regra:** total da parte = soma dos pontos, com teto nos marks da parte,
ignorando a linha `MARK` escrita pelo modelo.

**Por quê:** garante consistência entre pontos e total depois das outras regras.
Sozinha, teve efeito zero nas medições.

## Cuidados e bugs encontrados no caminho

- `"13 600"` era lido como `600` → separador de milhar com espaço.
- `"148/16.6"`: a barra virava parte da unidade e o 16,6 sumia → a unidade só
  começa com `/` se vier uma letra depois.
- Aluno lusófono (`98,4 / 41,0 = 2,4`): a primeira versão do `a1check` tirou
  marcas certas → vírgula decimal suportada. O caso `13,600` é ambíguo: as regras
  que sobem nota leem como milhar, as que descem consideram as duas leituras.
- O `3` de `cm3` não é tratado como número (`kg m⁻³`, `kgm-3` e `m s-1` são normalizados).
- Temperatura fica de fora da conversão (°C ↔ K tem deslocamento, não fator).
- Toda mudança de regra é checada por replay **resposta a resposta**: quais
  discordâncias foram corrigidas e se apareceu alguma nova.

## Resultado (60 respostas, split open, gemma4:e4b, temp 0)

| Prompt             | sem regras | `numeric,implied,sum` | +`a1check,subst`         |
| ------------------ | ---------- | ----------------------- | -------------------------- |
| `marker-compact` | 62%        | 68%                     | 75% (bias +0,10)           |
| `marker-points`  | 62%        | 70%                     | **78%** (bias +0,20) |

Por regra isolada (replay): `numeric` +5–6 pp, `implied` +1 pp, `sum` 0.
As regras que descem nota corrigiram 5 cálculos sem criar nenhuma discordância nova.

Com o prompt `marker-statements` (explicações), a melhor config atual chega a **82%**.

## O que as regras não resolvem

Perguntas de explicação (B1): palavra-chave solta, hesitação entre duas ideias,
ciência errada com as palavras certas. Isso é julgamento e fica com o modelo
(e com o prompt). Ver `experiment-log.md`, entradas [10]–[16].
