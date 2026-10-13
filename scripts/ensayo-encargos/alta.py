"""Lo que hace el dueño desde /encargos, sin abrir el navegador.

    HUB_HOME=<carpeta-de-ensayo> uv run python scripts/ensayo-encargos/alta.py [alias]

Crea al dueño de prueba, da de alta a la persona de prueba y abre su encargo y
su entrevistador (decisión 229). Los ids son fijos e inventados: son los mismos
que usa `hablar.py`.
"""
import os, sys
from pathlib import Path

SB = Path(os.environ.get("HUB_HOME", "")).resolve()
if not SB.is_dir() or SB == Path.home() / ".local/share/hub":
    sys.exit("HUB_HOME tiene que apuntar a una carpeta de ensayo aparte")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from hub import config, db, encargos, entrevistador  # noqa: E402

DUENO, ELLA = 555000001, 555000002
con = db.conectar(config.DB_PATH); db.inicializar(con)
encargos.anotar_persona(con, DUENO, "dueno_de_prueba", "Quien aprueba")
encargos.marcar_dueno(con, DUENO)
encargos.editar_persona(con, ELLA, estado="activo", alias=(sys.argv[1] if len(sys.argv) > 1 else "Persona de prueba"))
print(entrevistador.empezar_con(con, ELLA))
con.commit()
