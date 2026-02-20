import os
import polib
from deep_translator import GoogleTranslator

SOURCE_LANG = "en"

TARGET_LANGS = [
    "en", "ar", "tr", "ru", "az", "th", "be", "es", "pt",
    "vi", "sq", "es_CL", "es_MX", "en_NG", "et"
]

LANG_MAP = {
    "es_CL": "es",
    "es_MX": "es",
    "en_NG": "en"
}

BASE_DIR = "/home/barch/Desktop/bc/AmazonProject/locale"

for lang in TARGET_LANGS:
    translate_lang = LANG_MAP.get(lang, lang)

    # Path to existing django.po file
    po_path = os.path.join(BASE_DIR, lang, "LC_MESSAGES", "django.po")

    if not os.path.exists(po_path):
        print(f"Skipping {lang} – no file found at {po_path}")
        continue

    # Load existing translations
    po = polib.pofile(po_path, encoding="utf-8")

    translator = GoogleTranslator(source=SOURCE_LANG, target=translate_lang)

    for entry in po:
        try:
            entry.msgstr = translator.translate(entry.msgid)
        except Exception as e:
            print(f"Error translating {entry.msgid} to {lang}: {e}")

    po.save(po_path)
    print(f"Updated translations for {lang} → {po_path}")
