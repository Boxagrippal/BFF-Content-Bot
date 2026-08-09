"""
BFF Content Bot
----------------
Erzeugt taeglich automatisch ein fertiges Instagram/Facebook-Postbild
(Bild + Spruch + Logo) fuer "Battlefield for Friends" und laedt es in
einen Dropbox-Ordner hoch. Postet NICHT automatisch - das macht der
Nutzer weiterhin selbst von Hand.

Laeuft als taeglicher Cron-Job (z.B. via Render.com um 3-4 Uhr nachts).
"""
import re
import os
import io
import json
import base64
import random
import datetime
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "events_config.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo", "bff-logo.png")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

DROPBOX_FOLDER = "/BFF-Content"
STATE_DROPBOX_PATH = f"{DROPBOX_FOLDER}/state.json"

OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
DROPBOX_APP_KEY = (os.environ.get("DROPBOX_APP_KEY") or "").strip()
DROPBOX_APP_SECRET = (os.environ.get("DROPBOX_APP_SECRET") or "").strip()
DROPBOX_REFRESH_TOKEN = (os.environ.get("DROPBOX_REFRESH_TOKEN") or "").strip()


# ---------- Hilfsfunktionen: Konfiguration ----------

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- Dropbox ----------

def dropbox_get_access_token():
    resp = requests.post(
        "https://api.dropboxapi.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": DROPBOX_REFRESH_TOKEN,
            "client_id": DROPBOX_APP_KEY,
            "client_secret": DROPBOX_APP_SECRET,
      },
    )
    if resp.status_code != 200:
        print(resp.text)
    resp.raise_for_status()
    return resp.json()["access_token"]


def dropbox_upload_bytes(access_token, data_bytes, dropbox_path):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({
            "path": dropbox_path,
            "mode": "overwrite",
            "mute": True,
        }),
        "Content-Type": "application/octet-stream",
    }
    resp = requests.post(
        "https://content.dropboxapi.com/2/files/upload",
        headers=headers,
        data=data_bytes,
    )
    resp.raise_for_status()


def dropbox_download_bytes(access_token, dropbox_path):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({"path": dropbox_path}),
    }
    resp = requests.post(
        "https://content.dropboxapi.com/2/files/download",
        headers=headers,
    )
    if resp.status_code != 200:
        return None
    return resp.content


def load_state(access_token, config):
    raw = dropbox_download_bytes(access_token, STATE_DROPBOX_PATH)
    if raw is None:
        # Noch kein Status vorhanden -> Grundzustand anlegen
        return {
            "last_event_index": -1,
            "used_scenes": {e["key"]: [] for e in config["events"]},
            "last_story_special": None,
        }
    return json.loads(raw.decode("utf-8"))


def save_state(access_token, state):
    data = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
    dropbox_upload_bytes(access_token, data, STATE_DROPBOX_PATH)


# ---------- Auswahl-Logik ----------

def pick_next_event(config, state):
    events = config["events"]
    next_index = (state["last_event_index"] + 1) % len(events)
    state["last_event_index"] = next_index
    return events[next_index]


def pick_next_scene(state, event):
    key = event["key"]
    used = state["used_scenes"].setdefault(key, [])
    all_scenes = event["scenes"]
    remaining = [s for s in all_scenes if s not in used]
    if not remaining:
        # Pool durch -> von vorne beginnen
        used.clear()
        remaining = all_scenes[:]
    scene = random.choice(remaining)
    used.append(scene)
    return scene


def is_story_special_day(config, state):
    today = datetime.date.today()
    target_weekday = config["story_special"]["weekday"]
    if today.weekday() != target_weekday:
        return False
    last = state.get("last_story_special")
    iso_week = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]}"
    if last == iso_week:
        return False
    return True


# ---------- OpenAI: Bild & Text ----------
def generate_quote(event):
    examples = "\n".join(f"- {q}" for q in event["quote_examples"])
    system_prompt = (
        "Du schreibst kurze, punchy deutsche Instagram-Sprueche fuer eine "
        "Survival/Airsoft-Eventreihe namens 'Battlefield for Friends'. "
        "Antworte AUSSCHLIESSLICH mit genau EINEM einzelnen Spruch, ein "
        "Satz, maximal 12 Woerter. Kein Aufzaehlungszeichen, kein "
        "Bindestrich-Trenner, keine Liste, keine Anfuehrungszeichen, kein "
        "Hashtag, kein Emoji, keine Zeilenumbrueche. Nur der reine "
        "Spruchtext, sonst nichts.\n\n"
        "Beispiele aus der Reihe (nur zur Stil-Orientierung, nicht als "
        "Liste zurueckgeben und nicht kopieren):\n" + examples
    )
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Thema/Event: {event['name']} - {event['theme']}. "
                    "Gib genau einen Spruch zurueck.",
                },
            ],
            "temperature": 0.9,
            "max_tokens": 40,
        },
        timeout=60,
    )
    resp.raise_for_status()
    quote = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
 
    # Sicherheitsnetz: falls das Modell trotzdem mehrere Sprueche oder eine
    # Liste zurueckgibt, nur den ersten, kurzen Teil davon verwenden
    quote = quote.split("\n")[0].lstrip("-•– ").strip()
    quote = re.split(r"\s[-–—]\s", quote)[0].strip()
    words = quote.split()
    if len(words) > 14:
        quote = " ".join(words[:14])
    return quote
