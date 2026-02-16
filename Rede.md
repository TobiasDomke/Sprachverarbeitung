# Sprechtext – Hybrid-Sprachassistent (Vosk + Gemini + TTS)

> **Hinweis für dich beim Vortragen:** Sprich in kurzen Sätzen. Vermeide Performance-Behauptungen (ms, WER etc.), außer du zeigst echte Messwerte. Markiere klar „Prototyp / Implementationsdemo“.


---

## Folie 1 – Titel / Einordnung („Hybrid-Sprachassistent“)

### Block: „Hybrid“ (Vosk lokal → Gemini Cloud → TTS optional)
Was ich sage:
- „Der Assistent ist **hybrid** aufgebaut: **Spracherkennung lokal** mit Vosk, **Antwortgenerierung** über Gemini in der Cloud, und **Sprachausgabe** optional per TTS.“
- „Hybrid heißt: **Roh-Audio bleibt lokal**; in die Cloud geht nur der **erkannte Text** (und optional TTS-Text, wenn edge-tts genutzt wird).“

Codebezug (Daten/Module):
- Vosk: `Model(...)`, `KaldiRecognizer(...)` (deutsches Modell z. B. `vosk-model-small-de-0.15`)
- Gemini: `client = genai.Client(api_key=...)`, `client.chats.create(model=GEMINI_MODEL, config=...)`
- TTS: edge-tts (optional) oder pyttsx3 (optional)

### Block: „Thread-sichere Session“
Was ich sage:
- „Die Pipeline läuft parallelisiert. Deshalb ist Session-Konsistenz wichtig: **State + Session-ID** werden thread-sicher verwaltet.“

Codebezug (Projektfunktionen):
- `SessionState(active, session_id)` (Dataclass)
- `state_lock` schützt `session_state.active` und `session_state.session_id`

### Block: Wissenschaftlicher Hinweis (Korrektheit)
Was ich sage:
- „Wichtig: Die Präsentation beschreibt **nur Funktionen**, die im Code implementiert sind.“
- „Konkrete Latenz-/RAM-/Speicherzahlen nenne ich **nicht als Fakten**, weil der Code diese Werte nicht misst.“

---

## Folie 2 – Agenda / Struktur

### Block: Inhalt (1–6)
Was ich sage:
- „Ich gehe in sechs Teilen vor: Motivation, Ziele/Forschungsfragen, Systemdesign, Implementationsdetails, Grenzen/Evaluation, Fazit/Ausblick.“

### Block: Artefakt (Implementationsform)
Was ich sage:
- „Das Artefakt ist ein **Python-Script**: STT/Wake über Vosk, Antwortgenerierung über Gemini-Chat, TTS über edge-tts oder pyttsx3.“

Codebezug:
- Datei/Programmstruktur: ein laufendes Script mit Audio-Stream + Worker-Threads

---

## Folie 3 – Motivation & Problemraum

### Block: Lokale Signal-/Sprachverarbeitung
Was ich sage:
- „Wake-Phrase und Diktat können lokal laufen. Dadurch muss **kein Roh-Audio** in die Cloud.“
- „Das reduziert Cloud-Abhängigkeit auf die reine Text-Semantik.“

Codebezug (Datenfluss):
- Audio wird als **PCM int16** verarbeitet (`dtype="int16"`, `SAMPLE_RATE=16000`, `CHANNELS=1`)
- Roh-Audio wird lokal in `audio_q` gepuffert und durch Vosk verarbeitet

### Block: Cloud-LLM als Wissens-/Dialogkomponente
Was ich sage:
- „Für flexible, inhaltliche Antworten nutze ich ein Cloud-LLM (Gemini) über eine **Chat-Session**.“
- „Der Output wird über System-Instructions so begrenzt, dass er gut für Voice passt (kurz, deutsch, nicht halluzinieren).“

Codebezug (Projektfunktionen/Daten):
- `GEMINI_MODEL = "gemini-2.5-flash"`
- `GenerateContentConfig(... system_instruction=INSTRUCTIONS, max_output_tokens=..., temperature=0.35, top_p=0.95 ...)`

### Block: Systemrobustheit im Streaming-Betrieb
Was ich sage:
- „Streaming-Audio + Threads + Ausfälle (Netz/Quota) brauchen saubere Zustands- und Fehlerlogik.“

Codebezug:
- Thread-Entkopplung: Audio-Loop + Gemini-Worker + TTS-Worker
- Fehlerpfade: Retry/Backoff (transient), Quota-Erkennung (abbrechen + aufräumen)

