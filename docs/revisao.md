# Revisão da política e do banco (v1 → v2)

O que mudou em relação à primeira versão do `project_arstotzka.md` e por quê. Serve de roteiro para defender as escolhas na banca.

## Bugs que impediam o projeto de rodar

| Problema | Efeito | Correção |
|---|---|---|
| `database.sql` terminava com `COMMENT ON TABLE account_risk_profile`, uma tabela que não existe | O script de criação do banco falhava, o container do Postgres não subia e a API nunca ficava de pé | Comentário removido; o cabeçalho que falava em "Feature Store" foi corrigido |
| O código do `sample_entity` continuava na API, mas as tabelas dele tinham saído do schema | Rotas e testes de exemplo quebravam com 500 | `sample_entity` removido; no lugar entraram as rotas, camadas e testes do Pix |
| O motor não existia | — | `src/engine/` (política, regras, decisão) + controller, repository, models, schema, DTO, erros |

## Calibragem: regras que davam a decisão errada

| Regra | Antes | Problema | Agora |
|---|---|---|---|
| `MON_01` | Faixas de 24h sem exigir quantidade mínima | Um único Pix PF de R$ 12.000 somava LIM_01 (+45) e MON_01 (+45) = 90 e era **rejeitado**, embora o LIM_01 diga que essa faixa é de 2FA | Todas as faixas exigem 2+ Pix na janela. Acumulação é de vários Pix; um Pix sozinho é assunto do LIM_01 (cenário MON-08) |
| `CTP_02` | Valia para qualquer destino | Toda loja (PJ) recebe de muitos clientes por hora: o cliente pagando um café cairia em 2FA | Só destino PF (cenário CTP2-05) |
| `VEL_01` / `VEL_03` | Mesmos limites para PF e PJ | Empresa pagando fornecedores ou folha em lote seria rejeitada no 5º Pix | Contagens × 5 para PJ, consistente com o × 5 que o MON_01 já usava |
| `PRF_02` | Dispositivo novo valia também para o primeiro Pix do cliente; +15 por geolocalização ausente | Todo cliente novo estaria num aparelho "novo". E a geolocalização é **opcional** no contrato: penalizar a ausência pune quem usa web | Só avalia quem já tem Pix aprovado; sinal de geolocalização ausente removido; limites alinhados ao Banco Central (R$ 200 por Pix e R$ 1.000 por dia em aparelho não cadastrado) |
| `LIM_02` PF | A partir de R$ 1.000 → +35 | +35 sozinho aprovava, e o texto dizia que os valores não eram regulatórios | Acima de R$ 1.000 → +40 (2FA). R$ 1.000 **é** o limite noturno padrão do BC para PF: acima dele o cliente pediu aumento, então confirmamos |
| `PRF_04` | Sem distância mínima | A imprecisão do GPS (2 km em 10 s = 720 km/h) dispararia a regra à toa | Só avalia a partir de 100 km; compara com o último Pix **aprovado** com geolocalização |
| `PRF_03` | Sem janela de tempo | Contagem "desde sempre": o celular de uma família acumularia titulares e dispararia | Janela de 7 dias |
| `CTP_03` | "desde que critérios de elegibilidade sejam atendidos e não exista condição crítica" | Vago: não dava para implementar nem testar | ≥ 1 Pix aprovado para o mesmo destino há 24h ou mais → −25; eliminatória continua vencendo |

## Definições que faltavam (e agora estão no README e no código)

- **Qual histórico conta:** tentativas (qualquer status) para velocity; aprovados + 2FA para montante; só aprovados para perfil e confiança.
- **O Pix atual entra nas contagens** ("3 ou mais em 2 min" inclui o atual).
- **Limites:** "acima de" é `>`, "a partir de" é `>=`, em centavos.
- **Relógio:** janelas a partir do `transaction_date` do payload; hora noturna no fuso do payload.
- **Perfil do cliente:** por documento, aprovados dos últimos 30 dias: `tx_count_30d`, `total_amount_30d`, `avg_ticket`.
- **Eliminatória:** 0 pontos e `hard_reject = true`, garantido também por CHECK no banco (`ck_hard_reject_no_points`).

## Banco

- Histórico do pagador indexado por **documento** (`source_document`), e não por conta: o perfil é da pessoa.
- `raw_payload jsonb` adicionado, para auditoria (o próprio texto da v1 pedia "os dados necessários para reconstruir a análise").
- `risk_analysis.metadata` guarda exatamente o que a API respondeu: o GET devolve isso, sem recalcular.

## Concorrência: uma afirmação da v1 que estava errada

A v1 dizia que calcular tudo a partir do histórico garantia "consistência transacional absoluta (ACID)… livre de travamentos". **Não garante.** No isolamento padrão do Postgres (read committed), duas análises simultâneas do mesmo pagador não enxergam uma à outra antes do commit, e as duas aprovam. A v2 trava o pagador (`pg_advisory_xact_lock`) do começo ao fim da análise. O teste de concorrência prova a diferença: com a trava, exatamente 2 de 10 Pix simultâneos são aprovados; sem ela, 3 a 5 passaram nas nossas execuções.
