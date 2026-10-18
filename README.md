# Project Arstotzka — Motor Antifraude Pix

*Grupo 20*

**Integrantes:**
- Guilherme Vicente Ramalho
- Leonardo Bonfá Schroeder

API que recebe um Pix em `POST /pix/transaction`, analisa a transação junto com o histórico, decide entre `approved`, `two_factor_required` e `rejected`, grava a análise e a devolve em `GET /pix/transaction/{id}`. Feita a partir do Base Service (Python + FastAPI + PostgreSQL), mantendo as mesmas camadas.

## Como o motor de decisão funciona

O motor combina **regras determinísticas, histórico do cliente e uma pontuação de risco**. O princípio é simples: um sinal fraco sozinho não deve incomodar o cliente, mas vários sinais juntos devem. Por isso a maioria das regras soma pontos e só poucas rejeitam sozinhas.

```
POST /pix/transaction
   │
   ▼
① Schema (JSON Schema) ── formato errado → 400, nada é gravado
   │                       data inexistente / IP inválido → 422
   ▼
② Trava o pagador ─────── Pix simultâneos do mesmo CPF/CNPJ passam um de cada vez
   │
   ▼
③ Idempotência ────────── mesmo id + mesmo conteúdo → devolve a análise original (200)
   │                       mesmo id + outro conteúdo → 409
   ▼
④ Contexto (repository) ─ 4 consultas montam o histórico: pagador, último ponto
   │                       geográfico, dispositivo e destino
   ▼
⑤ Regras (funções puras) ─ cada regra olha Pix + contexto → pontos + motivo + evidência
   │
   ▼
⑥ Decisão ────────────── eliminatória? rejected. Senão: soma → faixa
   │
   ▼
⑦ Grava fato + decisão + regras num único commit (que solta a trava) → 201
```

| Camada (Base Service) | O que faz aqui |
|---|---|
| `schemas/post_pix_transaction.json` | Contrato de entrada: campos, tipos, `amount ≥ 1`, data com fuso, CPF/CNPJ com ou sem máscara, ISPB com 8 dígitos |
| `resources/pix_transaction.py` | HTTP: 201 para análise nova, 200 para reenvio, 200 no GET |
| `controllers/pix_transaction_controller.py` | Orquestra trava → idempotência → contexto → motor → gravação → commit |
| `engine/` | O motor puro (não conhece banco nem HTTP): `policy.py` (todos os parâmetros), `rules.py`, `decision.py` |
| `repositories/pix_transaction_repository.py` | Única camada com SQL: trava, monta o histórico (`HistorySnapshot`), grava |
| `models/`, `dtos/` | Espelho das tabelas e a resposta `{key, status, metadata}` |

Rejeitar um Pix não é erro HTTP, é uma decisão de negócio: sai como 201 com `"status": "rejected"`. Toda resposta traz em `metadata` o score, a versão da política e cada regra disparada com motivo e evidência (o valor observado e o parâmetro):

```json
{
  "key": "9ee6d213-338f-4aad-9247-65cbcef96ef8",
  "status": "two_factor_required",
  "metadata": {
    "engine_version": "1.0.0",
    "policy_version": "2026-10-17.1",
    "score": 40,
    "decision": "two_factor_required",
    "decided_by": "score",
    "hard_reject": false,
    "triggered_rules": [
      {
        "rule_id": "LIM_02", "family": "LIMITE", "points": 40, "hard_reject": false,
        "reason": "Valor relevante em horário noturno (acima de R$ 1.000,00)",
        "evidence": {"amount": 150000, "local_hour": 22, "person_type": "PF", "attention_above": 100000}
      }
    ]
  }
}
```

(Resposta real para o payload de exemplo do desafio: R$ 1.500 às 22h15.)

## Regras

Valores em reais na tabela; no código tudo é comparado em **centavos**, e todos os parâmetros ficam em [`src/engine/policy.py`](src/engine/policy.py). "Acima de" = maior que; "a partir de" = maior ou igual. Contagens e somas **incluem o Pix atual**. Janelas de tempo são medidas a partir do `transaction_date` do Pix (não do relógio do servidor) e a hora noturna usa o fuso informado no payload. Quando uma regra tem várias faixas, vale só a mais severa.

### Qual histórico cada regra enxerga

