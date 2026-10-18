-- =====================================================================
-- Project Arstotzka — Motor Antifraude Pix (PostgreSQL 13+)
--
-- Separação de domínios, tudo imutável (só INSERT):
--   1. pix_transaction : o FATO — o Pix como chegou no payload.
--   2. risk_analysis   : o JULGAMENTO — a decisão do motor sobre aquele Pix.
--   3. fraud_rule_hit  : o PORQUÊ — cada regra que disparou, com evidência.
--
-- Não existe tabela de perfil de cliente gravada: o perfil (quantidade,
-- soma e ticket médio dos últimos 30 dias) é calculado na hora, a partir
-- de pix_transaction. Uma janela de 30 dias muda sozinha todo dia; uma
-- tabela com esses números ficaria errada no dia seguinte.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. O FATO: Transação Pix (payload)
-- ---------------------------------------------------------------------
CREATE TABLE pix_transaction (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- identificação e valores
    pix_id                text        NOT NULL,   -- "id" do payload
    payload_hash          text        NOT NULL,   -- SHA-256 do payload (idempotência / 409)
    raw_payload           jsonb       NOT NULL,   -- payload original, para auditoria
    amount                bigint      NOT NULL,   -- em centavos
    transaction_date      timestamptz NOT NULL,
    local_hour            smallint    NOT NULL,   -- hora 0-23 no fuso informado no payload
    received_at           timestamptz NOT NULL DEFAULT now(),

    -- conta origem (o payload não traz ISPB do pagador)
    source_branch         text        NOT NULL,
    source_account_number text        NOT NULL,
    source_document       text        NOT NULL,   -- só dígitos
    source_opening_date   timestamptz NOT NULL,
    source_account_key    text        GENERATED ALWAYS AS (source_branch || ':' || source_account_number) STORED,
    source_person_type    text        GENERATED ALWAYS AS (CASE WHEN length(source_document) = 11 THEN 'PF' ELSE 'PJ' END) STORED,

    -- conta destino
    dest_participant      text        NOT NULL,   -- ISPB
    dest_branch           text        NOT NULL,
    dest_account_number   text        NOT NULL,
    dest_document         text        NOT NULL,   -- só dígitos
    dest_opening_date     timestamptz NOT NULL,
    dest_account_key      text        GENERATED ALWAYS AS (dest_participant || ':' || dest_branch || ':' || dest_account_number) STORED,
    dest_person_type      text        GENERATED ALWAYS AS (CASE WHEN length(dest_document) = 11 THEN 'PF' ELSE 'PJ' END) STORED,

    -- dispositivo / contexto
    device_id             text        NOT NULL,
    channel               text        NOT NULL,
    ip                    inet        NOT NULL,
    latitude              numeric(9,6),
    longitude             numeric(9,6),

    CONSTRAINT uq_pix_transaction_pix_id UNIQUE (pix_id),
    CONSTRAINT ck_amount_positive        CHECK (amount > 0),
    CONSTRAINT ck_local_hour             CHECK (local_hour BETWEEN 0 AND 23),
    CONSTRAINT ck_payload_hash           CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_source_document        CHECK (source_document ~ '^([0-9]{11}|[0-9]{14})$'),
    CONSTRAINT ck_dest_document          CHECK (dest_document   ~ '^([0-9]{11}|[0-9]{14})$'),
    CONSTRAINT ck_dest_participant       CHECK (dest_participant ~ '^[0-9]{8}$'),
    CONSTRAINT ck_geolocation_pair       CHECK ((latitude IS NULL) = (longitude IS NULL)),
    CONSTRAINT ck_latitude_range         CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_longitude_range        CHECK (longitude BETWEEN -180 AND 180)
);

