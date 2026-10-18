# Cenários do motor antifraude

Gerado por `scripts/gerar_cenarios.py` a partir de `tests/unit/scenario_catalog.py` (política `2026-10-17.1`). Cada linha é um teste automatizado.

**Pix base de todos os cenários:** PF → PF, quinta-feira 15/10/2026 às 14h (-03:00), R$ 100,00, contas abertas há anos, celular que o cliente já usa, cliente com 10 Pix aprovados antigos e nada recente. Cada cenário muda só o que está escrito nele. "Antes" = histórico que já existia quando o Pix chegou.

Faixas: score < 40 → approved · 40 a 79 → two_factor_required · ≥ 80 → rejected. Regra eliminatória rejeita sozinha, e redutor não a desfaz.

## Base

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| BASE-01 | Pix comum: PF, 14h, R$ 100, dispositivo e contas antigas | — | 0 | ✅ approved |
| BASE-02 | Primeiro Pix da vida do cliente (sem histórico nenhum) | — | 0 | ✅ approved |
| BASE-03 | Exemplo do PDF: R$ 1.500 às 22h15, PF | LIM_02 (+40) | 40 | 🔐 2FA |

- **BASE-02:** Sem histórico não há dispositivo 'de sempre': PRF_02 não se aplica.

## INT_01 — Mesma conta

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| INT-01 | Origem e destino: mesmo titular, mesma agência e conta | INT_01 (eliminatória) | 0 | ⛔ rejected |
| INT-02 | Mesmo titular, outra conta (transferência entre contas próprias) | — | 0 | ✅ approved |
| INT-03 | Contas próprias, R$ 8.000 (só o limite pesa) | LIM_01 (+45) | 45 | 🔐 2FA |

## LIM_01 — Limite por transação

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| LIM1-01 | PF, R$ 5.000,00 (exatamente no limite de atenção) | — | 0 | ✅ approved |
| LIM1-02 | PF, R$ 5.000,01 | LIM_01 (+45) | 45 | 🔐 2FA |
| LIM1-03 | PF, R$ 15.000,00 (exatamente no teto) | LIM_01 (+45) | 45 | 🔐 2FA |
| LIM1-04 | PF, R$ 15.000,01 | LIM_01 (eliminatória) | 0 | ⛔ rejected |
| LIM1-05 | PJ, R$ 25.000,00 | — | 0 | ✅ approved |
| LIM1-06 | PJ, R$ 25.000,01 | LIM_01 (+45) | 45 | 🔐 2FA |
| LIM1-07 | PJ, R$ 100.000,00 | LIM_01 (+45) | 45 | 🔐 2FA |
| LIM1-08 | PJ, R$ 100.000,01 | LIM_01 (eliminatória) | 0 | ⛔ rejected |
| LIM1-09 | PF, R$ 5.000,01 para destinatário conhecido | LIM_01 (+45), CTP_03 (-25) | 20 | ✅ approved |
| LIM1-10 | PF, R$ 20.000 para destinatário conhecido | LIM_01 (eliminatória), CTP_03 (-25) | 0 | ⛔ rejected |

- **LIM1-09:** 45 − 25 = 20: aluguel alto para o mesmo locador passa sem fricção.
- **LIM1-10:** Redutor não salva eliminatória.

