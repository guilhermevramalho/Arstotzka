# Project Arstotzka — Grupo 20

**Integrantes:** Guilherme Vicente Ramalho, Leonardo Bonfá Schroeder

Motor antifraude para Pix construído sobre o Base Service (Python, FastAPI e PostgreSQL). A API recebe uma transação em `POST /pix/transaction`, decide entre `approved`, `two_factor_required` e `rejected` e devolve, junto com a decisão, cada regra que disparou e por quê.

## Como o motor de decisão funciona

O motor combina **regras determinísticas** com um **modelo de machine learning que entra como mais uma regra** (`PRF_07`). Nenhuma decisão é caixa-preta: todo ponto somado tem uma regra, um motivo e a evidência que o justificou.

### O caminho de uma requisição

A requisição segue as camadas do Base Service, e cada camada faz uma coisa só:

| Camada | Arquivo | O que faz no motor |
|---|---|---|
| app | `src/app.py` | Registra os middlewares e liga `POST /pix/transaction` e `GET /pix/transaction/{pix_id}` aos resources. |
| middlewares | `src/middlewares/` | Identificador da requisição, log, conferência do `INTERNAL-TOKEN` e sessão de banco. |
| schemas | `src/schemas/post_pix_transaction.json` | Confere o formato do payload antes de qualquer regra. Payload torto devolve 400. |
| resources | `src/resources/pix_transaction.py` | Recebe a requisição e chama o controller. Não decide nada. |
| controllers | `src/controllers/pix_transaction_controller.py` | Orquestra a análise: idempotência, histórico, regras, decisão e gravação. As regras moram aqui. |
| repositories | `src/repositories/pix_transaction_repository.py` | Única camada que consulta o banco: trava do pagador, histórico das regras, histórico do modelo e gravação. |
| models | `src/models/` | As tabelas `pix_transaction`, `risk_analysis` e `fraud_rule_hit` em Python. |
| dtos | `src/dtos/pix_analysis_dto.py` | Transforma a análise gravada na resposta do contrato. |
| utils | `src/utils/` | `policy.py` (todos os parâmetros), `types.py` (objetos do motor), `pix_payload.py`, `geo.py`, `ml_features.py` e `ml_model.py` (modelo comportamental). |
| database | `database/database.sql` | Schema, índices das consultas de histórico e travas de imutabilidade. |

### O fluxo de uma análise

1. **Validação do contrato.** O JSON Schema confere tipos, formatos e campos obrigatórios.
2. **Trava do pagador.** Uma trava consultiva do Postgres (`pg_advisory_xact_lock`) por documento do pagador coloca Pix simultâneos do mesmo pagador em fila. Assim, dez Pix disparados juntos enxergam uns aos outros em vez de lerem todos "nenhum Pix recente".
3. **Idempotência.** O mesmo `id` com o mesmo conteúdo devolve a análise original, sem rodar as regras de novo e sem contar o Pix duas vezes. O mesmo `id` com outro conteúdo devolve `409 Conflict`. A comparação é feita pelo SHA-256 do payload canônico.
4. **Histórico.** O repository monta, em poucas consultas, tudo o que as regras precisam sobre o passado (o `HistorySnapshot`), mais o histórico que o modelo comportamental usa. Só entram Pix anteriores ao atual.
5. **Regras.** As 17 regras rodam sobre o Pix e o histórico. Cada uma devolve "não disparou" ou um `RuleHit` com pontos, motivo e evidência.
6. **Decisão.** Rejeição imediata, se houver; senão, a soma dos pontos define o status.
7. **Gravação.** O Pix (`pix_transaction`), a decisão (`risk_analysis`) e cada regra disparada (`fraud_rule_hit`) são gravados num único commit. As três tabelas são imutáveis: o banco recusa `UPDATE` e `DELETE`.

### Por que três tabelas

- **`pix_transaction`** é o fato: o Pix como chegou, que nunca muda. É dela que saem todas as consultas de histórico, com índices específicos para cada uma.
- **`risk_analysis`** é a decisão do motor sobre aquele Pix: status, score, quem decidiu, versão da política e a resposta enviada.
- **`fraud_rule_hit`** é o dossiê: cada regra disparada com o valor observado. É o que permite explicar um bloqueio e, depois, calibrar regras que geram atrito demais.

Não existe uma tabela de "perfil" mutável por conta. Os sinais são calculados na hora a partir do histórico imutável, o que evita condição de corrida entre dois Pix do mesmo cliente.

## Regras

