from navegador.flujo import convertir, paso_de_linea, sustituir

GRABACION = """await page.goto('http://127.0.0.1:8790/login');
await page.getByRole('textbox', { name: 'Usuario' }).fill('usuario');
await page.getByRole('textbox', { name: 'Contraseña' }).fill('hunter2');
await page.getByRole('checkbox', { name: '/aws/lambda/pedidos-crear' }).check();
await page.getByRole('textbox', { name: 'Editor de consultas' }).click();
await page.getByRole('textbox', { name: 'Editor de consultas' }).press('ControlOrMeta+a');
await page.getByRole('textbox', { name: 'Editor de consultas' }).fill('fields @message | limit 5');
await page.getByRole('button', { name: 'Ejecutar consulta' }).click();
await page.frameLocator('#x').getByText('y').click();"""


def test_lo_tecleado_en_un_campo_de_contrasena_no_llega_al_flujo():
    c = convertir(GRABACION, "f")
    assert "hunter2" not in repr(c.flujo)
    assert c.flujo["parametros"]["secreto_1"] == {"secreto": True}
    assert any("secreto" in a for a in c.avisos)


def test_los_parametros_sustituyen_cada_aparicion_del_valor():
    c = convertir(GRABACION, "f", parametros={"base": "http://127.0.0.1:8790",
                                              "grupo": "/aws/lambda/pedidos-crear"})
    assert c.flujo["pasos"][0] == {"ir": "{{base}}/login"}
    assert {"marcar": {"rol": "checkbox", "nombre": "{{grupo}}"}} in c.flujo["pasos"]


def test_pulsar_y_seleccionar_todo_antes_de_rellenar_se_colapsa_en_rellenar():
    pasos = convertir(GRABACION, "f").flujo["pasos"]
    editor = [p for p in pasos if "Editor de consultas" in repr(p)]
    assert editor == [{"rellenar": {"rol": "textbox", "nombre": "Editor de consultas",
                                    "valor": "fields @message | limit 5"}}]


def test_lo_que_no_entiende_lo_deja_fuera_y_lo_dice():
    c = convertir(GRABACION, "f")
    assert not any("frameLocator" in repr(p) for p in c.flujo["pasos"])
    assert any("frameLocator" in a for a in c.avisos)


def test_un_parametro_que_no_aparece_se_avisa_en_vez_de_declararse():
    c = convertir(GRABACION, "f", parametros={"region": "eu-west-1"})
    assert "region" not in c.flujo["parametros"]
    assert any("region" in a for a in c.avisos)


def test_entiende_comillas_escapadas_nth_y_exact():
    p = paso_de_linea("""await page.getByRole('link', { name: 'it\\'s', exact: true }).nth(2).click();""")
    assert p == {"pulsar": {"rol": "link", "nombre": "it's", "exacto": True, "n": 2}}


def test_sustituir_deja_para_el_bucle_las_variables_con_punto_y_exige_las_demas():
    assert sustituir("{{base}}/{{api.ID}}", {"base": "b"}) == "b/{{api.ID}}"
    try:
        sustituir("{{falta}}", {})
    except KeyError:
        pass
    else:
        raise AssertionError


def test_componer_une_fragmentos_y_junta_sus_parametros():
    from navegador.flujo import componer
    a = {"nombre": "lista", "coleccion": "lab", "pantallas": {"desde": "consola", "hasta": "lista"},
         "parametros": {"base": {}, "region": {"defecto": "us-east-1"}}}
    b = {"nombre": "detalle", "coleccion": "lab", "pantallas": {"desde": "lista", "hasta": "detalle"},
         "parametros": {"api": {}, "secreto_1": {"secreto": True}}}
    c = componer("todo", [a, b])
    assert c.avisos == []
    assert set(c.flujo["parametros"]) == {"base", "region", "api"}
    assert c.flujo["pantallas"] == {"desde": "consola", "hasta": "detalle"}
    assert c.flujo["pasos"][1] == {"usar": {"flujo": "lab/detalle", "con": {"api": "{{api}}"}}}


def test_componer_avisa_cuando_un_fragmento_no_empieza_donde_acaba_el_anterior():
    from navegador.flujo import componer
    a = {"nombre": "lista", "pantallas": {"desde": "consola", "hasta": "lista"}}
    b = {"nombre": "logs", "pantallas": {"desde": "logs-insights", "hasta": "logs-insights"}}
    c = componer("raro", [a, b])
    assert len(c.avisos) == 1 and "lista" in c.avisos[0] and "logs-insights" in c.avisos[0]


def test_el_mapa_cuelga_de_cada_pantalla_los_fragmentos_que_salen_de_ella(tmp_path, monkeypatch):
    import yaml
    from navegador import config
    d = tmp_path / "f"; d.mkdir()
    for n, p in (("a", {"desde": "x", "hasta": "y"}), ("b", {"desde": "x"}), ("c", {})):
        (d / f"{n}.yml").write_text(yaml.safe_dump({"nombre": n, "pantallas": p, "pasos": []}))
    monkeypatch.setattr(config, "cargar", lambda: {"colecciones": [{"nombre": "t", "ruta": str(d)}], "politicas": []})
    m = config.mapa()
    assert [c["flujo"] for c in m["salen"]["x"]] == ["t/a", "t/b"]
    assert {c["flujo"]: c["hasta"] for c in m["caminos"]} == {"t/a": "y", "t/b": "x"}
    assert m["sin_pantalla"] == ["t/c"]