### Block: Projektfokus (aus dem Code ableitbar)
Was ich sage:
- „Im Fokus stehen: definierte Wake/Sleep/Exit-Phrasen, Parallelisierung, Session-Invalidierung via `session_id` und Retry/Backoff.“

---

## Folie 4 – Zielsetzung & Forschungsfragen

### Block: Zielsetzung (klar, ohne Leistungsversprechen)
Was ich sage:
- „Ziel ist ein prototypischer Sprachassistent, der **Vosk lokal** + **Gemini Cloud** kombiniert und optional **TTS** bietet.“

Codebezug:
- STT lokal: Vosk
- LLM: Gemini-Chat
- TTS: edge-tts/pyttsx3 (optional)

### Block: Nicht-Ziele (transparent)
Was ich sage:
- „Kein vollständig offline-LLM im aktuellen Code.“
- „Keine integrierte automatische Latenz-/Qualitätsmessung.“

### Block: Forschungsfragen (projektbezogen)
Was ich sage:
- **F1:** „Wie realisiere ich Wake-Phrase und Diktat lokal ohne Cloud-STT?“  
- **F2:** „Welche Architektur entkoppelt Audioaufnahme, LLM und TTS robust (Queues/Threads)?“  
- **F3:** „Wie handhabe ich Session-Konsistenz und Fehlerszenarien (Retry/Quota) in laufender Interaktion?“

---

## Folie 5 – Pipeline-Übersicht (Signalfluss)

### Block: Audio → `audio_q`
Was ich sage:
- „Audio kommt über `sounddevice.RawInputStream` rein und wird als Bytes in **`audio_q`** gepuffert.“

Codebezug (Daten):
- `SAMPLE_RATE=16000`, `CHANNELS=1`, `BLOCKSIZE=4000`, `dtype="int16"`
- `audio_callback(...)` schreibt Frames nach `audio_q`

### Block: Wake/Sleep/Exit (Vosk mit Grammar)
Was ich sage:
- „Ein Vosk-Recognizer mit **Grammar** erkennt Steuerphrasen.“
- „Damit steuere ich Aktivierung/Deaktivierung/Beenden.“

Codebezug (Projektfunktionen/Daten):
- Phrasen (de):  
  - Wake: **„hallo michaela“**  
  - Sleep: **„danke michaela“**  
  - Exit: **„kill switch aktivieren“**
- Bei Erkennung werden Control-Tokens erzeugt: `__WAKE__`, `__SLEEP__`, `__EXIT__`

### Block: Diktat → `text_q`
Was ich sage:
- „Im ACTIVE-Modus läuft freies Diktat. Final erkannter Text geht in **`text_q`**.“

Codebezug:
- `text_q` enthält **Diktattexte** *und* interne Tokens (z. B. `__WAKE__`, `__SLEEP__`, `__EXIT__`), damit Worker sauber gesteuert werden

### Block: LLM (Gemini) → Antworttext
Was ich sage:
- „Der Gemini-Worker liest aus `text_q`, ruft Gemini auf und erzeugt Antworttext.“

### Block: TTS → `tts_q` → Ausgabe
Was ich sage:
- „Antworttexte gehen optional in **`tts_q`** und werden dort vom TTS-Worker gesprochen.“

Codebezug:
- `tts_q` enthält **Antworttexte** *und* Kontrollsignale wie `__STOP__`/`__EXIT__`

### Block: Datenschutz-Transparenz
Was ich sage:
- „Audio bleibt lokal. Für die Antwortgenerierung wird **nur Text** an Gemini geschickt. Bei edge-tts kann zusätzlich Text für TTS in die Cloud gehen.“

---

## Folie 6 – Architektur & Parallelisierung (Threads + Queues)

### Block: Main Loop (Audio)
Was ich sage:
- „Die Audio-Main-Loop hält den Stream am Laufen und darf nicht blockieren.“
- „Sie verarbeitet Audio-Frames, erkennt Wake/Sleep/Exit und erzeugt Diktattexte.“

Codebezug (Projektfunktionen):
- Audio: `sounddevice.RawInputStream(... callback=audio_callback)`
- Zustandsvariablen: `session_state.active`, `session_state.session_id` (unter `state_lock`)
- Gatekeeping:
  - `dictation_block_until` (Arming/Cooldown)
  - `tts_busy_evt` (unterdrückt Diktat während Sprachausgabe)

