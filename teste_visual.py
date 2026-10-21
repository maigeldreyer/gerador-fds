from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    page = browser.new_page(viewport={"width": 900, "height": 1400})
    page.goto("http://127.0.0.1:5000/")

    # Preenche o formulário
    page.fill("#prod-name", "Detergente Teste")
    page.fill("#prod-use", "Limpeza industrial")

    linhas = page.query_selector_all("#comp-body tr")
    dados = [
        ("Ácido nítrico", "7697-37-2", "6.0"),
        ("Berílio", "7440-41-7", "3.0"),
        ("Água", "7732-18-5", "90.0"),
        ("Ingrediente sem cadastro", "9999-99-9", "1.0"),
    ]
    for tr, (nome, cas, conc) in zip(linhas, dados):
        inputs = tr.query_selector_all("input")
        inputs[0].fill(nome)
        inputs[1].fill(cas)
        inputs[2].fill(conc)

    page.screenshot(path="/home/claude/screenshot_formulario.png", full_page=True)

    page.click("#btn-calcular")
    page.wait_for_selector("#results.visible", timeout=10000)
    page.screenshot(path="/home/claude/screenshot_resultado.png", full_page=True)

    # Checa se apareceu erro de conexão (não deveria)
    erro_visivel = page.eval_on_selector("#connection-error", "el => el.classList.contains('visible')")
    print("Erro de conexão visível (deveria ser False):", erro_visivel)

    browser.close()