## LIM_02 — Valor noturno

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| LIM2-01 | PF, 22h, R$ 1.000,00 (limite noturno do BC) | — | 0 | ✅ approved |
| LIM2-02 | PF, 22h, R$ 1.000,01 | LIM_02 (+40) | 40 | 🔐 2FA |
| LIM2-03 | PF, 22h, R$ 3.000,00 | LIM_02 (+40) | 40 | 🔐 2FA |
| LIM2-04 | PF, 22h, R$ 3.000,01 | LIM_02 (eliminatória) | 0 | ⛔ rejected |
| LIM2-05 | PF, 19h59, R$ 2.000 (ainda é dia) | — | 0 | ✅ approved |
| LIM2-06 | PF, 20h00, R$ 2.000 (começo da noite, inclusive) | LIM_02 (+40) | 40 | 🔐 2FA |
| LIM2-07 | PF, 05h59, R$ 2.000 | LIM_02 (+40) | 40 | 🔐 2FA |
| LIM2-08 | PF, 06h00, R$ 2.000 (fim da noite) | — | 0 | ✅ approved |
| LIM2-09 | PF no Acre, 19h -05:00 (00h em UTC), R$ 2.000 | — | 0 | ✅ approved |
| LIM2-10 | PJ, 22h, R$ 5.000,00 | — | 0 | ✅ approved |
| LIM2-11 | PJ, 22h, R$ 5.000,01 (sinal sozinho não chega a 2FA) | LIM_02 (+35) | 35 | ✅ approved |
| LIM2-12 | PJ, 22h, R$ 15.000,01 | LIM_02 (eliminatória) | 0 | ⛔ rejected |
| LIM2-13 | PF, 22h, R$ 5.000,01 (limite e noite juntos) | LIM_01 (+45), LIM_02 (eliminatória) | 45 | ⛔ rejected |

- **LIM2-09:** A hora vem do fuso do payload, não do servidor.

## VEL_01 — Rajada

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| VEL1-01 | 2º Pix do pagador em 2 min | — | 0 | ✅ approved |
| VEL1-02 | 3º Pix do pagador em 2 min | VEL_01 (+45) | 45 | 🔐 2FA |
| VEL1-03 | 4º Pix em 5 min, mas só 2 nos últimos 2 min | — | 0 | ✅ approved |
| VEL1-04 | 5º Pix em 5 min | VEL_01 (eliminatória) | 0 | ⛔ rejected |
| VEL1-05 | PJ: 14º Pix em 2 min (limite PJ é 15) | — | 0 | ✅ approved |
| VEL1-06 | PJ: 15º Pix em 2 min | VEL_01 (+45) | 45 | 🔐 2FA |
| VEL1-07 | PJ: 25º Pix em 5 min | VEL_01 (eliminatória) | 0 | ⛔ rejected |

## VEL_02 — Repetição

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| VEL2-01 | Mesmo destino e valor repetido em 60 s | VEL_02 (+45) | 45 | 🔐 2FA |
| VEL2-02 | Mesmo destino e valor repetido depois de 5 min | — | 0 | ✅ approved |
| VEL2-03 | 3ª tentativa idêntica em 10 min | VEL_02 (eliminatória) | 0 | ⛔ rejected |
| VEL2-04 | Mesmo destino, valor diferente, em 60 s | — | 0 | ✅ approved |

- **VEL2-04:** Repetição exige mesmo valor; reenvio técnico (mesmo id) é idempotência, não conta aqui.

## VEL_03 — Muitos destinos

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| VEL3-01 | 2 destinatários distintos em 10 min | — | 0 | ✅ approved |
| VEL3-02 | 3 destinatários distintos em 10 min | VEL_03 (+40) | 40 | 🔐 2FA |
| VEL3-03 | 4 destinatários distintos em 10 min | VEL_03 (+40) | 40 | 🔐 2FA |
| VEL3-04 | 5 destinatários distintos em 10 min | VEL_03 (eliminatória) | 0 | ⛔ rejected |
| VEL3-05 | PJ: 14 destinatários em 10 min | — | 0 | ✅ approved |
| VEL3-06 | PJ: 15 destinatários em 10 min | VEL_03 (+40) | 40 | 🔐 2FA |