def generate_image(prompt):
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "high",
        },
        timeout=120,
    )
    resp.raise_for_status()
    b64 = resp.json()["data"][0]["b64_json"]
    return base64.b64decode(b64)




KAMERA_WINKEL = [
    "Weitwinkel-Establishing-Shot, leichte Untersicht, Szene wirkt gewaltig",
    "Pull-Back-Reveal-Perspektive, als wuerde die Kamera langsam zurueckfahren und die volle Szene enthuellen",
    "Nahaufnahme mit Fokus auf Ausruestung und Mimik, Hintergrund leicht unscharf (Bokeh)",
    "Low-Angle-Heroshot von schraeg unten, die Figur wirkt ueberlebensgross",
    "Over-the-Shoulder-Perspektive, Blick ueber die Schulter der Figur in die Szene hinein",
    "dynamische, leicht gekippte Diagonalkomposition fuer zusaetzliche Spannung",
]

REGIE_STIMMUNG = [
    "cinematisch, gewichtig, wie der Trailer-Moment eines Blockbusters",
    "energiegeladen, Bewegung eingefroren im Moment maximaler Spannung",
    "ruhig und bedrohlich, Stille vor dem Sturm",
    "episch und ehrfurchtgebietend, grosse Kulisse, kleine Figur",
]
def build_image_prompt(event, scene):
    kamera = random.choice(KAMERA_WINKEL)
    regie = random.choice(REGIE_STIMMUNG)
    return (
        f"{scene}. Stil: {event['theme']}. Bildbehandlung: {event['treatment']}. "
        f"Kamera: {kamera}. Regie: {regie}. "
        "Preisgekroentes Kino-Standbild, wie ein Poster-Motiv fuer einen "
        "Blockbuster-Actionfilm, ultra-detailliert, scharfe Texturen, "
        "beeindruckende Tiefenwirkung durch Vorder-, Mittel- und Hintergrund, "
        "starke Lichtquelle die die Szene dramatisch akzentuiert (z.B. "
        "Sonnenuntergang, Feuer, Scheinwerfer oder Neonlicht), satte, kraeftige "
        "Farben statt flaechig dunkler Bildstimmung, Gefuehl von Bewegung und "
        "Spannung, fotorealistisch, 8K, wie von einem preisgekroenten "
        "Fotografen, keine Personenschaeden, kein Blut, keine grafische "
        "Gewalt, keine Waffen die direkt auf Personen zielen."
    )


# ---------- Bildkomposition: Logo + Spruch ----------