### Block: Gemini-Worker
Was ich sage:
- „Der Gemini-Worker ist ein separater Thread: Er konsumiert `text_q` und macht Cloud-Calls.“
- „Bei Wake wird eine neue Chat-Session erzeugt; bei Sleep wird sie verworfen.“
- „Retry/Backoff stabilisiert transiente Fehler; Quota-Fehler werden erkannt und führen zu Aufräumen statt Endlosschleife.“

Codebezug:
- `client.chats.create(...)` erzeugt Chat
- `__WAKE__` → Chat neu
- `__SLEEP__` → Chat = None
- Retry/Backoff-Logik + Quota-Handling

### Block: TTS-Worker
Was ich sage:
- „Der TTS-Worker ist ebenfalls entkoppelt: Er konsumiert `tts_q` und führt die Wiedergabe aus.“
- „Er kann per `__STOP__` unterbrochen werden und blockiert währenddessen STT via Event.“

Codebezug:
- `tts_busy_evt.set()` während Ausgabe, danach `clear()`
- `__STOP__` → Ausgabe abbrechen + Queue leeren

### Block: Kommunikationskanäle (Zusammenhang der Queues)
Was ich sage:
- „Die drei Queues sind die Entkopplungsschicht:“
  - `audio_q`: **Bytes/PCM** (Roh-Audio)
  - `text_q`: **Diktat + Control-Tokens** (Steuerung für LLM)
  - `tts_q`: **Antworttexte + Control-Tokens** (Steuerung für Ausgabe)
- „So bleiben blockierende Operationen (Cloud-Call, Playback) in Worker-Threads und nicht im Audio-Loop.“

Codebezug (konkrete Max-Größen):
- `audio_q` maxsize **120**
- `text_q` maxsize **10**
- `tts_q` maxsize **10**
- Motivation: lieber kontrolliert verwerfen/aufräumen als Deadlock oder unendliche Latenz


---

## Folie 1 – Titel: Hybrid-Sprachassistent

**Sprechtext (ca. 20–30 s)**  
Hallo, ich bin Tobias Dome. Ich stelle heute einen prototypischen *hybriden* Sprachassistenten vor.  
„Hybrid“ heißt hier: Wake-Phrase und Diktat laufen lokal über Vosk, die Antwortgenerierung erfolgt über ein Cloud-LLM (Gemini), und die Sprachausgabe ist optional per TTS möglich.  
Der Stand ist eine Implementationsdemo: Fokus liegt auf einer funktionierenden Pipeline und sauberer Zustandslogik – nicht auf einer fertigen Produktqualität.

**Zeigepunkte**  
- Komponenten: Vosk (lokal) → Gemini (Cloud) → TTS (optional)  
- „Thread-sichere Session“ als Robustheitsziel

---

## Folie 2 – Agenda

**Sprechtext (ca. 15–20 s)**  
Ich gehe in sechs Schritten vor: Erst Motivation und Problemraum, dann Zielsetzung und Forschungsfragen.  
Anschließend zeige ich das Systemdesign – Pipeline, Architektur und State-Handling.  
Danach kommen die Implementationsdetails zu STT, LLM, TTS und Robustheit.  
Zum Schluss formuliere ich Grenzen und einen Evaluationsplan sowie ein kurzes Fazit mit Roadmap.

---

## Folie 3 – Motivation & Problemraum

**Sprechtext (ca. 35–45 s)**  
Die Motivation ist ein typischer Zielkonflikt bei Sprachassistenten: Datenschutz und Latenz sprechen für lokale Verarbeitung, aber offene Dialoge und Wissen sind mit lokalen Ressourcen oft begrenzt.  
Darum trenne ich bewusst: Wake-Phrase-Erkennung und Diktat passieren lokal. Dadurch muss kein Roh-Audio in die Cloud.  
Für flexible Antworten nutze ich ein Cloud-LLM als Dialogkomponente.  
Dazu kommt die dritte Perspektive: Im Streaming-Betrieb treten Robustheitsprobleme auf – mehrere Threads, Queue-Überläufe, Netzwerkausfälle oder Quota-Limits.  
Der Projektfokus ist daher: definierte Phrasen für Wake/Sleep/Exit, Parallelisierung mit Worker-Threads, Session-Invalidierung und ein Retry/Backoff-Verhalten bei transienten Fehlern.

**Transition**  
Damit ist klar, *warum* hybrid. Als Nächstes: *was* genau ich mit dem Prototyp beantworte.

---