## MON_01 — Montante

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| MON-01 | 1h: R$ 3.000 antes + R$ 1.000 agora = R$ 4.000,00 | — | 0 | ✅ approved |
| MON-02 | 1h: R$ 3.000 antes + R$ 1.000,01 agora | MON_01 (+40) | 40 | 🔐 2FA |
| MON-03 | 1h: um Pix sozinho de R$ 4.500 (sem acumulação) | — | 0 | ✅ approved |
| MON-04 | 24h: R$ 8.000 antes + R$ 2.000 agora = R$ 10.000,00 | — | 0 | ✅ approved |
| MON-05 | 24h: R$ 8.000 antes + R$ 2.000,01 agora | MON_01 (+45) | 45 | 🔐 2FA |
| MON-06 | 24h: R$ 18.000 antes + R$ 2.000 agora = R$ 20.000,00 | MON_01 (+45) | 45 | 🔐 2FA |
| MON-07 | 24h: R$ 18.000 antes + R$ 2.000,01 agora | MON_01 (eliminatória) | 0 | ⛔ rejected |
| MON-08 | Um único Pix de R$ 12.000, sem histórico recente | LIM_01 (+45) | 45 | 🔐 2FA |
| MON-09 | 1h e 24h ao mesmo tempo: vale só a faixa mais severa | MON_01 (+45) | 45 | 🔐 2FA |
| MON-10 | PJ, 1h: R$ 18.000 antes + R$ 2.000,01 agora (limite PJ R$ 20.000) | MON_01 (+40) | 40 | 🔐 2FA |
| MON-11 | PJ, 24h: R$ 60.000 em vários Pix (PF rejeitaria) | MON_01 (+45) | 45 | 🔐 2FA |

- **MON-08:** Correção: antes o MON_01 somava +45 sobre o mesmo Pix e rejeitava (90). Acumulação exige 2+ Pix.

## PRF_01 — Desvio do ticket

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| PRF1-01 | Só 2 Pix no perfil (média R$ 200), Pix de R$ 5.000 agora | — | 0 | ✅ approved |
| PRF1-02 | Média R$ 200, Pix de R$ 999,99 (abaixo do piso de R$ 1.000) | — | 0 | ✅ approved |
| PRF1-03 | Média R$ 400, Pix de R$ 1.200,00 (exatamente 3x) | — | 0 | ✅ approved |
| PRF1-04 | Média R$ 400, Pix de R$ 1.200,01 | PRF_01 (+30) | 30 | ✅ approved |
| PRF1-05 | Média R$ 400, Pix de R$ 3.200,00 (exatamente 8x) | PRF_01 (+30) | 30 | ✅ approved |
| PRF1-06 | Média R$ 400, Pix de R$ 3.200,01 | PRF_01 (+50) | 50 | 🔐 2FA |
| PRF1-07 | Cliente de ticket alto: média R$ 3.000, Pix de R$ 4.000 | — | 0 | ✅ approved |

- **PRF1-01:** Com menos de 3 Pix não existe régua confiável.

## PRF_02 — Dispositivo novo

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| PRF2-01 | Dispositivo novo, R$ 200,00 | — | 0 | ✅ approved |
| PRF2-02 | Dispositivo novo, R$ 200,01 | PRF_02 (+30) | 30 | ✅ approved |
| PRF2-03 | Dispositivo novo: R$ 900 hoje nele + R$ 100 agora = R$ 1.000,00 | — | 0 | ✅ approved |
| PRF2-04 | Dispositivo novo: R$ 900 hoje nele + R$ 100,01 agora | PRF_02 (+45) | 45 | 🔐 2FA |
| PRF2-05 | Dispositivo novo, um Pix de R$ 1.500 | PRF_02 (+45) | 45 | 🔐 2FA |
| PRF2-06 | Dispositivo conhecido, R$ 3.000 | — | 0 | ✅ approved |
| PRF2-07 | Cliente sem nenhum aprovado, dispositivo 'novo', R$ 3.000 | — | 0 | ✅ approved |

## PRF_03 — Dispositivo compartilhado

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| PRF3-01 | Dispositivo usado só por este titular | — | 0 | ✅ approved |
| PRF3-02 | 2 titulares no mesmo aparelho em 7 dias (ex.: casal) | PRF_03 (+30) | 30 | ✅ approved |
| PRF3-03 | 3 titulares no mesmo aparelho | PRF_03 (+45) | 45 | 🔐 2FA |
| PRF3-04 | 6 titulares no mesmo aparelho (não rejeita sozinho) | PRF_03 (+45) | 45 | 🔐 2FA |