-- ---------------------------------------------------------------------
-- 2. O JULGAMENTO: análise de risco
-- ---------------------------------------------------------------------
CREATE TABLE risk_analysis (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pix_transaction_id bigint      NOT NULL REFERENCES pix_transaction(id),

    analysis_key       uuid        NOT NULL DEFAULT gen_random_uuid(), -- o "key" da resposta
    status             text        NOT NULL,
    score              integer     NOT NULL,
    decided_by         text        NOT NULL,   -- 'hard_rule' ou 'score'
    rules_version      text        NOT NULL,   -- versão da política que decidiu
    metadata           jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- exatamente o que a API respondeu
    analyzed_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_risk_analysis_pix      UNIQUE (pix_transaction_id),
    CONSTRAINT uq_analysis_key           UNIQUE (analysis_key),
    CONSTRAINT ck_status                 CHECK (status IN ('approved', 'two_factor_required', 'rejected')),
    CONSTRAINT ck_score_non_negative     CHECK (score >= 0),
    CONSTRAINT ck_decided_by             CHECK (decided_by IN ('hard_rule', 'score')),
    CONSTRAINT ck_hard_rule_rejects      CHECK (decided_by <> 'hard_rule' OR status = 'rejected')
);

-- ---------------------------------------------------------------------
-- 3. O PORQUÊ: regras acionadas
-- ---------------------------------------------------------------------
CREATE TABLE fraud_rule_hit (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    risk_analysis_id bigint  NOT NULL REFERENCES risk_analysis(id),

    rule_code        text    NOT NULL,
    rule_family      text    NOT NULL,
    points           integer NOT NULL,          -- negativo nos redutores (CTP_03)
    is_hard_reject   boolean NOT NULL DEFAULT false,
    reason           text    NOT NULL,
    evidence         jsonb   NOT NULL DEFAULT '{}'::jsonb,  -- valor observado x parâmetro

    CONSTRAINT uq_rule_hit_per_analysis UNIQUE (risk_analysis_id, rule_code),
    CONSTRAINT ck_rule_code             CHECK (rule_code ~ '^[A-Z]{3}_[0-9]{2}$'),
    CONSTRAINT ck_rule_family           CHECK (rule_family IN ('INTEGRIDADE', 'LIMITE', 'VELOCITY', 'MONTANTE', 'PERFIL', 'CONTRAPARTE')),
    CONSTRAINT ck_hard_reject_no_points CHECK (NOT is_hard_reject OR points = 0)
);

-- =====================================================================
-- Índices — cada um existe porque uma consulta de contexto usa
-- =====================================================================

-- Histórico do PAGADOR (por documento): VEL_01, VEL_02, VEL_03, MON_01,
-- perfil de 30 dias (PRF_01), dispositivo conhecido (PRF_02), último
-- ponto geográfico (PRF_04) e contraparte conhecida (CTP_03).
CREATE INDEX ix_pix_source_doc_date
    ON pix_transaction (source_document, transaction_date DESC)
    INCLUDE (amount, dest_account_key, device_id);

-- Histórico do DESTINO: concentração de recebimentos (CTP_02).
CREATE INDEX ix_pix_dest_date
    ON pix_transaction (dest_account_key, transaction_date DESC)
    INCLUDE (source_document);

-- Histórico do DISPOSITIVO: dispositivo compartilhado (PRF_03).
CREATE INDEX ix_pix_device_date
    ON pix_transaction (device_id, transaction_date DESC)
    INCLUDE (source_document);

-- Calibração da política: quantas vezes cada regra disparou.
CREATE INDEX ix_rule_hit_rule_code ON fraud_rule_hit (rule_code);
CREATE INDEX ix_rule_hit_analysis  ON fraud_rule_hit (risk_analysis_id);

-- =====================================================================
-- Imutabilidade: histórico só aceita INSERT
-- =====================================================================

CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Registros da tabela % são imutáveis (apenas INSERT é permitido)', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER trg_pix_transaction_immutable
    BEFORE UPDATE OR DELETE ON pix_transaction
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TRIGGER trg_risk_analysis_immutable
    BEFORE UPDATE OR DELETE ON risk_analysis
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TRIGGER trg_fraud_rule_hit_immutable
    BEFORE UPDATE OR DELETE ON fraud_rule_hit
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- =====================================================================
-- Comentários
-- =====================================================================

COMMENT ON TABLE pix_transaction IS 'Fato ocorrido: dados de um Pix recebido, como chegou (imutável).';
COMMENT ON TABLE risk_analysis   IS 'Decisão do motor para uma transação: status, score e metadata respondida (imutável).';
COMMENT ON TABLE fraud_rule_hit  IS 'Evidências: cada regra disparada em uma análise, com o valor observado (imutável).';