def _load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def compose_final_image(raw_image_bytes, quote_text, event_name=None):
    img = Image.open(io.BytesIO(raw_image_bytes)).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    # Logo klein, oben rechts
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo_w = int(w * 0.14)
    logo_h = int(logo_w * logo.size[1] / logo.size[0])
    logo = logo.resize((logo_w, logo_h))
    img.paste(logo, (w - logo_w - 28, 28), logo)

    if not quote_text:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=92)
        return out.getvalue()

    font_path = os.path.join(BASE_DIR, "fonts", "ArmyRust.ttf")

    # Spruch in Einleitungszeile (klein) + Kernaussage (gross) aufteilen,
    # falls ein Doppelpunkt vorhanden ist
    intro_text = ""
    main_text = quote_text
    if ":" in quote_text:
        parts = quote_text.split(":", 1)
        intro_text = parts[0].strip().upper() + ":"
        main_text = parts[1].strip()

    quote_upper = main_text.upper()
    max_width = int(w * 0.86)

    intro_size = int(w * 0.032)
    intro_font = _load_font(font_path, intro_size)
    intro_lines = _wrap_text(draw, intro_text, intro_font, max_width) if intro_text else []

    font_size = int(w * 0.078)
    font = _load_font(font_path, font_size)
    lines = _wrap_text(draw, quote_upper, font, max_width)

    # Schrift verkleinern, falls der Spruch trotz Kuerzung zu viele Zeilen braucht
    while len(lines) > 4 and font_size > int(w * 0.04):
        font_size -= 4
        font = _load_font(font_path, font_size)
        lines = _wrap_text(draw, quote_upper, font, max_width)

    intro_line_height = int(intro_size * 1.3)
    line_height = int(font_size * 1.3)
    footer_size = int(w * 0.022)
    footer_font = _load_font("DejaVuSansMono-Bold.ttf", footer_size)
    footer_h = int(footer_size * 1.8)

    total_text_h = intro_line_height * len(intro_lines) + line_height * len(lines)
    y = h - total_text_h - footer_h - int(h * 0.06)

    def draw_centered_line(line, font, y_pos):
        line_w = draw.textlength(line, font=font)
        x = (w - line_w) / 2
        for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2), (-2, 2), (2, -2)]:
            draw.text((x + dx, y_pos + dy), line, font=font, fill="black")
        draw.text((x, y_pos), line, font=font, fill="#e9e3cf")

    for line in intro_lines:
        draw_centered_line(line, intro_font, y)
        y += intro_line_height

    for line in lines:
        draw_centered_line(line, font, y)
        y += line_height

    # Fusszeile: BATTLEFIELD FOR FRIENDS
    footer_text = "BATTLEFIELD FOR FRIENDS"
    fw = draw.textlength(footer_text, font=footer_font)
    fx = (w - fw) / 2
    fy = h - footer_h - int(h * 0.025)
    draw.text((fx, fy), footer_text, font=footer_font, fill="#c9c3a8")

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


# ---------- Ablauf: normaler Tagespost ----------

def run_daily_post(config, state, access_token):
    event = pick_next_event(config, state)
    scene = pick_next_scene(state, event)
    image_prompt = build_image_prompt(event, scene)

    raw_image = generate_image(image_prompt)
    quote = generate_quote(event)
    final_image = compose_final_image(raw_image, quote)

    today = datetime.date.today().isoformat()
    filename_base = f"{today}_{event['key']}"

    dropbox_upload_bytes(access_token, final_image, f"{DROPBOX_FOLDER}/{filename_base}.jpg")
    caption = f"{quote}\n\n#BattlefieldForFriends #{event['key']}"
    dropbox_upload_bytes(access_token, caption.encode("utf-8"), f"{DROPBOX_FOLDER}/{filename_base}_caption.txt")

    print(f"Fertig: {filename_base} ({event['name']})")


# ---------- Ablauf: Story Special (mehrteilig) ----------

def run_story_special(config, state, access_token):
    event = pick_next_event(config, state)
    beats = config["story_special"]["beats"]
    today = datetime.date.today().isoformat()

    for i, beat in enumerate(beats, start=1):
        scene = pick_next_scene(state, event)
        prompt = build_image_prompt(event, scene) + f" Erzaehlmoment: {beat}."
        raw_image = generate_image(prompt)

        if i == len(beats):
            caption = f"{beat} Was macht ihr? Schreibt's in die Kommentare! 👇"
        else:
            caption = beat

        final_image = compose_final_image(raw_image, caption if i == len(beats) else "")
        filename_base = f"{today}_story_{event['key']}_{i}"
        dropbox_upload_bytes(access_token, final_image, f"{DROPBOX_FOLDER}/{filename_base}.jpg")
        dropbox_upload_bytes(access_token, caption.encode("utf-8"), f"{DROPBOX_FOLDER}/{filename_base}_caption.txt")

    iso_week = f"{datetime.date.today().isocalendar()[0]}-W{datetime.date.today().isocalendar()[1]}"
    state["last_story_special"] = iso_week
    print(f"Story Special fertig fuer Event {event['name']}")


# ---------- Main ----------

def main():
    missing = [n for n, v in [
        ("OPENAI_API_KEY", OPENAI_API_KEY),
        ("DROPBOX_APP_KEY", DROPBOX_APP_KEY),
        ("DROPBOX_APP_SECRET", DROPBOX_APP_SECRET),
        ("DROPBOX_REFRESH_TOKEN", DROPBOX_REFRESH_TOKEN),
    ] if not v]
    if missing:
        raise SystemExit(f"Fehlende Umgebungsvariablen: {', '.join(missing)}")

    config = load_config()
    access_token = dropbox_get_access_token()
    state = load_state(access_token, config)

    if is_story_special_day(config, state):
        run_story_special(config, state, access_token)
    else:
        run_daily_post(config, state, access_token)

    save_state(access_token, state)


if __name__ == "__main__":
    main()
# Trigger Redeploy