## PRF_04 — Deslocamento

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| PRF4-01 | Pix sem geolocalização (campo opcional) | — | 0 | ✅ approved |
| PRF4-02 | Sem Pix anterior com geolocalização | — | 0 | ✅ approved |
| PRF4-03 | Campinas → São Paulo (~85 km) em 10 min | — | 0 | ✅ approved |
| PRF4-04 | Rio → São Paulo (~357 km) em 6h (~60 km/h) | — | 0 | ✅ approved |
| PRF4-05 | Rio → São Paulo em 1h (~357 km/h) | PRF_04 (+45) | 45 | 🔐 2FA |
| PRF4-06 | Recife → São Paulo (~2.130 km) em 2h (~1.065 km/h) | PRF_04 (+60) | 60 | 🔐 2FA |
| PRF4-07 | Rio → São Paulo no mesmo instante | PRF_04 (+60) | 60 | 🔐 2FA |

- **PRF4-03:** Abaixo de 100 km não avalia: imprecisão de GPS geraria velocidades absurdas.

## PRF_05 — Conta de origem nova

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| PRF5-01 | Conta de 2 dias, R$ 999,99 | — | 0 | ✅ approved |
| PRF5-02 | Conta de 2 dias, R$ 1.000,00 | PRF_05 (+30) | 30 | ✅ approved |
| PRF5-03 | Conta de exatamente 3 dias, R$ 2.000 | — | 0 | ✅ approved |
| PRF5-04 | Conta de 12h, R$ 3.000,00 | PRF_05 (+30) | 30 | ✅ approved |
| PRF5-05 | Conta de 12h, R$ 3.000,01 | PRF_05 (+50) | 50 | 🔐 2FA |
| PRF5-06 | Abertura com data no futuro (tratada como recém-aberta), R$ 3.500 | PRF_05 (+50) | 50 | 🔐 2FA |

## CTP_01 — Destino recente

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| CTP1-01 | Destino de 7 dias, R$ 499,99 | — | 0 | ✅ approved |
| CTP1-02 | Destino de exatamente 7 dias, R$ 500,00 | CTP_01 (+25) | 25 | ✅ approved |
| CTP1-03 | Destino de 7 dias e 1h, R$ 1.000 | — | 0 | ✅ approved |
| CTP1-04 | Destino de 48h, R$ 1.999,99 (cai na faixa de 7 dias) | CTP_01 (+25) | 25 | ✅ approved |
| CTP1-05 | Destino de exatamente 48h, R$ 2.000 | CTP_01 (+45) | 45 | 🔐 2FA |
| CTP1-06 | Destino de exatamente 24h, R$ 5.000 (faixa de 48h) | CTP_01 (+45) | 45 | 🔐 2FA |
| CTP1-07 | Destino de 23h, R$ 5.000 | CTP_01 (+60) | 60 | 🔐 2FA |

## CTP_02 — Concentração no destino

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| CTP2-01 | Destino PF recebeu de 4 pagadores em 1h | — | 0 | ✅ approved |
| CTP2-02 | Destino PF recebeu de 5 pagadores em 1h | CTP_02 (+40) | 40 | 🔐 2FA |
| CTP2-03 | Destino PF antigo recebeu de 10 pagadores em 1h | CTP_02 (+40) | 40 | 🔐 2FA |
| CTP2-04 | Destino PF de 10 dias recebeu de 10 pagadores em 1h | CTP_02 (+60) | 60 | 🔐 2FA |
| CTP2-05 | Destino PJ (loja) recebeu de 50 pagadores em 1h | — | 0 | ✅ approved |

- **CTP2-05:** Correção: loja recebendo de muitos clientes é o normal; a regra vale só para destino PF.

## CTP_03 — Destinatário conhecido

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| CTP3-01 | Destinatário conhecido, sem outros sinais (score não fica negativo) | CTP_03 (-25) | 0 | ✅ approved |
| CTP3-02 | Conhecido + destino concentrando pagadores | CTP_02 (+40), CTP_03 (-25) | 15 | ✅ approved |

