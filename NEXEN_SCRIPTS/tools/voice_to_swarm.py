import speech_recognition as sr
import os
from datetime import datetime

VAULT_DIR = r"H:\NEXEN\obsidian-vault"

def listen_and_dispatch():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("🎙️ NEXEN SWARM LISTENING... (Speak now)")
        r.adjust_for_ambient_noise(source)
        audio = r.listen(source)

    try:
        print("🧠 Transcribing...")
        text = r.recognize_google(audio)
        print(f"🗣️ You said: {text}")
        
        # Dump straight to the vault. The continuous watcher will catch it and execute it.
        filename = f"Voice_Command_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = os.path.join(VAULT_DIR, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Voice Command\n\n{text}\n")
            
        print(f"✅ Voice command injected into the Swarm via {filename}")
        
    except sr.UnknownValueError:
        print("❌ Swarm could not understand audio")
    except sr.RequestError as e:
        print(f"❌ Could not request results; {e}")

if __name__ == "__main__":
    listen_and_dispatch()