## Folie 4 – Zielsetzung & Forschungsfragen

**Sprechtext (ca. 45–55 s)**  
Ziel ist die Entwicklung eines prototypischen Sprachassistenten, der lokale Spracherkennung mit einer cloudbasierten Dialogkomponente kombiniert und optional TTS ausgibt.  
Wichtig ist die Abgrenzung: Im aktuellen Stand gibt es **kein** vollständig offline arbeitendes LLM. Und es gibt **keine** integrierte automatische Messung von Latenz oder Qualitätsmetriken.  
Daraus ergeben sich drei projektbezogene Fragen:  
Erstens: Wie kann Wake-Phrase und Diktat lokal umgesetzt werden, ohne Cloud-STT zu benötigen?  
Zweitens: Welche Architektur entkoppelt Audioaufnahme, LLM-Aufruf und TTS robust, also mit Queues und Threads?  
Drittens: Wie lässt sich Session-Konsistenz und Fehlerbehandlung in einer laufenden Sprachinteraktion umsetzen?

---

## Folie 5 – Pipeline-Übersicht

**Sprechtext (ca. 45–60 s)**  
Hier ist der Signalfluss vom Mikrofon bis zur Ausgabe.  
Audio kommt als Stream rein und wird als Bytes in eine Audio-Queue gelegt.  
Ein Vosk-Recognizer mit Grammar erkennt die Steuerphrasen für Wake, Sleep und Exit.  
Im ACTIVE-Modus läuft ein zweiter Recognizer als freies Diktat; erkannter Text landet in der Text-Queue.  
Ein Gemini-Worker nimmt Text aus der Queue, erzeugt oder nutzt eine Chat-Session, und produziert eine Antwort.  
Optional geht die Antwort in eine TTS-Queue und wird gesprochen.  
Wichtig für Datenschutz-Transparenz: Audio wird lokal verarbeitet; an Gemini geht nur der erkannte Text. Bei edge-tts kann optional auch TTS-Text die Cloud verlassen.

#### Folie 5 – Kurz-Erklärung der Queues (audio_q / text_q / tts_q)

- **audio_q**: Puffert eingehende Audioblöcke (Bytes) aus dem Mikrofon.  
  Zweck: Audioaufnahme läuft kontinuierlich weiter, auch wenn nachgelagerte Schritte kurz langsamer sind.

- **text_q**: Puffert erkannten Text (Transkript) aus dem Diktat.  
  Zweck: Der LLM-Worker kann Texte nacheinander abarbeiten, ohne die Audioaufnahme zu blockieren.

- **tts_q**: Puffert auszugebende Antworttexte bzw. TTS-Jobs.  
  Zweck: Sprachausgabe läuft asynchron und unabhängig vom LLM-Call oder von der Aufnahme.

---

#### Folie 5 – Bedeutung der 5 Icons (Audio / Wake+Sleep / Diktat / LLM / TTS)

1) **Audio**  
   Mikrofon-Stream → Audiodaten kommen in kleinen Frames/Chunks rein (z. B. 16 kHz, mono) und werden in **audio_q** gelegt.

2) **Wake/Sleep**  
   Vosk mit *Grammar* prüft den Audio-Stream auf definierte Steuerphrasen.  
   Ergebnis: Zustandswechsel (**IDLE ↔ ACTIVE**) und ggf. Session-Wechsel.

3) **Diktat**  
   Im **ACTIVE**-Modus läuft Vosk als freies Diktat (ohne Grammar).  
   Ergebnis: erkannter Inhaltstext wird in **text_q** geschrieben (Steuerphrasen werden nicht als Diktat weitergegeben).

4) **LLM**  
   Ein Worker liest aus **text_q**, sendet den Text an Gemini (Chat-Session) und erzeugt eine Antwort.  
   Ergebnis: Antworttext (plus ggf. Session-Kontext im Hintergrund).

5) **TTS**  
   Ein Worker nimmt den Antworttext und verarbeitet ihn zur Sprachausgabe (z. B. edge-tts oder pyttsx3).  
   Ergebnis: gesprochene Antwort; währenddessen wird Diktat typischerweise unterdrückt, um Feedback-Schleifen zu vermeiden.





**Mini-Demo-Ansage (optional)**  
„Aktivierung ist *hallo michaela*, Deaktivierung *danke michaela*, und zum Beenden *kill switch aktivieren*.“

---

## Folie 6 – Architektur: Main Loop (Audio), Gemini-Worker, TTS-Worker

