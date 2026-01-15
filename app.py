import streamlit as st
import pdfplumber
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 1. KONFIGURACJA "MÓZGU" (Stałe i Reguły)
# ==========================================

# Dane Sprzedawcy (DO FILTROWANIA - TEGO NIE CHCEMY WYNIKACH)
MY_DATA = ["GEKO", "7722420459", "Sprzedawca", "Kietlin"]

# Limit interwencji (powyżej tej kwoty nie zawracamy gitary)
MAX_GAP = 300.00

# Baza Promocji (Priorytety)
PROMOS = [
    # Format: (Słowa kluczowe, Próg, Nagroda, Nazwa Promocji)
    (["szczotk", "wycior", "kula", "lina", "przepychacz"], 200.00, "T-SHIRT (0.01 zł)", "🔥 KOMINIARSKA"),
    (["rękawic", "kalosz", "gumofilc", "obuwie"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie"], 250.00, "Wieszak (1 zł)", "🔥 BHP (MAŁA)"),
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),    # Domyślna
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")           # Dla dużych
]

# Baza Sugestii (Co dorzucić)
SUGGESTIONS = {
    "prowadnic": "Ostrzałka elektr. (G81207) - Serwis pił",
    "łańcuch": "Olej do łańcuchów (G82000) - Eksploatacja",
    "siekier": "Ostrzałka 2w1 (T02-009) - Tani dodatek",
    "wykrętak": "Gwintowniki (G38301) - Naprawa gwintów",
    "prostownik": "Kable rozruchowe (G02400) - Zestaw Zima",
    "podnośnik": "Kobyłki warsztatowe - Wymóg BHP",
    "pneumat": "Wąż zakuty / Szybkozłączki",
    "szczotk": "Kula + Lina - Zestaw kominiarski",
    "kula": "Lina kominiarska - Do kompletu",
    "rękawic": "Kalosze / Więcej par - Dobij do progu BHP",
    "nagrzewnic": "Druga sztuka - Rabat Wielosztuka!",
    "wciągark": "Zblocze / Uchwyt - Promocja"
}

DEFAULT_SUGGESTION = "Chemia warsztatowa / Zmywacze (Uniwersalne)"

# ==========================================
# 2. SILNIK ANALIZY (Core Logic)
# ==========================================

def clean_text(text):
    """Czyści tekst z PDFa"""
    if not text: return ""
    return text.replace('\xa0', ' ')

def extract_client_data(text):
    """
    Zaawansowany algorytm ekstrakcji danych NABYWCY.
    Ignoruje dane GEKO.
    """
    lines = text.splitlines()
    client_name = ""
    client_nip = ""
    
    # 1. Szukanie NIPu (Każdy 10-cyfrowy ciąg, który NIE jest moim NIPem)
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459": # Hardcoded MY_NIP
            client_nip = nip
            break

    # 2. Szukanie Nazwy Firmy (Sekcja Nabywca)
    capture_mode = False
    candidates = []
    
    for line in lines:
        # Wyzwalacz szukania
        if "Nabywca" in line or "Płatnik" in line:
            capture_mode = True
            continue
        
        # Wyzwalacz końca szukania
        if capture_mode and ("Sprzedawca" in line or "Adres dostawy" in line or "Data" in line):
            capture_mode = False
            
        if capture_mode:
            clean = line.strip()
            # Filtry: Musi być długie, nie zawierać GEKO, nie być NIPem
            if len(clean) > 3 and "GEKO" not in clean.upper() and not re.search(r'\d{10}', clean.replace('-','')):
                 candidates.append(clean)

    if candidates:
        client_name = candidates[0] # Bierzemy pierwszą sensowną linię pod "Nabywca"
    else:
        client_name = "Nie wykryto nazwy"

    return client_name, client_nip

def extract_amount(text):
    """Wyciąga największą kwotę (Netto/Brutto) z dokumentu"""
    try:
        # Szuka formatów: 1234.56 lub 1 234,56
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = []
        for a in amounts:
            # Normalizacja do float (usuń spacje, zamień przecinek na kropkę)
            clean = float(a.replace(' ', '').replace(',', '.'))
            clean_amounts.append(clean)
        
        return max(clean_amounts) if clean_amounts else 0.0
    except:
        return 0.0

def analyze_promotion(text, amount):
    """Wybiera najlepszą promocję na podstawie zawartości i kwoty"""
    text_lower = text.lower()
    
    best_promo = None
    min_gap = 99999.0
    
    # Sortujemy od najniższego progu, żeby znaleźć pierwszy osiągalny
    sorted_promos = sorted(PROMOS, key=lambda x: x[1])
    
    # 1. Najpierw sprawdzamy dedykowane (Kominiarka, BHP)
    dedicated_found = False
    for keywords, threshold, reward, name in sorted_promos:
        if keywords and any(k in text_lower for k in keywords):
            gap = threshold - amount
            # Jeśli to dedykowana promocja i brakuje > 0
            if gap > 0:
                 if gap < min_gap:
                     min_gap = gap
                     best_promo = (name, threshold, reward)
                     dedicated_found = True
            # Jeśli dedykowana już spełniona, szukamy wyższej dedykowanej (np. BHP Duża)
            elif gap <= 0:
                 # Sprawdzamy czy jest wyższy próg w tej samej kategorii
                 pass 

    # 2. Jeśli nie znaleziono dedykowanej (lub już spełniona), szukamy ogólnej
    if not best_promo:
        for keywords, threshold, reward, name in sorted_promos:
            if not keywords: # To są promocje ogólne
                gap = threshold - amount
                if gap > 0 and gap < min_gap:
                    min_gap = gap
                    best_promo = (name, threshold, reward)

    # Fallback: Jeśli wszystko spełnione (np. faktura na 5000 zł)
    if not best_promo:
         return ("MAX", 0.0, "Wszystko zdobyte!"), 0.0
         
    return best_promo, min_gap

def get_smart_suggestion(text):
    text_lower = text.lower()
    for keyword, suggestion in SUGGESTIONS.items():
        if keyword in text_lower:
            return suggestion
    return DEFAULT_SUGGESTION

def send_email_report(data, secrets):
    if not secrets: return False
    
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {data['client']} - Brakuje {data['gap']:.0f} zł"
    
    body = f"""
    RAPORT ZAMÓWIENIA
    -------------------------------------
    KLIENT: {data['client']}
    NIP:    {data['nip']}
    KWOTA:  {data['amount']:.2f} zł
    -------------------------------------
    CEL:     {data['promo_name']} ({data['promo_target']} zł)
    BRAKUJE: {data['gap']:.2f} zł
    -------------------------------------
    💡 SUGEROWANE DOMÓWIENIE:
    {data['suggestion']}
    """
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        s = smtplib.SMTP('smtp.gmail.com', 587)
        s.starttls()
        s.login(secrets["EMAIL_NADAWCY"], secrets["HASLO_NADAWCY"])
        s.sendmail(secrets["EMAIL_NADAWCY"], secrets["EMAIL_ODBIORCY"], msg.as_string())
        s.quit()
        return True
    except: return False

# ==========================================
# 3. INTERFEJS UŻYTKOWNIKA (UI)
# ==========================================
st.set_page_config(page_title="GEKO PRO", page_icon="🚀", layout="centered")

# CSS - Wygląd Mobilny Premium
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        height: 60px;
        font-size: 24px;
        font-weight: bold;
        background-color: #FF4B4B;
        color: white;
        border-radius: 10px;
    }
    .big-metric { font-size: 30px !important; }
    .success-box { padding: 20px; background-color: #d4edda; border-radius: 10px; color: #155724; }
    .alert-box { padding: 20px; background-color: #f8d7da; border-radius: 10px; color: #721c24; }
</style>
""", unsafe_allow_html=True)

# Pobranie haseł (Fail-safe)
try:
    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
except: SECRETS = None

st.title("🚀 GEKO SYSTEM v3.0")
st.caption("Inteligentna Analiza Faktur B2B")

uploaded_file = st.file_uploader("📂 Wrzuć Fakturę (PDF)", type="pdf")

if uploaded_file:
    # 1. Parsowanie PDF
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            raw_text += page.extract_text() or ""
    
    text = clean_text(raw_text)
    
    # 2. Ekstrakcja Danych
    detected_client, detected_nip = extract_client_data(text)
    detected_amount = extract_amount(text)
    
    # 3. Formularz Weryfikacji (NA GÓRZE - Najważniejsze)
    st.markdown("### 📝 Weryfikacja Danych")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        final_client = st.text_input("Klient", value=detected_client)
        final_nip = st.text_input("NIP", value=detected_nip)
    with col2:
        final_amount = st.number_input("Kwota (PLN)", value=float(detected_amount), step=10.0)

    # 4. Logika Biznesowa (Działa na żywo po edycji)
    if final_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, final_amount)
        suggestion = get_smart_suggestion(text)
        
        st.markdown("---")
        
        # Pasek postępu
        if p_target > 0:
            progress = min(final_amount / p_target, 1.0)
            st.progress(progress, text=f"Postęp: {int(progress*100)}% (Cel: {p_target} zł)")
        
        # WYNIKI
        if gap <= 0:
            st.markdown(f"""
            <div class="success-box">
                <h3>✅ CEL OSIĄGNIĘTY!</h3>
                <p>Promocja: <strong>{p_name}</strong></p>
                <p>Nagroda: <strong>{p_reward}</strong></p>
            </div>
            """, unsafe_allow_html=True)
            st.balloons()
            
        elif gap > MAX_GAP:
            st.info(f"🔵 Brakuje {gap:.2f} zł. Powyżej limitu {MAX_GAP} zł. Nie dzwonimy.")
            
        else:
            # ALARM SPRZEDAŻOWY
            st.markdown(f"""
            <div class="alert-box">
                <h3>🔥 ALARM! BRAKUJE {gap:.2f} ZŁ</h3>
                <p>Cel: {p_name}</p>
                <p>Nagroda: {p_reward}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Sekcja Rekomendacji
            with st.container(border=True):
                st.markdown(f"**💡 TWOJA PODPOWIEDŹ:**")
                st.markdown(f"### {suggestion}")
                
                # Gotowiec SMS
                sms = f"Dzień dobry! Tu GEKO. Brakuje Panu {gap:.0f} zł do promocji '{p_name}'. Może dorzucimy {suggestion.split(' - ')[0]}?"
                st.code(sms, language="text")
                st.caption("Kliknij ikonkę obok tekstu, żeby skopiować")

            # Przycisk Maila
            if st.button("📧 WYŚLIJ DO MNIE RAPORT"):
                report_data = {
                    "client": final_client,
                    "nip": final_nip,
                    "amount": final_amount,
                    "gap": gap,
                    "promo_name": p_name,
                    "promo_target": p_target,
                    "suggestion": suggestion
                }
                
                if send_email_report(report_data, SECRETS):
                    st.toast("Mail wysłany pomyślnie!", icon="✅")
                else:
                    st.error("Błąd wysyłki maila. Sprawdź hasła w Secrets.")

    else:
        st.warning("⚠️ Nie wykryto kwoty. Wpisz ją ręcznie powyżej.")