Valores em reais; no código tudo é comparado em centavos, como o `amount` do payload. Todos os parâmetros ficam em `src/utils/policy.py`, versionados por `POLICY_VERSION`, que é gravado em cada análise. "Rejeição" significa rejeição imediata, independentemente dos outros pontos.

### Integridade e limites

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `INT_01` — Mesma conta | Origem e destino são a mesma conta do mesmo titular. | Mesmo documento, agência e conta: **rejeição**. | Não é uma transferência válida. Transferir entre contas diferentes do mesmo titular continua permitido. |
| `LIM_01` — Limite por transação | Valor acima do limite de atenção do perfil soma pontos; acima do teto, rejeita. | PF: acima de R$ 5.000, +45; acima de R$ 15.000, **rejeição**. PJ: acima de R$ 25.000, +45; acima de R$ 100.000, **rejeição**. | Limita a exposição de uma única operação. +45 sozinho já pede 2FA. PJ tem tetos maiores porque pagar fornecedores é rotina. |
| `LIM_02` — Valor noturno | Entre 20h e 5h59, na hora local do payload. | PF: acima de R$ 1.000, +40; acima de R$ 3.000, **rejeição**. PJ: acima de R$ 5.000, +35; acima de R$ 15.000, **rejeição**. | R$ 1.000 é o limite noturno padrão do Banco Central para pessoa física. Acima de R$ 3.000 rejeitamos porque, no sequestro relâmpago, a vítima confirma o 2FA sob coação. |

### Velocity

As contagens incluem o Pix atual. Para PJ, as contagens das regras `VEL_01` e `VEL_03` são multiplicadas por 5.

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `VEL_01` — Rajada | Pix do mesmo pagador em janelas curtas, com qualquer status. | 3 ou mais em 2 minutos: +45. 5 ou mais em 5 minutos: **rejeição**. | Conta invadida é esvaziada em rajada, antes que a vítima perceba. |
| `VEL_02` — Repetição | Mesmo pagador, mesmo destino e mesmo valor. | Repetição em até 120 segundos: **rejeição**. 3 ou mais idênticos em 10 minutos: **rejeição**. | Repetição imediata costuma ser clique duplo ou automação. Rejeitar deixa o cliente tentar de novo sem ficar preso num 2FA. Reenvio técnico do mesmo `id` não conta: é tratado pela idempotência. |
| `VEL_03` — Pulverização | Destinatários distintos do pagador em 10 minutos. | 3 ou mais: +40. 5 ou mais: **rejeição**. | Conta comprometida espalha o saldo por várias contas laranja. |

### Montante

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `MON_01` — Volume acumulado | Soma dos Pix aprovados ou em 2FA, mais o atual, com pelo menos 2 Pix na janela. Rejeitados não somam, porque o dinheiro não saiu. | PF: acima de R$ 4.000 em 1 hora, +40; acima de R$ 10.000 em 24 horas, +45; acima de R$ 20.000 em 24 horas, **rejeição**. PJ: valores × 5. | Pega quem fraciona: vários Pix de R$ 4.900 para não cair no `LIM_01`. |

### Perfil

O perfil do cliente são os Pix **aprovados** do mesmo documento nos últimos 30 dias.

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `PRF_01` — Desvio do valor habitual | Valor atual comparado ao ticket médio do perfil. | Exige 3 ou mais Pix no perfil e valor a partir de R$ 1.000. Acima de 3× a média: +30. Acima de 8× a média: +50. | Golpista não respeita o padrão de consumo da vítima. O valor mínimo evita incomodar quem sempre manda pouco. |
| `PRF_02` — Dispositivo novo | Aparelho sem nenhum Pix aprovado deste pagador, para pagador que já tem histórico. | Pix acima de R$ 200: +30. Mais de R$ 1.000 no aparelho novo em 24 horas: +45. | Alinhado aos limites do Banco Central para dispositivo não cadastrado. Trocar de celular é normal, por isso a regra pede 2FA em vez de rejeitar. |
| `PRF_03` — Dispositivo compartilhado | Documentos pagadores distintos no mesmo aparelho em 7 dias. | 2 titulares: +30. 3: +45. 4 ou mais: **rejeição**. | Um casal dividindo o celular é normal. Quatro ou mais CPFs no mesmo aparelho é assinatura de "fazenda" de contas laranja. |
| `PRF_04` — Deslocamento incompatível | Velocidade aparente entre a última geolocalização aprovada e a atual, a partir de 100 km de distância. | Acima de 300 km/h: +45. Acima de 800 km/h: +60. Acima de 900 km/h: **rejeição**. | Viagem de avião pede 2FA. Dois Pix em cidades distantes com segundos de diferença indicam GPS falso, VPN ou sessão roubada. |
| `PRF_05` — Conta de origem recente | Idade da conta de origem no momento do Pix. | Menos de 3 dias e valor a partir de R$ 1.000: +30. Menos de 24 horas e valor acima de R$ 3.000: +50. | Conta recém-aberta movimentando alto é o padrão de conta laranja descartável. |
| `PRF_06` — Fuso incompatível | Fuso declarado na data do Pix comparado ao fuso esperado pela longitude do GPS. | Divergência de 2 horas ou mais: **rejeição**. | Golpista muda o fuso do aparelho para fugir do horário noturno do `LIM_02`. A tolerância de 1 hora cobre fronteiras de fuso. |
| `PRF_07` — Score comportamental (ML) | Um modelo LightGBM compara o Pix com o hábito do pagador e com o que está acontecendo no destino, no aparelho e no IP. Detalhes na seção abaixo. | Score a partir de 0,7804: +45. Score a partir de 0,7035: +30. Não dispara em partida a frio. | Pega combinações que uma regra isolada não pega, como destinatário novo com conta recém-aberta e valor fora do padrão do cliente. Sinal comportamental soma pontos, mas nunca rejeita sozinho. |