| Tipo de histórico | Status que contam | Por quê |
|---|---|---|
| Tentativas (VEL_01, VEL_02, VEL_03, PRF_03, CTP_02) | Todos | Tentativa rejeitada também é sinal: é o fraudador testando |
| Movimentado (MON_01, soma do dispositivo no PRF_02) | approved + two_factor_required | Não sabemos se o 2FA foi confirmado, então assumimos que o dinheiro pode ter saído. Rejeitado não soma: o dinheiro não saiu |
| Confiança (perfil do PRF_01, dispositivo conhecido, PRF_04, CTP_03) | Só approved | Um Pix em dúvida não pode "ensinar" ao motor o que é normal |

### 1. Integridade e limites

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `INT_01` — Mesma conta | Rejeita quando origem e destino são a mesma conta. | Mesmo documento, mesma agência e mesmo número. **Eliminatória.** | Operação incompatível com uma transferência. Transferência entre contas próprias *diferentes* não cai aqui. |
| `LIM_01` — Limite por transação | Atenção acima do limite do tipo de pessoa; rejeita acima do teto. | PF: acima de R$ 5.000 → +45; acima de R$ 15.000 → **eliminatória**. PJ: acima de R$ 25.000 → +45; acima de R$ 100.000 → **eliminatória**. | Valor alto aumenta a exposição. +45 sozinho já pede 2FA: o custo de um falso positivo é só uma confirmação. Tetos diferentes porque R$ 50 mil é normal para empresa e raro para pessoa. O teto PF simula o limite configurado pelo cliente. |
| `LIM_02` — Valor noturno | Entre 20h e 5h59 (hora local do payload), atenção acima de um valor; rejeita acima do teto. | PF: acima de R$ 1.000 → +40; acima de R$ 3.000 → **eliminatória**. PJ: acima de R$ 5.000 → +35; acima de R$ 15.000 → **eliminatória**. | R$ 1.000 é o limite noturno padrão do Banco Central para pessoa física (Pix entre PFs, 20h–6h). Acima dele, o cliente precisou pedir aumento, por isso pedimos confirmação (40 = 2FA). O teto rejeita porque no sequestro relâmpago a vítima confirma o 2FA sob coação. Para PJ, +35 sozinho não chega a 2FA: noite não é prova de fraude. |

### 2. Velocity — velocidade e frequência

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `VEL_01` — Rajada | Quantidade de Pix do mesmo pagador (documento) em janelas curtas. | 3+ em 2 min → +45; 5+ em 5 min → **eliminatória**. PJ: contagens × 5 (15 e 25). | Script esvaziando a conta. Dividir a conta do bar raramente passa de 2 Pix em 2 minutos. PJ paga fornecedores em lote, por isso o multiplicador. |
| `VEL_02` — Repetição | Mesmo pagador, mesmo destino e mesmo valor. | 2ª tentativa idêntica em 120 s → +45; 3+ em 10 min → **eliminatória**. | Repetição insistente (tentando "passar"). Reenvio técnico da mesma requisição (mesmo `id`) é idempotência e não conta aqui. |
| `VEL_03` — Muitos destinos | Destinatários distintos do pagador em 10 min. | 3+ → +40; 5+ → **eliminatória**. PJ: × 5 (15 e 25). | Conta comprometida pulverizando dinheiro em várias contas laranja. |

### 3. Montante — acumulação

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `MON_01` — Volume acumulado | Soma do pagador (aprovados + 2FA + o atual) em janelas móveis. **Todas as faixas exigem 2+ Pix na janela.** | PF: acima de R$ 4.000 em 1h → +40; acima de R$ 10.000 em 24h → +45; acima de R$ 20.000 em 24h → **eliminatória**. PJ: valores × 5. | Pega o fracionamento: vários Pix pequenos que, um a um, ficam abaixo do LIM_01. A exigência de 2+ Pix evita punir duas vezes um Pix único, que já é assunto do LIM_01. O × 5 para PJ é hipótese de política, não calibração estatística. |

### 4. Perfil — comportamento do pagador

