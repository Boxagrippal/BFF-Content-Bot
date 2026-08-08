# BFF Content Bot

Erzeugt jede Nacht automatisch ein fertiges Postbild (Bild + Spruch + Logo)
fuer Battlefield for Friends und legt es in einem Dropbox-Ordner ab.
Postet NICHT selbststaendig - Upload auf Instagram/Facebook macht der
Nutzer weiterhin von Hand.

Einmal pro Woche (Standard: Mittwoch) wird statt einem Einzelbild eine
4-teilige Story mit Cliffhanger erzeugt.

## Was du brauchst

- OpenAI API-Schluessel (platform.openai.com)
- Dropbox-Konto + eine Dropbox-App (siehe unten)
- Render.com-Konto, verbunden mit diesem GitHub-Repository

## Dropbox einrichten

1. Auf https://www.dropbox.com/developers/apps auf "Create app" klicken.
2. "Scoped access" waehlen, Zugriffstyp "App folder", einen beliebigen
   Namen vergeben (z.B. "BFF Content Bot").
3. Im Reiter "Permissions" die Haekchen bei `files.content.write` und
   `files.content.read` setzen, dann "Submit".
4. Im Reiter "Settings" stehen App key und App secret - beide notieren.
5. Dort auch bei "OAuth 2" auf "Generate" klicken, um einmalig einen
   Autorisierungscode/Refresh-Token zu erzeugen (Anleitung dazu in den
   Dropbox-Entwicklerdoku, oder ich helfe dir Schritt fuer Schritt live).

Am Ende brauchst du drei Werte: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`,
`DROPBOX_REFRESH_TOKEN`.

Die Bilder landen dann automatisch im Dropbox-Ordner `/Apps/BFF Content Bot/BFF-Content`.

## Render einrichten

1. Neues "Blueprint" auf Render anlegen und dieses GitHub-Repo auswaehlen
   (die Datei `render.yaml` wird automatisch erkannt).
2. Bei den Umgebungsvariablen die vier Werte eintragen:
   `OPENAI_API_KEY`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`,
   `DROPBOX_REFRESH_TOKEN`.
3. Render fuehrt den Job danach automatisch jede Nacht um 3 Uhr UTC aus.

## Events anpassen

Alle Events, Szenen-Bausteine und Beispiel-Sprueche stehen in
`events_config.json`. Ein neues Event hinzufuegen = neuer Eintrag in der
Liste, kein Code-Aendern noetig.
