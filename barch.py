import os
import polib
import time
from deep_translator import GoogleTranslator

SOURCE_LANG = "en"

# Only Estonian left
TARGET_LANGS = ["et"]

BASE_DIR = "/home/barch/Desktop/bc/AmazonProject/locale"

total_start = time.time()

for lang in TARGET_LANGS:
    po_path = os.path.join(BASE_DIR, lang, "LC_MESSAGES", "django.po")

    if not os.path.exists(po_path):
        print(f"⚠️ Skipping {lang} – no file found at {po_path}")
        continue

    print(f"▶ Starting translation for {lang}...")
    start_time = time.time()

    try:
        po = polib.pofile(po_path, encoding="utf-8")
    except Exception as e:
        print(f"❌ Error loading {po_path}: {e}")
        continue

    translator = GoogleTranslator(source=SOURCE_LANG, target=lang)
    count = 0

    for entry in po:
        try:
            # Skip auto-translation for placeholders or technical terms
            if "%(" in entry.msgid or "slug" in entry.msgid.lower() or "boolean" in entry.msgid.lower():
                entry.msgstr = entry.msgstr or entry.msgid
            else:
                translated = translator.translate(entry.msgid)
                if translated is None:
                    translated = entry.msgstr or entry.msgid
                entry.msgstr = str(translated)
            count += 1
        except Exception as e:
            print(f"⚠️ Error translating {entry.msgid} to {lang}: {e}")
            entry.msgstr = entry.msgstr or entry.msgid

    try:
        po.save(po_path)
        elapsed = time.time() - start_time
        print(f"✅ Updated {count} entries for {lang} → {po_path} (took {elapsed:.2f} seconds)")
    except Exception as e:
        print(f"❌ Failed to save {po_path}: {e}")

total_elapsed = time.time() - total_start
print(f"\n🏁 Estonian translation completed in {total_elapsed:.2f} seconds (~{total_elapsed/60:.2f} minutes)")