### 1) Main Loop (Audio) – was ist das und was macht er?
Der **Main Loop** ist der Teil, der sich um die **kontinuierliche Audioaufnahme** kümmert.

- Er liest fortlaufend Audio vom Mikrofon (typisch über einen Callback/Stream).
- Er zerlegt das Audio in kleine **Chunks/Frames** (z. B. feste Blockgröße).
- Diese Chunks werden **sofort** in die **audio_q** gelegt.
- Parallel dazu wird auf Basis dieser Audio-Chunks die **Wake/Sleep-Erkennung** (Vosk mit Grammar) ausgeführt:
  - Wenn **Wake** erkannt wird: System geht in **ACTIVE**, Session-ID wird erhöht.
  - Wenn **Sleep** erkannt wird: System geht in **IDLE**, Session-ID wird erhöht.
- Wenn das System **ACTIVE** ist, wird zusätzlich **Diktat** (Vosk frei) betrieben:
  - Erkannter Text wird in die **text_q** gelegt.

**Warum das wichtig ist:**  
Die Audioaufnahme soll nie blockieren. Auch wenn LLM oder TTS langsam sind, darf die Aufnahme nicht „stehen bleiben“. Deshalb ist sie entkoppelt.

---

### 2) Gemini-Worker – was macht dieser Thread?
Der **Gemini-Worker** ist ein separater Worker-Thread, der die Cloud-Anfrage abarbeitet.

- Er wartet auf neuen Inhalt in der **text_q** (Diktat-Text).
- Er nimmt den nächsten Text aus der Queue und schickt ihn an **Gemini** (Chat-Session).
- Er bekommt die Antwort zurück und erzeugt daraus einen **Antworttext**.
- Danach:
  - entweder legt er den Antworttext als Job in die **tts_q** (wenn Sprachausgabe aktiv ist),
  - oder er gibt ihn nur als Text aus (wenn TTS deaktiviert ist).
- Zusätzlich prüft er typischerweise, ob die Antwort noch zur **aktuellen Session** gehört (Session-ID), damit alte Antworten nicht „reinlaufen“.

**Warum das wichtig ist:**  
Ein LLM-Call kann verzögern (Netz/Quota). Durch den separaten Worker blockiert das nicht die Audioaufnahme.

---

### 3) TTS-Worker – was macht dieser Thread?
Der **TTS-Worker** ist ein eigener Thread, der die Sprachausgabe seriell abarbeitet.

- Er wartet auf Jobs in der **tts_q**.
- Er nimmt den nächsten Antworttext und macht daraus **Sprachausgabe**:
  - z. B. über edge-tts (Cloud) oder pyttsx3 (lokal).
- Während die Ausgabe läuft, wird Diktat typischerweise **unterdrückt**, damit keine Rückkopplung entsteht
  (also der Assistent sich nicht selbst wieder „hört“).

**Warum das wichtig ist:**  
TTS kann ebenfalls dauern. Durch den Worker bleibt der Rest des Systems responsiv.

---

## Zusammenspiel: audio_q, text_q, tts_q (Abhängigkeiten und Datenfluss)

### Was machen die Queues?
- **audio_q**: Puffer für **Audio-Chunks** aus dem Mikrofon (Roh-Audio in kleinen Blöcken).
- **text_q**: Puffer für **erkannten Diktat-Text** (Transkript).
- **tts_q**: Puffer für **Antworttexte**, die gesprochen werden sollen (TTS-Jobs).

### Wie hängen sie zusammen?
**Datenfluss als Kette:**
1. **Main Loop** schreibt Audio-Chunks → **audio_q**
2. Aus Audio wird (im ACTIVE-Modus) Diktat erkannt → Main Loop schreibt Text → **text_q**
3. **Gemini-Worker** liest Text aus **text_q** → erzeugt Antwort → schreibt in **tts_q**
4. **TTS-Worker** liest aus **tts_q** → spricht die Antwort

### Warum überhaupt Queues?
- Sie entkoppeln die Komponenten zeitlich:
  - Audio läuft „in Echtzeit“,
  - LLM und TTS können langsamer sein.
- Sie verhindern, dass ein langsamer Cloud-Call oder eine lange Sprachausgabe die Aufnahme blockiert.
- Sie erlauben kontrolliertes Verhalten bei Last (z. B. Verwerfen/Flush bei Überlauf statt Deadlock).


---
# Sprechertext – Folien 7–13 (Präsi + chat.py)