### Contraparte

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `CTP_01` — Destinatário recente | Idade da conta destino combinada ao valor. Vale a faixa mais severa. | Menos de 24 horas e a partir de R$ 5.000: +60. Até 48 horas e a partir de R$ 2.000: +45. Até 7 dias e a partir de R$ 500: +25. | Conta laranja é aberta pouco antes do golpe e esvaziada logo depois. A idade sozinha nunca rejeita. |
| `CTP_02` — Concentração de recebimentos | Pagadores distintos para o mesmo destino PF em 1 hora. | 5 ou mais: +40. 10 ou mais, com conta destino aberta há menos de 30 dias: +60. | Conta coletora recebendo de várias vítimas ao mesmo tempo. Destino PJ fica de fora: loja recebe de muitos clientes. |
| `CTP_03` — Contraparte conhecida | Redutor: o pagador já teve Pix aprovado para este destino há mais de 24 horas. | −25 pontos. | Diminui o atrito em pagamentos de rotina, como aluguel. As 24 horas impedem que o golpista "esquente" o contato minutos antes. Não salva uma rejeição. |

### O modelo comportamental (`PRF_07`)

**O que ele olha.** São 23 sinais calculados a partir do histórico, sempre só com Pix anteriores ao atual:

| Grupo | Sinais |
|---|---|
| O próprio Pix | valor, hora, dia da semana, madrugada, canal, PF ou PJ na origem e no destino |
| Contas | idade da conta de origem e da conta destino |
| Hábito do pagador | Pix de 90 dias a 24 horas atrás: quantidade, valor típico (mediana), razão valor ÷ valor típico, destinatário fora do habitual, aparelho fora do habitual, distância da localização habitual |
| Agora | Pix do pagador na última hora e nas últimas 24 horas, soma enviada em 24 horas |
| Destino, aparelho e IP | pagadores distintos do destino em 24 horas e 7 dias, outras contas no mesmo aparelho em 7 dias, outras contas no mesmo IP em 24 horas |

O "hábito" para 24 horas antes do Pix de propósito. Numa conta invadida, os primeiros Pix da rajada contaminariam o "normal" do cliente e esconderiam os seguintes.

**Como foi treinado.** O código está em `ml/`.

- **Dados.** Não existe base pública rotulada de fraude em Pix, então geramos dados sintéticos (`ml/gerar_dataset_v2.py`) **no mesmo formato da tabela `pix_transaction`**: cerca de 1.100 clientes com hábitos próprios (aparelhos, IP, cidade, valor típico, destinatários recorrentes), 93.750 Pix e 3% de fraude.
- **Quatro golpes:** conta invadida, engenharia social (a vítima paga do próprio celular), golpe em massa (muitas vítimas pagando a mesma conta laranja) e conta laranja aberta no próprio banco.
- **Casos legítimos difíceis**, para o modelo não aprender atalhos falsos: troca de celular, viagem, aluguel, Pix para conta recém-aberta de conhecido, conta nova movimentando logo após abrir.
- **Divisão.** 64% treino, 16% validação e 20% teste, estratificados.
- **Modelo.** LightGBM com peso 31,5 na fraude (a proporção entre classes), parada antecipada pela PR-AUC da validação e restrições monotônicas: conta destino mais nova, valor mais acima do habitual ou mais contas no mesmo aparelho nunca diminuem o risco.
- **Cortes.** Os dois cortes do score foram escolhidos na validação: no maior, pelo menos 90% dos Pix eram fraude; o menor alcança 95% das fraudes.

