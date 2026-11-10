# Label Lab

Produktdaten Check für Supplements und Proteinprodukte. Gedacht für Fitness Marken, die ihre Produktseiten und Etiketten sauber halten wollen.

## Das Problem

Bei Proteinpulver und Riegeln stecken die Fehler oft in den Daten: Nährwerte fehlen, Zucker ist höher als Kohlenhydrate, die Kalorien passen nicht zu den Makros, ein Allergen steht in den Zutaten, aber nicht in der Deklaration. Dazu kommen Werbeaussagen, die nach der EU Verordnung 1924/2006 nicht zulässig sind. Label Lab prüft das für rund 200 Produkte und zeigt das Ergebnis als Ampel.

## Was geprüft wird

1. Lücken: Energie, Fett, Kohlenhydrate, Zucker, Eiweiß, Salz, Zutaten, Portionsgröße.
2. Widersprüche: Zucker über Kohlenhydrate, gesättigte Fette über Fett, Kalorien mehr als 15 % neben der Rechnung aus den Makros (4/4/9 kcal), Werte über 100 g pro 100 g.
3. Allergene: Wortliste der 14 EU Hauptallergene mit Synonymen auf Deutsch und Englisch (Molke, Casein, Laktose gehören zu Milch). Die Zutaten werden mit den deklarierten Allergenen verglichen. Spurenhinweise zählen nicht als Zutat.
4. Claims: Ein lokales Sprachmodell liest den Produkttext, markiert unzulässige Werbeversprechen und schlägt einen zulässigen Ersatztext vor.

Ampel: rot bei mindestens einem Fehler, gelb bei Hinweisen, grün ohne Funde.

## Architektur

```
Open Food Facts -> data/products.json (Snapshot) -> FastAPI Dienst -> PostgreSQL (Port 5442)
                                                         |  Regeln in Python
                                                         |  Claims: Ollama (lokal)
n8n: holen -> prüfen -> exportieren -> Alarm bei roten Produkten
web/public/results.json -> statisches Dashboard (HTML, JS, CSS)
```

Warum Regeln zuerst: Rechnen, Vergleichen und Wortlisten kann Python exakt, schnell und ohne Kosten. Es braucht dafür kein Modell, und das Ergebnis ist jedes Mal gleich und nachvollziehbar. Das Modell kommt nur dort zum Einsatz, wo es um Sprache geht, also bei der Frage, ob ein Werbesatz zulässig ist und wie er zulässig klingen könnte.

Warum ein lokales Modell: Die Produkttexte verlassen den Rechner nicht, und es fallen keine laufenden Kosten an. Das Modell läuft über Ollama (Standard `qwen2.5:7b`, gut bei Deutsch). Pro Produkt werden Laufzeit und Token (`prompt_eval_count`, `eval_count`) gespeichert, das Dashboard zeigt sie an. Ein Cache über den Hash des Produkttexts sorgt dafür, dass nichts doppelt gerechnet wird.

Der Fake Modus (`LLM_MODE=fake`, Standard) arbeitet mit festen Stichwortregeln und braucht kein Netzwerk. Die Tests laufen damit.

## Start

Ohne Docker, nur das Dashboard mit Fake Ergebnissen:

```
make setup
make run          # http://localhost:8080
make test
make check-all    # Tests, dann alle Produkte im Fake Modus prüfen
```

Alles zusammen mit Docker (Postgres auf 5442, API und Dashboard auf 8000, n8n auf 5678):

```
docker compose up --build
```

In n8n den Workflow "Label Lab Pruefung" öffnen und ausführen. Er lädt die Daten in die Datenbank, prüft alle Produkte, exportiert `web/public/results.json` und meldet rote Produkte an den Dienst (`/alert`, sichtbar im Log).

Echter Lauf mit dem lokalen Modell. Ollama läuft nativ auf dem Mac, nicht in Docker:

```
brew install ollama
ollama serve
ollama pull qwen2.5:7b
LLM_MODE=ollama make real        # oder in Docker: LLM_MODE=ollama docker compose up --build
```

Anderes Modell: `OLLAMA_MODEL=...`, andere Adresse: `OLLAMA_URL=...`.

Die Ergebnisse in `web/public/results.json` stammen bis zum ersten echten Lauf aus dem Fake Modus. Das Dashboard zeigt dann ein Platzhalter Banner.

## Kosten

API Kosten: 0 €. Es gibt keinen API Key. Es entstehen nur Rechenzeit und Strom auf dem eigenen Rechner. Das Dashboard zeigt "200 Produkte geprüft, 0 € API Kosten, X Minuten lokal" und die Laufzeit pro Produkt.

## Daten und Lizenz

Produktdaten von [Open Food Facts](https://world.openfoodfacts.org), Lizenz ODbL. Der Snapshot `data/products.json` wurde mit `scripts/fetch_off.py` erzeugt. Open Food Facts wird von Freiwilligen gepflegt, viele Funde sind also echte Datenlücken der Community und keine Fehler der Hersteller. Die Allergen Wortliste ist eine Hilfe und ersetzt keine rechtliche Prüfung.

Code: MIT, siehe `LICENSE`.
