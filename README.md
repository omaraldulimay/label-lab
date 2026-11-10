# Label Lab

Produktdaten Check für Supplements und Proteinprodukte. Gedacht für Fitness Marken, die ihre Produktseiten und Etiketten sauber halten wollen.

## Das Problem

Bei Proteinpulver und Riegeln stecken die Fehler oft in den Daten: Nährwerte fehlen, Zucker ist höher als Kohlenhydrate, die Kalorien passen nicht zu den Makros, ein Allergen steht in den Zutaten, aber nicht in der Deklaration. Dazu kommen Werbeaussagen, die nach der EU Verordnung 1924/2006 nicht zulässig sind. Label Lab prüft das für rund 250 Produkte aus zwei Quellen und zeigt das Ergebnis als Ampel. Die Standardansicht ist der Katalog der Marke RAWFORM, daneben lassen sich rund 200 Supplements von Open Food Facts umschalten.

RAWFORM ist eine fiktive Marke, Name und Texte sind erfunden. Der Katalog (`data/brand_catalog.json`) ist dem Sortiment einer typischen D2C Fitnessmarke nachgebaut.

## Was geprüft wird

1. Lücken: Energie, Fett, Kohlenhydrate, Zucker, Eiweiß, Salz, Zutaten, Portionsgröße.
2. Widersprüche: Zucker über Kohlenhydrate, gesättigte Fette über Fett, Kalorien mehr als 15 % neben der Rechnung aus den Makros (4/4/9 kcal), Werte über 100 g pro 100 g.
3. Allergene: Wortliste der 14 EU Hauptallergene mit Synonymen auf Deutsch und Englisch (Molke, Casein, Laktose gehören zu Milch). Die Zutaten werden mit den deklarierten Allergenen verglichen. Spurenhinweise zählen nicht als Zutat.
4. Claims: Ein lokales Sprachmodell liest den Produkttext, markiert unzulässige Werbeversprechen und schlägt einen zulässigen Ersatztext vor.

Jeder Fund nennt die Rechtsgrundlage. Claim Funde haben die Felder `claim`, `reason`, `rule` (zum Beispiel "Art. 10 Abs. 1 VO (EG) 1924/2006, nicht zugelassene Angabe") und `suggestion`, die Regelprüfungen tragen ein `rule` aus der Lebensmittelinformationsverordnung VO (EU) 1169/2011 (Art. 9, Art. 21, Anhang XV). Alle Texte liegen in Deutsch und Englisch vor (`*_en`), die Produkttexte bleiben Deutsch. Die Prompt Version steht in `labellab/llm.py` (`PROMPT_VERSION`, aktuell 2) und ist Teil des Cache Schlüssels.

Im Dashboard (oben rechts DE/EN) ersetzt "Korrektur übernehmen" die beanstandete Passage im Produkttext durch den Vorschlag. Der Text erscheint als Diff (alt rot durchgestrichen, neu in Gold), die Ampel wird im Browser neu berechnet und springt um. Dafür fällt der übernommene Fund weg, die Regelfunde bleiben. Das setzt voraus, dass der Vorschlag selbst zulässig ist, im Fake Modus prüft das ein Test. Der Zustand liegt nur im Browser (localStorage), "Zurücksetzen" stellt den Ausgang wieder her. Die Logik steht in `web/fix.js` und wird in `tests/test_fix_js.py` mit Node getestet.

Ampel: rot bei mindestens einem Fehler, gelb bei Hinweisen, grün ohne Funde.

## Architektur

```
Markenkatalog (data/brand_catalog.json) + Open Food Facts (data/products.json) -> FastAPI Dienst -> PostgreSQL (Port 5442)
                                                         |  Regeln in Python
                                                         |  Claims: Ollama (lokal)
n8n: holen -> prüfen -> exportieren -> Alarm bei roten Produkten
web/public/results.json -> statisches Dashboard (HTML, JS, CSS)
```

