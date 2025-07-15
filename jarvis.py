import os
import time
import signal
import subprocess
import cv2
from ultralytics import YOLO
import face_recognition
import telegram
import pygame
from datetime import datetime
import sounddevice as sd
import numpy as np
import whisper
import pyttsx3
import requests
from scipy.io.wavfile import write
from gpiozero import LED, MotionSensor
from picamera2 import Picamera2
from PIL import Image
import board
import adafruit_dht

# ====== CONFIGURATION ======
# Telegram Bot Setup
TELEGRAM_TOKEN = "your_telegram_token"
CHAT_ID = "your_chat_id"
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# Auto-launch llama-server
LLAMA_SERVER = "/home/eya/llama.cpp/build/bin/llama-server" #adjust this to your llama path
MODEL_PATH = "/home/eya/llama_models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

# Face recognition setup
KNOWN_FACES_DIR = "known_faces"
yolo_model = YOLO("yolov8n.pt")

# Audio parameters
SR, DUR = 44100, 5  # sample rate, record seconds

# Music folder
MUSIC_FOLDER = "/home/eya/Music" #adjust your path

# System prompt for LLaMA
SYSTEM_PROMPT = """You are JARVIS, a home AI assistant. Your task is to:
1. Understand user requests about home control
2. Respond with JUST ONE of these action tags:
   - LIGHT_ON
   - LIGHT_OFF
   - TAKE_PHOTO
   - CHECK_TEMP
   - ACTIVATE_SECURITY
   - DEACTIVATE_SECURITY  
   - TELL_TIME
   - TELL_WEATHER
   - PLAY_MUSIC
   - STOP_MUSIC
   - TELL_NEWS
   - GENERAL_RESPONSE (for chats)
3. Then provide a brief natural response

Example:
User: "It's dark in here"
Response: "<LIGHT_ON>Let me turn on the lights for you</LIGHT_ON>"
"""

# ====== INITIALIZATION ======
def initialize_system():
    # Start LLaMA server
    print("🦙 Starting LLaMA server...")
    llama_proc = subprocess.Popen([
        LLAMA_SERVER,
        "-m", MODEL_PATH,
        "--port", "8080",
        "--threads", "4"
    ])
    time.sleep(15)  # wait for model to load

    # Initialize Whisper and TTS
    print("🎤 Initializing audio models...")
    model = whisper.load_model("base")
    tts = pyttsx3.init()
    tts.setProperty('rate', 150)
    tts.setProperty('volume', 1.0)

    # Initialize hardware
    print("💡 Initializing hardware...")
    light = LED(22)            # GPIO22 for LED
    dht = adafruit_dht.DHT11(board.D4)  # DHT11 on GPIO4
    pir = MotionSensor(17)     # PIR on GPIO17
    cam = Picamera2()          # PiCamera2
    
    # Create global state
    class GlobalState:
        security_active = False
    
    return llama_proc, model, tts, light, dht, pir, cam, GlobalState()

# ====== AUDIO FUNCTIONS ======
def speak(text):
    print("🗣️ JARVIS says:", text)
    tts.say(text)
    tts.runAndWait()

def record_audio():
    print("🎙️ Listening...")
    rec = sd.rec(int(DUR * SR), samplerate=SR, channels=1, dtype='int16')
    sd.wait()
    return np.squeeze(rec)

def transcribe_audio():
    audio = record_audio()
    write("temp.wav", SR, audio)
    print("🧠 Transcribing...")
    return model.transcribe("temp.wav")["text"].strip()

# ====== FACE RECOGNITION & SECURITY ======
def is_known_person(image_np):
    try:
        input_encodings = face_recognition.face_encodings(image_np)
        if not input_encodings:
            return False

        for filename in os.listdir(KNOWN_FACES_DIR):
            known_image = face_recognition.load_image_file(os.path.join(KNOWN_FACES_DIR, filename))
            known_encoding = face_recognition.face_encodings(known_image)[0]
            matches = face_recognition.compare_faces([known_encoding], input_encodings[0])
            if matches[0]:
                return True
        return False
    except Exception as e:
        print("⚠️ Face recognition error:", e)
        return False

