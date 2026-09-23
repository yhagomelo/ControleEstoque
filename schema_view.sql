-- =====================================================================
-- View de conciliação de estoque de EPIs: Gmcore x RSData
-- Compatível com SQLite e PostgreSQL (FULL OUTER JOIN emulado com
-- LEFT JOIN + anti-join, para funcionar também em SQLite antigo).
--
-- Tabelas esperadas (nomes normalizados):
--   gmcore (empresa, filial, departamento, secao, cod_gm, produto_gm, estoque_gm)
--   rsdata (empresa, filial, local_estoque, produto, ca, tamanho, quantidade_rs)
--   depara (ca, cod_int_produto, cod_gm, key)      -- key = CA|Produto|Tamanho
-- =====================================================================

DROP VIEW IF EXISTS vw_conciliacao;

CREATE VIEW vw_conciliacao AS
WITH
-- De-Para visto pelo lado Gmcore: cod_gm -> chave
dp_gm AS (
    SELECT UPPER(TRIM(cod_gm)) AS cod_gm,
           MIN(UPPER(TRIM("key"))) AS chave
    FROM depara
    WHERE cod_gm IS NOT NULL
    GROUP BY UPPER(TRIM(cod_gm))
),
-- De-Para visto pelo lado RSData: lista de chaves cadastradas
dp_rs AS (
    SELECT DISTINCT UPPER(TRIM("key")) AS chave
    FROM depara
    WHERE "key" IS NOT NULL
),
-- Gmcore agregado por filial + chave (chave NULL = sem De-Para)
gm AS (
    SELECT UPPER(TRIM(g.filial))     AS filial,
           d.chave                   AS chave,
           UPPER(TRIM(g.cod_gm))     AS cod_gm,
           MAX(g.produto_gm)         AS produto_gm,
           SUM(g.estoque_gm)         AS qtd_gm
    FROM gmcore g
    LEFT JOIN dp_gm d ON d.cod_gm = UPPER(TRIM(g.cod_gm))
    GROUP BY UPPER(TRIM(g.filial)), d.chave, UPPER(TRIM(g.cod_gm))
),
rs0 AS (
    SELECT UPPER(TRIM(filial)) AS filial,
           UPPER(TRIM(ca) || '|' || TRIM(produto) || '|' || TRIM(COALESCE(tamanho, ''))) AS chave_calc,
           ca, produto, COALESCE(tamanho, '') AS tamanho, quantidade_rs
    FROM rsdata
),
-- RSData agregado por filial + chave (chave NULL = sem De-Para)
rs AS (
    SELECT r.filial,
           d.chave                   AS chave,
           r.ca                      AS ca,
           MAX(r.produto)            AS produto_rs,
           MAX(r.tamanho)            AS tamanho,
           SUM(r.quantidade_rs)      AS qtd_rs
    FROM rs0 r
    LEFT JOIN dp_rs d ON d.chave = r.chave_calc
    GROUP BY r.filial, d.chave, r.chave_calc, r.ca
),
cruzado AS (
    -- 1) Tudo do Gmcore com chave (com ou sem par no RSData)
    SELECT g.filial, g.chave, g.cod_gm, g.produto_gm, g.qtd_gm,
           r.ca, r.produto_rs, r.tamanho, r.qtd_rs
    FROM gm g
    LEFT JOIN rs r ON r.filial = g.filial AND r.chave = g.chave
    WHERE g.chave IS NOT NULL
    UNION ALL
    -- 2) RSData com chave que não existe no Gmcore (anti-join)
    SELECT r.filial, r.chave, NULL, NULL, NULL,
           r.ca, r.produto_rs, r.tamanho, r.qtd_rs
    FROM rs r
    WHERE r.chave IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM gm g WHERE g.filial = r.filial AND g.chave = r.chave)
    UNION ALL
    -- 3) Gmcore sem De-Para
    SELECT g.filial, NULL, g.cod_gm, g.produto_gm, g.qtd_gm,
           NULL, NULL, NULL, NULL
    FROM gm g
    WHERE g.chave IS NULL
    UNION ALL
    -- 4) RSData sem De-Para
    SELECT r.filial, NULL, NULL, NULL, NULL,
           r.ca, r.produto_rs, r.tamanho, r.qtd_rs
    FROM rs r
    WHERE r.chave IS NULL
)
SELECT
    filial,
    chave,
    COALESCE(cod_gm, ca)                          AS codigo_epi,
    ca,
    tamanho,
    produto_gm,
    COALESCE(qtd_gm, 0)                           AS qtd_gm,
    produto_rs,
    COALESCE(qtd_rs, 0)                           AS qtd_rs,
    COALESCE(qtd_gm, 0) - COALESCE(qtd_rs, 0)     AS diferenca,
    CASE
        WHEN chave IS NULL                        THEN '⚠️ SEM DE-PARA'
        WHEN qtd_rs IS NULL                       THEN '🔵 APENAS NO GMCORE'
        WHEN qtd_gm IS NULL                       THEN '🔴 APENAS NO RSDATA'
        WHEN qtd_gm = qtd_rs                      THEN '🟢 OK'
        ELSE                                           '🟡 DIVERGENTE'
    END                                           AS status_conciliacao
FROM cruzado;