## Faixas de decisão

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| DEC-01 | Score 35 → approved (abaixo de 40) | LIM_02 (+35) | 35 | ✅ approved |
| DEC-02 | Score 40 → 2FA (limite inferior) | LIM_02 (+40) | 40 | 🔐 2FA |
| DEC-03 | Score 75 → 2FA | LIM_01 (+45), PRF_03 (+30) | 75 | 🔐 2FA |
| DEC-04 | Score 80 → rejected (limite inferior) | LIM_02 (+40), VEL_03 (+40) | 80 | ⛔ rejected |

## Histórias

| ID | Cenário | Regras disparadas | Score | Decisão |
|---|---|---|---|---|
| HIST-01 | Aluguel mensal de R$ 2.500 para o mesmo locador | PRF_01 (+30), CTP_03 (-25) | 5 | ✅ approved |
| HIST-02 | Celular novo, compra de R$ 150 no mercado | — | 0 | ✅ approved |
| HIST-03 | Celular novo, primeira compra de R$ 300 | PRF_02 (+30) | 30 | ✅ approved |
| HIST-04 | Conta invadida: 23h, R$ 2.500, aparelho novo, destino aberto há 2 dias, cliente de ticket R$ 150 | LIM_02 (+40), PRF_01 (+50), PRF_02 (+45), CTP_01 (+45) | 180 | ⛔ rejected |
| HIST-05 | Golpe do falso parente: vítima no próprio celular, de dia, R$ 3.000 para PF que recebeu de 6 pessoas na última hora | PRF_01 (+50), CTP_01 (+25), CTP_02 (+40) | 115 | ⛔ rejected |
| HIST-06 | Golpe com cliente sem histórico recente: só a contraparte aparece | CTP_01 (+25), CTP_02 (+40) | 65 | 🔐 2FA |
| HIST-07 | Conta laranja coletora: PF aberta há 5 dias, 11 pagadores na última hora, R$ 800 | CTP_01 (+25), CTP_02 (+60) | 85 | ⛔ rejected |
| HIST-08 | Sequestro relâmpago: 23h, R$ 5.000, celular da própria vítima | LIM_02 (eliminatória) | 0 | ⛔ rejected |
| HIST-09 | Script esvaziando a conta: 5º Pix de R$ 900 em 3 min, cada um para um destino | VEL_01 (eliminatória), VEL_03 (eliminatória) | 0 | ⛔ rejected |
| HIST-10 | Fracionamento: 3º Pix de R$ 1.900 na mesma hora | MON_01 (+40) | 40 | 🔐 2FA |
| HIST-11 | Empresa pagando 8 fornecedores de R$ 3.000 em 10 min | MON_01 (+40) | 40 | 🔐 2FA |
| HIST-12 | Conta recém-aberta do pagador mandando R$ 3.500 para destino aberto ontem | PRF_05 (+50), CTP_01 (+45) | 95 | ⛔ rejected |
| HIST-13 | Casal dividindo o celular, Pix de R$ 80 | PRF_03 (+30) | 30 | ✅ approved |
| HIST-14 | Fazenda de contas: aparelho com 5 titulares, conta de 2 dias, R$ 1.000 | PRF_03 (+45), PRF_05 (+30) | 75 | 🔐 2FA |
| HIST-15 | Viagem de avião: Pix no Rio 1h depois do último em São Paulo | PRF_04 (+45) | 45 | 🔐 2FA |
| HIST-16 | Salário: cliente transfere R$ 4.000 para a própria conta em outro banco aberta há 1 ano | — | 0 | ✅ approved |

- **HIST-01:** O aluguel destoa do ticket médio (R$ 750) e soma 30, mas o destinatário conhecido tira 25: score 5.
- **HIST-05:** O 2FA não protege no golpe (é o próprio cliente confirmando): por isso contraparte e perfil somam até rejeitar.
- **HIST-06:** Limitação conhecida: sem régua de perfil, o golpe cai em 2FA.
- **HIST-11:** Atrito conhecido: lote grande de PJ pede uma confirmação.
- **HIST-15:** Falso positivo aceito: custa uma confirmação.

## Resumo

122 cenários: 57 approved, 46 two_factor_required, 19 rejected.