## Vorab: Begriffe, die auf mehreren Folien vorkommen
- **`audio_q`**: Puffer für rohe Audio-Frames aus dem Audio-Callback. Der Main-Loop liest daraus kontinuierlich und füttert die Vosk-Recognizer.
- **`text_q`**: Puffer für *erkannte* Texte (Diktat) **und** Steuersignale (`__WAKE__`, `__SLEEP__`, `__EXIT__`). Der Gemini-Worker konsumiert diese Queue.
- **`tts_q`**: Puffer für auszugebende Antworten (Text) **und** Steuersignale (`__STOP__`, `__EXIT__`). Der TTS-Worker konsumiert diese Queue.
- **Steuersignale**:
  - `__WAKE__`: startet/initialisiert eine neue Dialog-Session im LLM-Worker und stoppt ggf. laufende Sprachausgabe.
  - `__SLEEP__`: beendet die Session logisch (LLM-Worker setzt Chat zurück) und stoppt TTS.
  - `__STOP__`: stoppt TTS-Ausgabe *sofort* und leert die TTS-Queue (Abbruch laufender Ausgabe).
  - `__EXIT__`: beendet das Programm.

---

# Folie 7 – Zustandsmodell & Session-Konsistenz

### Block „Zustandsmodell (Konzept)“
Was ich sage:
- „Ich trenne den Assistenten in zwei Hauptzustände: **IDLE** und **ACTIVE**.“
- „**IDLE** bedeutet: Es wird nur auf *wenige Kommandos* gehört, konkret auf die Wake-Phrase.“
- „**ACTIVE** bedeutet: Der Assistent akzeptiert Diktat als Nutzereingabe und kann Antworten generieren und aussprechen.“
- „Die Präsentation nennt zusätzlich *PROCESSING/SPEAKING* als Phasen innerhalb von ACTIVE – im Code sind das keine eigenen States, sondern ergibt sich aus dem Ablauf (LLM-Call bzw. TTS aktiv).“

### Block „Mechanismen im Code“
Was ich sage:
- „Damit Threads konsistent bleiben, nutze ich drei Kernmechanismen.“
1) **`state_lock`**: „Schützt die gemeinsamen Zustandsvariablen, also `active` und `session_id`.“
2) **`session_id`**: „Wird bei Wake/Sleep hochgezählt. Worker prüfen diese ID – dadurch werden *alte* Operationen verworfen, wenn zwischenzeitlich ein Zustandswechsel passiert ist.“
3) **Cooldown + Arming Delay**: „Direkt nach State-Wechseln unterdrücke ich kurz Trigger/Diktat, um Fehlaktivierungen zu reduzieren.“
4) **TTS-Unterdrückung via Event**: „Während der Assistent spricht, wird Diktat unterdrückt, damit er seine eigene Ausgabe nicht wieder als Eingabe erkennt.“

### Block „Hinweis (Evaluation)“
Was ich sage:
- „Wichtig: Das ist eine Beschreibung der implementierten Logik. Es ist keine Aussage über Erkennungsqualität – dafür bräuchte ich Tests/Evaluation.“

Übergang:
- „Als Nächstes zeige ich die konkrete STT-Implementierung: Kommandos über Grammar und freies Diktat.“

---

# Folie 8 – Spracherkennung (STT) im Prototyp

### Block „Command-Erkennung“
Was ich sage:
- „Für Wake/Sleep/Exit nutze ich einen Vosk-Recognizer mit **begrenzter Grammar**. Das fokussiert die Erkennung auf wenige Phrasen und dient als zuverlässige Zustandssteuerung.“
- „Die drei Phrasen sind: Wake **„hallo michaela“**, Sleep **„danke michaela“**, Exit **„kill switch aktivieren“**.“
- „Im Code existieren dafür getrennte Recognizer/Grammars: ein Wake-Recognizer (Wake+Exit) und ein Sleep-Recognizer (Sleep+Exit).“

### Block „Freies Diktat“
Was ich sage:
- „Für Inhalte nutze ich einen zweiten Recognizer ohne Grammar: **freies Diktat**.“
- „Sobald Diktat final erkannt ist, schreibe ich den Text in **`text_q`** – das ist die Schnittstelle zum LLM-Worker.“
- „Ich filtere dabei die Steuerphrasen (Wake/Sleep/Exit) heraus, damit diese nicht aus Versehen als normale User-Frage beim LLM landen.“