Warum Regeln zuerst: Rechnen, Vergleichen und Wortlisten kann Python exakt, schnell und ohne Kosten. Es braucht dafür kein Modell, und das Ergebnis ist jedes Mal gleich und nachvollziehbar. Das Modell kommt nur dort zum Einsatz, wo es um Sprache geht, also bei der Frage, ob ein Werbesatz zulässig ist und wie er zulässig klingen könnte.

Warum ein lokales Modell: Die Produkttexte verlassen den Rechner nicht, und es fallen keine laufenden Kosten an. Das Modell läuft über Ollama (Standard `qwen2.5:3b`, klein genug für einen Codespace und brauchbar bei Deutsch). Pro Produkt werden Laufzeit und Token (`prompt_eval_count`, `eval_count`) gespeichert, das Dashboard zeigt sie an. Ein Cache über den Hash des Produkttexts sorgt dafür, dass nichts doppelt gerechnet wird.

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
make pull
LLM_MODE=ollama make real        # oder in Docker: LLM_MODE=ollama docker compose up --build
```

Anderes Modell: `OLLAMA_MODEL=...` (zum Beispiel `qwen2.5:7b`), andere Adresse: `OLLAMA_URL=...`.

## In Codespaces ausführen

Wer kein Ollama auf dem eigenen Rechner hat, kann den echten Lauf in GitHub Codespaces machen. Die Datei `.devcontainer/devcontainer.json` richtet Python 3.12, Docker in Docker, Ollama und das Modell `qwen2.5:3b` automatisch ein.

1. Das Repository auf GitHub öffnen, "Code", "Codespaces", "Create codespace on main" wählen. Einen Rechner mit mindestens 4 Kernen und 16 GB Arbeitsspeicher nehmen.
2. Warten, bis das Terminal bereit ist. Das Einrichtungsskript installiert Ollama, lädt `qwen2.5:3b` und führt `make setup` aus (einige Minuten).
3. Prüfen, dass Ollama läuft: `curl localhost:11434/api/tags`. Falls nicht, `ollama serve &` starten.
4. Den echten Lauf starten: `make real`. Er prüft alle Produkte beider Quellen mit dem Modell, auf CPU dauert das einige Minuten bis wenige Dutzend Minuten.
5. Das Ergebnis ansehen: `make run`, danach den weitergeleiteten Port 8080 im Reiter "Ports" öffnen.
6. `web/public/results.json` herunterladen: Datei im Explorer rechts anklicken, "Download". Oder im Terminal `cat web/public/results.json` und lokal einfügen.
7. Lokal die Datei nach `web/public/results.json` kopieren, damit das Dashboard die echten Ergebnisse und keinen Platzhalter zeigt.

Die Ports 8000 (API und Dashboard) und 5678 (n8n) werden ebenfalls weitergeleitet, falls dort `docker compose up --build` laufen soll. Der Codespace sollte danach gelöscht werden, damit keine Stunden weiterlaufen.

Die Ergebnisse in `web/public/results.json` stammen bis zum ersten echten Lauf aus dem Fake Modus. Das Dashboard zeigt dann ein Platzhalter Banner.

## Kosten

API Kosten: 0 €. Es gibt keinen API Key. Es entstehen nur Rechenzeit und Strom auf dem eigenen Rechner. Das Dashboard zeigt "200 Produkte geprüft, 0 € API Kosten, X Minuten lokal" und die Laufzeit pro Produkt.

## Daten und Lizenz

Die Daten der Marke RAWFORM sind fiktiv. Die zweite Quelle sind echte Produktdaten von [Open Food Facts](https://world.openfoodfacts.org), Lizenz ODbL. Der Snapshot `data/products.json` wurde mit `scripts/fetch_off.py` erzeugt und enthält nur Supplements (Proteinpulver, Riegel, Creatin, Aminosäuren, Vitamine und Kapseln, Pre Workout). Open Food Facts wird von Freiwilligen gepflegt, viele Funde sind also echte Datenlücken der Community und keine Fehler der Hersteller. Die Allergen Wortliste ist eine Hilfe und ersetzt keine rechtliche Prüfung.

Code: MIT, siehe `LICENSE`.