**Resultados no teste** (Pix de 2023 em diante, 473 fraudes e 14.916 legítimos):

| Métrica | Resultado |
|---|---|
| PR-AUC | 0,97 (um modelo aleatório faria 0,03) |
| PR-AUC treinando até jun/2024 e testando de jul/2024 em diante | 0,98 |
| Fraudes acima do corte menor | 93,9% |
| Precisão acima do corte menor | 86,5% |
| Legítimos acima do corte menor | 0,46% |

Por tipo de golpe: conta invadida 97%, conta laranja de origem 97%, engenharia social 92% e golpe em massa 86%.

**Limitação.** Os números medem o modelo nos golpes que nós simulamos. Eles provam que o pipeline funciona, não que o modelo detecta fraude real. Em produção, o modelo seria retreinado com rótulos reais (contestações e MED) e monitorado. É também por isso que ele entra como uma regra que soma pontos, e não como quem decide sozinho.

**Explicação de cada decisão.** O score do LightGBM é uma soma de contribuições. Com `pred_contrib` (TreeSHAP), o motor sabe quanto cada sinal empurrou o score daquele Pix específico. Os até três sinais que mais empurraram para "fraude", e que são de fato sinais de risco, viram o motivo da regra. Exemplo: `Modelo comportamental indica risco alto: conta destino aberta há 1 dia; valor 20.8x o valor típico do pagador; primeiro Pix para este destinatário`.

**Garantias na API.**

- **Mesmo cálculo do treino.** As features da API (`src/utils/ml_features.py`) são as mesmas do treino. O script `ml/check_features_parity.py` confere que o cálculo do treino e o cálculo por Pix dão resultados idênticos.
- **Modelo exportado sem pickle.** O modelo vai em texto (`src/utils/ml_artifacts/model.txt`) mais um JSON de pré-processamento. A API não depende de scikit-learn, e o export confere que o score é idêntico ao do modelo original.
- **Partida a frio.** Se a conta de origem tem 30 dias ou mais mas nenhum Pix no nosso histórico, "sem histórico" é falta de dado nosso, não comportamento do cliente. A `PRF_07` não dispara e o motor decide só com as demais regras.
- **Falha nunca vira fraude.** Se o modelo falhar por qualquer motivo, a `PRF_07` é ignorada e o erro é registrado no log.

## Como as regras viram decisão

O motor avalia todas as regras e decide em três passos, nesta ordem:

1. **Rejeição imediata.** Se qualquer regra disparar com rejeição (`INT_01`, os tetos de `LIM_01`, `LIM_02` e `MON_01`, `VEL_01`, `VEL_02`, `VEL_03`, 4 ou mais CPFs na `PRF_03`, 900 km/h na `PRF_04`, `PRF_06`), o Pix é `rejected` com `decided_by = "hard_rule"`. Nenhum redutor salva uma rejeição.
2. **Pontuação.** Senão, os pontos de todas as regras disparadas são somados: `score = max(0, soma dos pontos)`. Cada regra contribui uma vez, com a faixa mais severa que casou. O `CTP_03` pode subtrair.
3. **Faixas:**

| Score | Status | Significado |
|---|---|---|
| menor que 40 | `approved` | Sinais fracos ou nenhum: o cliente não é incomodado. |
| de 40 a 79 | `two_factor_required` | Um sinal forte ou dois fracos: o cliente confirma que é ele. |
| 80 ou mais | `rejected` | Sinais independentes que, somados, indicam fraude. |

**Quando pede 2FA.** A faixa de 40 foi escolhida para que um único sinal forte (+40 ou +45) já peça confirmação e que dois sinais fracos somados também peçam. Exemplos: Pix acima de R$ 5.000 (`LIM_01`, +45); aparelho novo com Pix acima de R$ 200 (`PRF_02`, +30) junto com destino aberto há 5 dias (`CTP_01`, +25); o modelo comportamental com risco alto (`PRF_07`, +45).

**Por que algumas regras rejeitam direto.** O 2FA protege contra conta invadida, porque o golpista não tem o segundo fator. Mas em golpes de engenharia social e sequestro, é a própria vítima quem confirma o 2FA. Por isso os sinais desses golpes (teto noturno, rajada, fuso falso, fazenda de aparelhos) rejeitam em vez de pedir 2FA.