def send_telegram_alert(image_np):
    filename = "intruder.jpg"
    cv2.imwrite(filename, cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR))
    try:
        bot.send_message(chat_id=CHAT_ID, text="🚨 Alert! Unknown person detected")
        with open(filename, 'rb') as photo:
            bot.send_photo(chat_id=CHAT_ID, photo=photo)
    except Exception as e:
        print(f"Telegram error: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# ====== SMART HOME ACTIONS ======
def take_photo():
    speak("Taking a photo")
    cam.start()
    time.sleep(2)
    img = cam.capture_array()
    cam.stop()
    pil = Image.fromarray(img)
    if pil.mode == "RGBA":
        pil = pil.convert("RGB")
    fn = f"photo_{int(time.time())}.jpg"
    pil.save(fn)
    speak(f"Photo saved as {fn}")
    return img

def check_temperature():
    speak("Reading temperature and humidity")
    try:
        t = dht.temperature
        h = dht.humidity
        if t is None or h is None:
            raise RuntimeError
        resp = f"Temperature is {t:.1f}°C, humidity {h:.1f}%"
        speak(resp)
    except Exception:
        speak("Failed to read DHT sensor")

def activate_security():
    speak("Security mode activated - monitoring for motion")
    try:
        while global_state.security_active:
            pir.wait_for_motion()
            speak("Motion detected - analyzing scene")
            
            # Capture image
            cam.start()
            time.sleep(2)
            frame = cam.capture_array()
            cam.stop()
            
            # Convert frame to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Run YOLOv8 detection
            results = yolo_model(frame_rgb, verbose=False)
            
            # Process results
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    label = yolo_model.names[class_id]
                    
                    if label == "person":
                        # Extract face region
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        face_img = frame_rgb[y1:y2, x1:x2]
                        
                        if face_img.size == 0:
                            continue
                            
                        # Face recognition check
                        if is_known_person(face_img):
                            speak("Authorized person detected")
                        else:
                            speak("Unknown person detected!")
                            send_telegram_alert(frame_rgb)
            
            time.sleep(10)  # Cooldown period
            
    except Exception as e:
        speak("Security system error")
        print(f"Security Error: {e}")

def turn_on_light():
    speak("Turning on the light")
    light.on()

def turn_off_light():
    speak("Turning off the light")
    light.off()

def tell_time():
    now = datetime.now()
    current_time = now.strftime("%I:%M %p")
    speak(f"The time is {current_time}")

def tell_weather():
    try:
        response = requests.get("https://wttr.in/?format=1", timeout=5)
        speak(f"The current weather is {response.text.strip()}")
    except:
        speak("Sorry, I can't reach the weather service.")

def tell_news():
    api_key = "your _ token _ here " # adjust your token here
    url = f"https://newsapi.org/v2/top-headlines?country=us&apiKey={api_key}"

    try:
        response = requests.get(url, timeout=5)
        data = response.json()

        if data["status"] != "ok" or "articles" not in data:
            speak("Sorry, I couldn't fetch the news.")
            return

        articles = data["articles"][:3]
        speak("Here are the latest news headlines.")
        for article in articles:
            speak(article["title"])

    except Exception as e:
        speak("Something went wrong while getting the news.")
        print("News API Error:", e)

def play_music():
    pygame.mixer.init()
    music_files = [f for f in os.listdir(MUSIC_FOLDER) if f.endswith(".mp3")]
    for track in music_files:
        path = os.path.join(MUSIC_FOLDER, track)
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            speak(f"Playing {track}")
            return
        except pygame.error:
            print(f"⚠️ Skipping invalid file: {track}")
            continue
    speak("I couldn't play any valid music files.")

def stop_music():
    pygame.mixer.music.stop()
    speak("Music stopped.")

# ====== LLaMA CHAT WITH ACTION RECOGNITION ======
def chat_with_llama(prompt):
    try:
        # Combine with system prompt
        full_prompt = f"{SYSTEM_PROMPT}\n\nUser: {prompt}\nResponse:"
        
        res = requests.post(
            "http://127.0.0.1:8080/completion",
            json={
                "prompt": full_prompt,
                "n_predict": 128,
                "temperature": 0.3,
                "stop": ["</s>", "\n"]
            },
            timeout=60
        )
        res.raise_for_status()
        response_text = res.json().get("content", "").strip()
        
        # Parse the response
        if "<" in response_text and ">" in response_text:
            action = response_text.split("<")[1].split(">")[0]
            message = response_text.split(">")[1].split("<")[0]
            return action, message
        return "GENERAL_RESPONSE", response_text
        
    except Exception as e:
        print("🔥 LLaMA error:", e)
        return "GENERAL_RESPONSE", "Sorry, I couldn't process that"

# ====== MAIN LOOP ======
if __name__ == "__main__":
    llama_proc, model, tts, light, dht, pir, cam, global_state = initialize_system()
    
    try:
        speak("JARVIS starting up. How can I help you?")
        while True:
            cmd = transcribe_audio()
            if not cmd:
                speak("I didn't catch that.")
                continue

            print("💬 You said:", cmd)
            
            # Get LLaMA's decision
            action, response = chat_with_llama(cmd)
            speak(response)  # Always speak the response
            
            # Execute the corresponding action
            if action == "LIGHT_ON":
                turn_on_light()
            elif action == "LIGHT_OFF":
                turn_off_light()
            elif action == "TAKE_PHOTO":
                take_photo()
            elif action == "CHECK_TEMP":
                check_temperature()
            elif action == "ACTIVATE_SECURITY":
                global_state.security_active = True
                activate_security()
            elif action == "DEACTIVATE_SECURITY":
                global_state.security_active = False
            elif action == "TELL_TIME":
                tell_time()
            elif action == "TELL_WEATHER":
                tell_weather()
            elif action == "PLAY_MUSIC":
                play_music()
            elif action == "STOP_MUSIC":
                stop_music()
            elif action == "TELL_NEWS":
                tell_news()
                
            print("-" * 40)
            time.sleep(0.5)

    except KeyboardInterrupt:
        speak("Goodbye.")
    finally:
        # Cleanup procedure
        speak("Performing system cleanup...")
        light.off()
        global_state.security_active = False
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
        
        llama_proc.send_signal(signal.SIGINT)
        llama_proc.wait()
        
        if os.path.exists("temp.wav"):
            os.remove("temp.wav")
            
        print("👋 JARVIS shut down.")