### Block „Wie das in der Main-Loop zusammenläuft (Audio)“
Was ich sage:
- „Das Mikrofon läuft über einen Callback und legt Audio-Bytes in **`audio_q`** ab.“
- „Die Main-Loop liest Frames aus `audio_q` und wendet je nach Zustand unterschiedliche Erkennung an:“
  - „**IDLE**: Wake-Recognizer prüft, ob Wake/Exit gesprochen wurde.“
  - „**ACTIVE**: Sleep-Recognizer prüft zuerst auf Sleep/Exit; danach kommt freies Diktat.“
- „Zusätzlich gibt es Gatekeeping:“
  - „Wenn wir gerade erst den Zustand gewechselt haben, blockt **`dictation_block_until`** kurz das Diktat (Arming Delay).“
  - „Wenn **`tts_busy_evt`** gesetzt ist, wird Diktat übersprungen (Feedback-Loop Schutz).“

Übergang:
- „Wenn Text in `text_q` landet, übernimmt der LLM-Worker – das ist die nächste Folie.“

---

# Folie 9 – Dialog-/Antwortkomponente (LLM)

### Block „Gemini Chat“
Was ich sage:
- „Die Antwortgenerierung erfolgt über einen separaten Thread, den **Gemini-Worker**.“
- „Der Worker liest aus **`text_q`** und spricht Gemini über eine Chat-Session an.“
- „Konfiguration ist bewusst ‘demo-tauglich’: begrenzte Token, moderate Temperatur – kurze, direkte Antworten.“

### Block „Session-Handling“
Was ich sage:
- „Bei `__WAKE__` wird eine neue Chat-Session erzeugt. Das ist bewusst ein ‘Reset’ für einen neuen Dialog.“
- „Bei `__SLEEP__` wird der Chat im Worker auf `None` gesetzt – damit ist die Session logisch beendet.“
- „Wichtig ist die Konsistenz: Der Worker hält eine **lokale `local_session_id`** und prüft vor/nach API-Calls, ob sich die globale `session_id` geändert hat.“
- „Wenn ja, wird das Ergebnis verworfen. So vermeide ich, dass eine Antwort aus einer alten Session in eine neue Sitzung ‘hineinblutet’.“

### Block „System-Instructions (Stil)“
Was ich sage:
- „Im Code gibt es ein System-Prompt, das den Output stark einschränkt: Deutsch, kurz, sachlich, maximal wenige Bulletpoints und keine erfundenen Fakten.“
- „Das ist eine Designentscheidung für eine Voice-Demo: kurze, gut vorlesbare Antworten statt lange Texte.“

### Block „Retry/Backoff + Quota“
Was ich sage:
- „Für transiente Fehler gibt es Retry mit Backoff und Jitter.“
- „**Quota Exhaustion** wird erkannt und *nicht* endlos retried – stattdessen wird abgebrochen und die Text-Queue geflusht, um das System wieder in einen stabilen Zustand zu bringen.“

Übergang:
- „Die Antwort landet optional in `tts_q` – damit kommen wir zur Sprachausgabe.“

---

# Folie 10 – Sprachausgabe (TTS)

### Block „edge-tts (optional)“
Was ich sage:
- „Primär nutze ich **edge-tts** als Neural-TTS. Ausgabe wird lokal abgespielt (z. B. über `ffplay`/`mpg123`).“
- „Die Stimme ist im Code als `de-DE-KatjaNeural` vorkonfiguriert.“
- „Wichtig: Das ist optional und kann – je nach Setup – cloudabhängig sein.“

### Block „pyttsx3 (optional)“
Was ich sage:
- „Als Fallback existiert **pyttsx3** für Offline-TTS. Das klingt oft robotischer, ist aber unabhängig vom Netz.“
- „Ich gebe satzweise aus, damit die Verständlichkeit stabil bleibt.“

### Block „Feedback-Loop Schutz“
Was ich sage:
- „Während der TTS-Ausgabe setze ich **`tts_busy_evt`**.“
- „Die Audio-Main-Loop prüft dieses Event und unterdrückt Diktat, solange gesprochen wird.“
- „Zusätzlich gibt es Steuersignale: `__STOP__` bricht laufende Ausgabe ab und leert die TTS-Queue.“

Übergang:
- „Damit das System im Betrieb nicht hängen bleibt, sind Robustheitsmechanismen wichtig – das ist Folie 11.“

---

# Folie 11 – Robustheit & Fehlerbehandlung

