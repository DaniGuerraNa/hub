"""Un procedimiento almacenado de muestra, largo y realista, para el simulador.

Se genera con semilla fija: el mismo texto en cada arranque, así una lectura
de la demo se puede repetir y comparar. Lleva lo que complica leer de una
captura —acentos, ñ, comillas, corchetes, sangrías de varios niveles, 0/O y
1/l juntos— porque un ejemplo fácil no prueba nada.
"""

from __future__ import annotations

import random

_TIPOS = [
    ("FAC", "factura"), ("NCR", "nota de crédito"), ("NDB", "nota de débito"),
    ("REC", "recibo"), ("ANT", "anticipo"), ("DEV", "devolución"),
    ("AJU", "ajuste"), ("TRS", "traspaso"), ("CMP", "compensación"),
    ("RET", "retención"), ("PEN", "penalización"), ("BON", "bonificación"),
]
_CUENTAS = ["1100", "1105", "1200", "2010", "2105", "4001", "4010", "5100", "5105", "6001"]
_ESTADOS = ["'PEND'", "'CONC'", "'RECH'", "'REV'", "'ANUL'"]


def procedimiento(lineas_objetivo: int = 2000, semilla: int = 11) -> list[str]:
    r = random.Random(semilla)
    L: list[str] = []
    L += [
        "CREATE OR ALTER PROCEDURE [dbo].[usp_ConciliarMovimientos]",
        "    @FechaCorte        DATE,",
        "    @IdEmpresa         INT,",
        "    @Usuario           NVARCHAR(50) = N'sistema',",
        "    @SoloSimular       BIT = 0,",
        "    @Resultado         INT OUTPUT",
        "AS",
        "/*",
        "    Concilia los movimientos del día contra el libro mayor.",
        "    - Agrupa por tipo de documento y cuenta contable.",
        "    - Marca como 'CONC' lo que cuadra; lo demás queda en 'PEND' con su motivo.",
        "    - Con @SoloSimular = 1 no escribe nada: sólo devuelve el resumen.",
        "    Nota: el año fiscal empieza en julio (ver dbo.fn_AnioFiscal).",
        "*/",
        "BEGIN",
        "    SET NOCOUNT ON;",
        "    SET XACT_ABORT ON;",
        "",
        "    DECLARE @Inicio       DATETIME2(3) = SYSUTCDATETIME();",
        "    DECLARE @Lote         UNIQUEIDENTIFIER = NEWID();",
        "    DECLARE @Total        DECIMAL(18, 2) = 0;",
        "    DECLARE @Diferencia   DECIMAL(18, 2) = 0;",
        "    DECLARE @Filas        INT = 0;",
        "    DECLARE @Mensaje      NVARCHAR(4000) = N'';",
        "",
        "    IF @FechaCorte IS NULL OR @IdEmpresa IS NULL",
        "    BEGIN",
        "        RAISERROR(N'Faltan parámetros: @FechaCorte e @IdEmpresa son obligatorios.', 16, 1);",
        "        RETURN;",
        "    END;",
        "",
        "    CREATE TABLE #Movimientos (",
        "        IdMovimiento   BIGINT         NOT NULL PRIMARY KEY,",
        "        TipoDoc        CHAR(3)        NOT NULL,",
        "        Cuenta         VARCHAR(10)    NOT NULL,",
        "        Importe        DECIMAL(18, 2) NOT NULL,",
        "        Estado         CHAR(4)        NOT NULL DEFAULT 'PEND',",
        "        Motivo         NVARCHAR(200)  NULL",
        "    );",
        "",
    ]
    bloque = 0
    while len(L) < lineas_objetivo - 40:
        codigo, nombre = _TIPOS[bloque % len(_TIPOS)]
        bloque += 1
        cuenta = r.choice(_CUENTAS)
        tolerancia = r.choice(["0.01", "0.10", "1.00", "0.05"])
        dias = r.randint(1, 45)
        L += [
            f"    /* -- Bloque {bloque:03d}: {nombre} ({codigo}) --------------------------- */",
            f"    INSERT INTO #Movimientos (IdMovimiento, TipoDoc, Cuenta, Importe)",
            f"    SELECT m.IdMovimiento, m.TipoDoc, m.Cuenta, m.Importe",
            f"    FROM   dbo.Movimientos AS m WITH (NOLOCK)",
            f"    WHERE  m.IdEmpresa = @IdEmpresa",
            f"      AND  m.TipoDoc = '{codigo}'",
            f"      AND  m.Fecha BETWEEN DATEADD(DAY, -{dias}, @FechaCorte) AND @FechaCorte",
            f"      AND  m.Cuenta IN ('{cuenta}', '{r.choice(_CUENTAS)}');",
            "",
            f"    SELECT @Total = ISNULL(SUM(Importe), 0), @Filas = COUNT(*)",
            f"    FROM   #Movimientos",
            f"    WHERE  TipoDoc = '{codigo}';",
            "",
            f"    IF @Filas > 0",
            f"    BEGIN",
            f"        SELECT @Diferencia = @Total - ISNULL(SUM(l.Saldo), 0)",
            f"        FROM   dbo.LibroMayor AS l",
            f"        WHERE  l.IdEmpresa = @IdEmpresa AND l.Cuenta = '{cuenta}'",
            f"          AND  l.Periodo = dbo.fn_Periodo(@FechaCorte);",
            "",
            f"        IF ABS(@Diferencia) <= {tolerancia}",
            f"        BEGIN",
            f"            UPDATE #Movimientos SET Estado = 'CONC', Motivo = NULL",
            f"            WHERE  TipoDoc = '{codigo}';",
            f"        END",
            f"        ELSE",
            f"        BEGIN",
            f"            UPDATE #Movimientos",
            f"            SET    Estado = 'PEND',",
            f"                   Motivo = CONCAT(N'Diferencia en {nombre}: ', @Diferencia)",
            f"            WHERE  TipoDoc = '{codigo}';",
        ]
        if r.random() < 0.5:
            L += [
                f"",
                f"            -- Señal para revisión manual si la diferencia supera el {r.randint(1, 9)}0 %",
                f"            IF ABS(@Diferencia) > @Total * 0.{r.randint(1, 9)}0",
                f"                INSERT INTO dbo.Alertas (Lote, TipoDoc, Texto, Usuario)",
                f"                VALUES (@Lote, '{codigo}', N'Revisar {nombre} [{cuenta}]', @Usuario);",
            ]
        L += [
            f"        END;",
            f"    END;",
            "",
        ]
        if r.random() < 0.3:
            estado = r.choice(_ESTADOS)
            L += [
                f"    -- Los {nombre}s anulados no cuentan (ticket 1O-{r.randint(100, 999)}: «O» de Oficina, no cero)",
                f"    DELETE FROM #Movimientos WHERE TipoDoc = '{codigo}' AND Estado = {estado};",
                "",
            ]
    L += [
        "    IF @SoloSimular = 0",
        "    BEGIN",
        "        BEGIN TRY",
        "            BEGIN TRANSACTION;",
        "",
        "            UPDATE m",
        "            SET    m.Estado = t.Estado,",
        "                   m.Motivo = t.Motivo,",
        "                   m.LoteConciliacion = @Lote,",
        "                   m.ModificadoPor = @Usuario",
        "            FROM   dbo.Movimientos AS m",
        "            JOIN   #Movimientos    AS t ON t.IdMovimiento = m.IdMovimiento;",
        "",
        "            SET @Resultado = @@ROWCOUNT;",
        "            COMMIT TRANSACTION;",
        "        END TRY",
        "        BEGIN CATCH",
        "            IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;",
        "            SET @Mensaje = CONCAT(N'Falló la conciliación: ', ERROR_MESSAGE());",
        "            THROW 50001, @Mensaje, 1;",
        "        END CATCH;",
        "    END",
        "    ELSE",
        "        SET @Resultado = (SELECT COUNT(*) FROM #Movimientos);",
        "",
        "    SELECT TipoDoc, Estado, COUNT(*) AS Filas, SUM(Importe) AS Importe",
        "    FROM   #Movimientos",
        "    GROUP BY TipoDoc, Estado",
        "    ORDER BY TipoDoc, Estado;",
        "",
        "    DROP TABLE #Movimientos;",
        "END;",
    ]
    return L