O **perfil do cliente** é calculado na hora, por documento, com os Pix **aprovados** dos últimos 30 dias: `tx_count_30d`, `total_amount_30d` e `avg_ticket = total ÷ quantidade` (veja "Modelagem de dados").

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `PRF_01` — Desvio do ticket | Compara o valor com o ticket médio do cliente. | Exige 3+ Pix no perfil e Pix a partir de R$ 1.000. Acima de 3× a média → +30; acima de 8× → +50. | Na conta invadida o perfil é o da vítima: o que denuncia é o Pix fugir do padrão *dela*. Com menos de 3 Pix não há régua confiável, e o piso de R$ 1.000 evita marcar R$ 60 de quem manda R$ 10. |
| `PRF_02` — Dispositivo novo | Dispositivo que nunca fez Pix aprovado para este pagador. | Só para quem já tem Pix aprovado. Acima de R$ 200 → +30; soma do dia nesse aparelho acima de R$ 1.000 → +45. | Alinhado à regra do Banco Central para dispositivo não cadastrado (R$ 200 por transação e R$ 1.000 por dia). Trocar de celular é legítimo, então sozinho não rejeita. Cliente sem nenhum aprovado não tem "aparelho de sempre" para comparar. |
| `PRF_03` — Dispositivo compartilhado | Documentos pagadores distintos no mesmo aparelho em 7 dias. | 2 → +30; 3+ → +45. | Um aparelho operando várias contas é típico de fazenda de contas laranja. Um casal dividindo celular dá 2 e não chega a 2FA sozinho. Nunca rejeita isoladamente. |
| `PRF_04` — Deslocamento incompatível | Velocidade entre este Pix e o último Pix aprovado do pagador com geolocalização (Haversine). | Só avalia distâncias de 100 km ou mais. Acima de 300 km/h → +45; acima de 800 km/h → +60. | Mesma conta em dois lugares longe demais em pouco tempo. O piso de 100 km evita que a imprecisão do GPS gere velocidades absurdas. A geolocalização vem do próprio aparelho e é opcional, por isso o peso é moderado. Viagem de avião pode pedir 2FA (falso positivo aceito). |
| `PRF_05` — Conta de origem recente | Idade da conta pagadora. | Menos de 3 dias e a partir de R$ 1.000 → +30; menos de 24h e acima de R$ 3.000 → +50. | Conta recém-aberta não tem histórico e é comum em cadeias de laranjas. |

### 5. Contraparte — quem recebe

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `CTP_01` — Destino recente | Idade da conta de destino combinada com o valor. | Menos de 24h e a partir de R$ 5.000 → +60; até 48h e a partir de R$ 2.000 → +45; até 7 dias e a partir de R$ 500 → +25. | Conta laranja costuma ser nova. Combinar com valor evita punir quem paga R$ 50 para alguém que acabou de abrir conta. |
| `CTP_02` — Concentração no destino | Pagadores distintos para o mesmo destino **PF** em 1h. | 5+ → +40; 10+ com conta de destino com menos de 30 dias → +60. | Conta laranja recebendo de várias vítimas. Só vale para destino PF: uma loja (PJ) recebendo de muitos clientes é o normal. Falso positivo possível: rifa ou vaquinha. |
| `CTP_03` — Destinatário conhecido (redutor) | Já houve Pix aprovado deste pagador para este destino há 24h ou mais. | −25. | Reduz atrito no recorrente, como o aluguel. A espera de 24h impede o fraudador de "fabricar" um destino conhecido em minutos. Não desfaz eliminatória. |

## Como as regras viram decisão

1. **Todas as regras rodam.** Cada uma devolve no máximo um resultado (a faixa mais severa).
2. **Eliminatória vence tudo.** Se alguma regra eliminatória disparou, o status é `rejected` (`decided_by = "hard_rule"`), mesmo com redutores. O score dos outros sinais é registrado assim mesmo.
3. **Senão, soma.** `score = max(0, soma dos pontos)`, com o CTP_03 entrando negativo.

| Score | Status | Quando |
|---|---|---|
| menor que 40 | `approved` | Nenhum sinal ou só sinais fracos isolados (ex.: celular novo numa compra de R$ 300) |
| 40 a 79 | `two_factor_required` | Um sinal médio ou dois fracos: a dúvida é resolvida pelo próprio cliente |
| 80 ou mais | `rejected` | Sinais independentes se somando |

**Quando pedir 2FA e quando rejeitar.** O 2FA protege quando quem faz o Pix *não é* o dono da conta (conta invadida): o fraudador não tem o segundo fator. No golpe (falso parente, falsa central) e no sequestro, quem confirma é o próprio dono, enganado ou coagido. Por isso os sinais de contraparte e o teto noturno precisam conseguir **rejeitar**, e não só pedir 2FA.