### Block „Retry-Strategie“
Was ich sage:
- „Im LLM-Teil klassifiziere ich Fehler in retrybar vs. nicht retrybar.“
- „Retrybar: typische transiente Netzwerk-/Serverprobleme (Timeouts, 5xx, Overload).“
- „Nicht retrybar: Quota/`RESOURCE_EXHAUSTED`. Da breche ich ab und räume auf, statt in einer Endlosschleife zu hängen.“
- „Backoff ist exponentiell und hat Jitter, damit wiederholte Requests nicht synchron ‘stapeln’.“

### Block „Queue-Management“
Was ich sage:
- „Alle drei Kommunikationspfade laufen über **bounded queues**: Audio, Text, TTS.“
- „Bei Überlauf wird verworfen oder gezielt geflusht, um Reaktionsfähigkeit zu behalten.“
- „Die Maximalgrößen sind: `audio_q` 120, `text_q` 10, `tts_q` 10.“
- „Das ist ein praktischer Trade-off: lieber einzelne Frames/Inputs verlieren als Deadlocks oder unendliche Latenz aufbauen.“

### Block „Warnhinweis“
Was ich sage:
- „Diese Mechanismen erhöhen Robustheit, ersetzen aber keine wissenschaftliche Evaluation – dafür braucht man definierte Metriken und Tests.“

Übergang:
- „Genau diese Trennung zwischen Implementationsstand und wissenschaftlicher Bewertung ist Thema der nächsten Folie.“

---

# Folie 12 – Grenzen & geplanter Evaluationsrahmen

### Block „Grenzen (aktueller Code)“
Was ich sage:
- „Aktueller Stand ist bewusst ein Prototyp mit klaren Grenzen:“
  - „Kein lokales LLM: Antworten brauchen Gemini (Cloud).“
  - „Keine integrierte Messung: Latenz/WER/RTF werden nicht automatisch erfasst.“
  - „Funktionsumfang fokussiert Wake/Sleep, Dialog und TTS – es gibt kein Skill-/Tool-System.“
  - „Datenschutz: Text verlässt das Gerät für LLM (und optional TTS bei edge-tts).“

### Block „Evaluation (Vorschlag)“
Was ich sage:
- „Als wissenschaftlicher Plan würde ich getrennt evaluieren:“
  - „**STT**: WER und Command-Accuracy (Wake/Sleep) auf einem Testset.“
  - „**Latenz**: End-to-End-Verteilung (p50/p95) und Segmentzeiten (STT→LLM→TTS).“
  - „**Robustheit**: Fehler-Injektion (Netz, Quota, Device/Queue Overflows).“
  - „**UX**: kleine Nutzerstudie zu Verständlichkeit und Turn-Taking.“
- „Wichtig: Das sind Vorschläge – keine bereits gemessenen Ergebnisse.“

Übergang:
- „Zum Schluss fasse ich den implementierten Beitrag zusammen und nenne die nächsten Schritte.“

---

# Folie 13 – Fazit & Ausblick

### Block „Beitrag (implementiert)“
Was ich sage:
- „Der konkrete Beitrag ist ein lauffähiger Hybrid-Prototyp mit klarer Pipeline:“
  - „Lokale STT/Command-Erkennung über Vosk (Wake/Sleep/Diktat).“
  - „Dialoggenerierung über Gemini, inklusive Session-Konsistenz durch `session_id` + Locking.“
  - „Optionale TTS-Ausgabe (edge-tts/pyttsx3) mit Schutz gegen Feedback-Loops.“
  - „Resilienz durch Retry/Backoff, Quota-Erkennung und Queue-Management.“

### Block „Nächste Schritte (Roadmap)“
Was ich sage:
- „Als Roadmap sehe ich vier direkte Ausbaustufen:“
  - „Optionaler Offline-Modus mit lokalem LLM (z. B. llama.cpp).“
  - „Evaluationssuite (WER/Latenz/Robustheit) + Logging/Telemetry.“
  - „Skill-System/Tools (z. B. Wissensquellen, Home-Automation).“
  - „Telemetrie-UI (Live-State) statt Simulation.“

### Block „Demo-Hinweis“
Was ich sage:
- „Bedienung in der Demo: Start mit **„hallo michaela“**, Beenden mit **„kill switch aktivieren“**.“
- „Und Sleep ist **„danke michaela“** – damit geht der Assistent zurück in den IDLE-Modus.“

Endsatz:
- „Damit ist der Implementationsstand sauber abgegrenzt: Prototyp steht, Evaluation ist als nächster wissenschaftlicher Schritt geplant.“