**A resposta.** Toda análise devolve `201` com o status e o dossiê. Rejeitar não é erro de requisição.

```json
{
  "key": "1b7c2c4e-5a7e-4b8f-9a51-3f2f4f0c9d10",
  "status": "rejected",
  "metadata": {
    "engine_version": "1.0.0",
    "policy_version": "2026-10-18.1",
    "score": 185,
    "decision": "rejected",
    "decided_by": "score",
    "hard_reject": false,
    "triggered_rules": [
      {"rule_id": "PRF_01", "family": "PERFIL", "points": 50, "hard_reject": false, "reason": "Valor mais de 8x o médio", "evidence": {"amount": 250000, "avg_ticket_30d": 12000, "tx_count_30d": 6}},
      {"rule_id": "PRF_02", "family": "PERFIL", "points": 45, "hard_reject": false, "reason": "Device novo com R$ 2.500,00 em 24h", "evidence": {"device_id": "dvc-desconhecido", "amount": 250000, "device_sum_24h": 250000}},
      {"rule_id": "PRF_07", "family": "PERFIL", "points": 45, "hard_reject": false, "reason": "Modelo comportamental indica risco alto: conta destino aberta há 1 dia; valor 20.8x o valor típico do pagador; primeiro Pix para este destinatário", "evidence": {"model_version": "v2-20261018", "score": 0.9991, "threshold": 0.780442, "factors": ["..."]}},
      {"rule_id": "CTP_01", "family": "CONTRAPARTE", "points": 45, "hard_reject": false, "reason": "Destino novo (24.0h) com Pix alto", "evidence": {"dest_age_hours": 24.0, "amount": 250000}}
    ]
  }
}
```

O exemplo é ilustrativo; os números de cada análise dependem do histórico. `GET /pix/transaction/{pix_id}` devolve a análise gravada, sem rodar as regras de novo.

## Como rodar e testar

### Pré-requisitos

Docker com Docker Compose e, para os testes, Python 3.11.

### Subir a API e o banco

```bash
docker compose up --build
```

A API sobe em `http://localhost:3000` e o Postgres em `localhost:5432`. O banco nasce com o schema de `database/database.sql`. Todas as rotas de Pix exigem o cabeçalho `INTERNAL-TOKEN` (padrão: `default_token`).

### Analisar um Pix

```bash
curl -s -X POST http://localhost:3000/pix/transaction \
  -H "Content-Type: application/json" \
  -H "INTERNAL-TOKEN: default_token" \
  -d '{
    "id": "pix-000123",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
      "branch": "0001",
      "account_number": "88213",
      "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": {"document_number": "123.456.789-09"}
    },
    "destination_account": {
      "participant": "60701190",
      "branch": "3675",
      "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": {"document_number": "987.654.321-00"}
    },
    "source": {
      "device_id": "dvc-9f2c71a8",
      "channel": "app",
      "ip": "198.51.100.23",
      "geolocation": {"latitude": -23.56, "longitude": -46.65}
    }
  }'
```

### Consultar uma análise

```bash
curl -s http://localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

### Rodar os testes

Com a API de pé (`docker compose up`), em outro terminal:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

### Retreinar o modelo (opcional)

O modelo já vem treinado em `src/utils/ml_artifacts/`. Para reproduzi-lo:

```bash
cd ml
pip install -r requirements.txt
python gerar_dataset_v2.py
python check_features_parity.py
python train_v2.py
python export_for_api.py
```

A semente é fixa, então o modelo gerado é idêntico ao versionado. O `export_for_api.py` grava os artefatos direto em `src/utils/ml_artifacts/` e confere que o score exportado é igual ao do modelo treinado.

## Escopo e limitações

- **Escopo.** Análise de Pix, histórico, regras, decisão, consulta e testes. Onboarding, cadastro de contas e front-end ficam de fora, como pede o desafio.
- **Parâmetros das regras determinísticas.** São escolhas de política. Alguns são ancorados em referências do Banco Central (limite noturno de R$ 1.000 para PF, limites para dispositivo não cadastrado); os demais são hipóteses iniciais a calibrar com dados reais. A tabela `fraud_rule_hit` existe para isso: mostra quais regras mais disparam e geram atrito.
- **O modelo de ML foi treinado com dados sintéticos.** Por isso ele soma pontos em vez de decidir sozinho, e não dispara em partida a frio.
- **Falha técnica nunca é tratada como fraude.**