**Exemplos** (todos são testes automatizados; a lista completa está em [`docs/cenarios.md`](docs/cenarios.md)):

| Situação | Regras | Score | Decisão |
|---|---|---|---|
| Aluguel de R$ 2.500 para o mesmo locador | PRF_01 +30, CTP_03 −25 | 5 | approved |
| Celular novo, compra de R$ 300 | PRF_02 +30 | 30 | approved |
| Conta invadida: 23h, R$ 2.500, aparelho novo, destino aberto há 2 dias | LIM_02 +40, PRF_01 +50, PRF_02 +45, CTP_01 +45 | 180 | rejected |
| Golpe: R$ 3.000 para PF que recebeu de 6 pessoas na última hora | PRF_01 +50, CTP_01 +25, CTP_02 +40 | 115 | rejected |
| Sequestro relâmpago: 23h, R$ 5.000 | LIM_02 eliminatória | — | rejected |
| Fracionamento: 3º Pix de R$ 1.900 na mesma hora | MON_01 +40 | 40 | 2FA |
| Script: 5º Pix em 3 min, cada um para um destino | VEL_01 e VEL_03 eliminatórias | — | rejected |

## Modelagem de dados

Três tabelas, todas **imutáveis** (triggers bloqueiam UPDATE e DELETE), separando o fato do julgamento. O schema está em [`database/database.sql`](database/database.sql).

| Tabela | O que guarda | Por quê |
|---|---|---|
| `pix_transaction` | O fato: cada campo do payload numa coluna, `raw_payload` (jsonb) e `payload_hash` (SHA-256). Colunas geradas: tipo de pessoa (PF/PJ) e chaves de conta. | As regras perguntam o tempo todo "quanto este pagador mandou nas últimas 24h?". Com colunas tipadas e indexadas, a resposta é direta. O hash separa reenvio (devolve o original) de "mesmo id, outro conteúdo" (409). |
| `risk_analysis` | O julgamento: `analysis_key` (o `key` da resposta), status, score, `decided_by`, `rules_version` e o `metadata` exato que a API respondeu. | Separar fato de julgamento permite reanalisar o histórico com uma nova versão da política. O GET devolve exatamente o que o POST respondeu, sem recalcular. |
| `fraud_rule_hit` | Uma linha por regra disparada: código, família, pontos, se é eliminatória, motivo e `evidence` (jsonb). | É o dossiê de cada decisão e a base para calibrar: "quantas vezes o CTP_02 disparou e quantas dessas viraram fraude?". |

**Índices.** Cada um existe porque uma consulta de contexto usa:
- `(source_document, transaction_date)`: todo o histórico do pagador, numa leitura só
- `(dest_account_key, transaction_date)`: concentração no destino
- `(device_id, transaction_date)`: dispositivo compartilhado
- `fraud_rule_hit(rule_code)`: estatísticas de calibração

**O histórico é por documento, não por conta.** O perfil é da pessoa: quem tem duas contas tem um histórico só. CPF com ou sem máscara é normalizado para dígitos antes de gravar.

**Por que não existe tabela de perfil gravada.** Uma janela de 30 dias muda sozinha todo dia: Pix antigos saem da conta mesmo sem nenhum Pix novo. Uma tabela com esses números ficaria errada no dia seguinte, ou exigiria uma rotina para recalcular. Por isso o perfil (`tx_count_30d`, `total_amount_30d`, `avg_ticket`) e os demais sinais saem de 4 consultas sobre `pix_transaction` no momento da análise. Em escala de produção, a evolução natural é materializar agregados por dia (uma linha por cliente por dia, atualizada no mesmo commit), que nunca ficam velhos porque os dias antigos simplesmente saem da janela.

**Concorrência: o principal desafio.** Ler o histórico, decidir e gravar é um problema clássico de "conferir num momento e usar em outro". Se 10 Pix do mesmo pagador chegam juntos, todos leem "nenhum Pix recente" e todos são aprovados. Consistência transacional sozinha não resolve isso: no isolamento padrão do Postgres, cada análise simplesmente não enxerga as outras que ainda não fizeram commit. A solução é uma **trava consultiva por pagador** (`pg_advisory_xact_lock` sobre o documento), adquirida antes de ler o histórico e solta no commit. Pix do mesmo pagador passam em fila e o segundo enxerga o primeiro. Pagadores diferentes não se bloqueiam. O teste `test_pix_concurrency.py` dispara 10 Pix simultâneos e exige exatamente 2 aprovados. **Sem a trava, o mesmo teste aprovou de 3 a 5 Pix nas nossas execuções.**

