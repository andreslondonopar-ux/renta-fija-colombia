name: Actualizar Curva UST

on:
  schedule:
    # 5pm Colombia (UTC-5) = 22:00 UTC, lunes a viernes
    # Después del cierre del mercado USA (4pm ET = 9pm UTC)
    - cron: '0 22 * * 1-5'
  workflow_dispatch:

jobs:
  update-ust:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Instalar dependencias
        run: pip install requests

      - name: Correr scraper UST
        run: python scraper_ust.py

      - name: Mostrar resultado
        run: |
          echo "=== ust_data.json ==="
          cat ust_data.json
          echo ""
          echo "=== UST en macro_data.json ==="
          python3 -c "import json; d=json.load(open('macro_data.json')); print(json.dumps(d.get('ust',{}), indent=2))" 2>/dev/null || echo "macro_data.json no disponible"

      - name: Commit y push
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add ust_data.json macro_data.json
          git diff --staged --quiet || git commit -m "auto: curva UST $(date -u '+%Y-%m-%d %H:%M UTC')"
          git push