Limite conhecido: a trava é por pagador, então dois pagadores *diferentes* pagando o mesmo destino no mesmo milissegundo não se enxergam no CTP_02. Numa janela de 1 hora, essa imprecisão é aceitável.

## Como rodar e testar

### Subir a API e o banco

```bash
docker compose up --build
```

A API sobe em `http://localhost:3000` e o banco é criado a partir de `database/database.sql`. Todas as rotas, exceto `/` e `/health_check`, exigem o header `INTERNAL-TOKEN` (padrão: `default_token`).

### Analisar um Pix

```bash
curl -s -X POST http://localhost:3000/pix/transaction \
  -H 'INTERNAL-TOKEN: default_token' -H 'Content-Type: application/json' \
  -d '{
    "id": "pix-000123",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {"branch": "0001", "account_number": "88213",
      "opening_date": "2025-03-02T10:00:00-03:00", "owner": {"document_number": "123.456.789-09"}},
    "destination_account": {"participant": "60701190", "branch": "3675", "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00", "owner": {"document_number": "987.654.321-00"}},
    "source": {"device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
      "geolocation": {"latitude": -23.56, "longitude": -46.65}}
  }'
```

| Resposta | Quando |
|---|---|
| `201` | Análise nova (approved, two_factor_required ou rejected) |
| `200` | Reenvio do mesmo Pix (mesmo `id` e conteúdo): devolve a análise original |
| `400` `QIT000001` | Payload fora do contrato (campo faltando, campo extra, `amount` ≤ 0, data sem fuso…) |
| `409` `QIT002002` | Mesmo `id` com conteúdo diferente |
| `422` `QIT002003` / `QIT002004` | Data que não existe (ex.: 30/02) / IP inválido |

### Consultar a análise

```bash
curl -s http://localhost:3000/pix/transaction/pix-000123 -H 'INTERNAL-TOKEN: default_token'
```

`200` com o mesmo corpo do POST, ou `404` (`QIT002001`) se o `id` não existe.

### Testes

```bash
pip install -r requirements-dev.txt

# Motor puro (regras, decisão, cenários): não precisa de nada de pé
pytest tests/unit

# Tudo, incluindo API, banco e concorrência (com o docker compose de pé)
pytest
```

- `tests/unit/test_scenarios.py`: **122 cenários** cobrindo cada faixa de cada regra (valor abaixo, exatamente no limite e 1 centavo acima), combinações, faixas de decisão e histórias completas (conta invadida, golpe, laranja, sequestro, fracionamento, script, PJ em lote).
- `tests/integration/pix/`: contrato HTTP, persistência, idempotência, montagem do histórico pelo banco (quais status e janelas contam) e concorrência.

Os cenários viram documentação com `python scripts/gerar_cenarios.py` (gera [`docs/cenarios.md`](docs/cenarios.md)). O documento é o resultado de rodar o motor, não um texto escrito à mão.

## Escopo e limitações

**Dentro:** POST e GET, banco próprio com o histórico de tudo que chegou, regras, testes e este README.

**Fora** (conforme o desafio): onboarding e cadastro de contas, front-end e outras APIs. Também não validamos saldo, existência da conta nem dígito verificador de CPF/CNPJ: isso é responsabilidade do core Pix que chama o antifraude. O schema cobra só o formato.

**Limitações:**
- **Resultado do 2FA.** O motor não sabe se o cliente confirmou, porque isso exigiria outra rota (fora do escopo). Por isso Pix em 2FA contam no montante, mas não ensinam confiança (perfil e destino conhecido).
- **Golpe sem histórico.** Contra cliente sem perfil recente, um golpe pode cair em 2FA (cenário HIST-06), e no golpe é o próprio cliente quem confirma.
- **Calibração.** Sem base rotulada de fraudes, pesos e limites são critérios de risco validados com cenários, não ótimos estatísticos. O score não é uma probabilidade. Os parâmetros ficam centralizados em `policy.py` e cada análise grava a `policy_version` que a decidiu.
- **Evolução.** Com fraudes confirmadas como rótulo, dá para medir falsos positivos e falsos negativos por regra (a `fraud_rule_hit` já guarda o necessário) e, aí sim, considerar um modelo supervisionado como mais um sinal no score.
