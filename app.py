import streamlit as st
import pdfplumber
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 1. KONFIGURACJA "MÓZGU" (Baza Wiedzy z Gazetek)
# ==========================================

# Dane Sprzedawcy (Do ignorowania)
MOJ_NIP = "7722420459"
MOJA_NAZWA = "GEKO"

# Limit interwencji (ile może brakować, żebyśmy dzwonili)
MAX_BRAK_PLN = 300.00

# --- BAZA PROMOCJI (Reguły) ---
# Format: (Słowa kluczowe, Próg, Nagroda, Nazwa Promocji)
PROMOS = [
    # KOMINIARSKA AB.pdf
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "zestaw komin", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    
    # RĘKAWICE AB.pdf + KALOSZE AB.pdf (Łączymy w BHP)
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    
    # OGÓLNE (GAZETKA STYCZEŃ)
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

# --- BAZA WIELOSZTUKI (2026AB.pdf) ---
# Jeśli znajdzie ten kod/nazwę, sugeruje domówienie do pary
WIELOSZTUKI = {
    "g01097": "Wciągarka 3T - Taniej przy 2 szt!",
    "g01362": "Nożyce do drutu - Taniej przy 2 szt!",
    "g02180": "Podnośnik ATV - Taniej przy 2 szt!",
    "g73866": "Łańcuchy śniegowe - Zestaw tańszy!",
    "g80443": "Grzejnik Konwektor - Taniej przy 2 szt!",
    "g80444": "Grzejnik LCD - Taniej przy 2 szt!",
    "g80446": "Grzejnik Szklany - Taniej przy 2 szt!",
    "g02648": "Klucze - Sprawdź progi ilościowe!",
    "nagrzewnic": "Sprawdź czy nie taniej w wielosztuce (2026AB)!"
}

# --- BAZA CROSS-SELLING (Inteligentne sugestie) ---
SUGESTIE_CROSS = {
    "prowadnic": "Ostrzałka elektr. (G81207) - Serwis pił",
    "łańcuch": "Olej do łańcuchów (G82000) - Eksploatacja",
    "siekier": "Ostrzałka 2w1 (T02-009) - Tani dodatek",
    "wykrętak": "Gwintowniki (G38301) - Naprawa gwintów",
    "prostownik": "Kable rozruchowe (G02400) - Zestaw Zima",
    "podnośnik": "Kobyłki warsztatowe - Wymóg BHP",
    "pneumat": "Wąż zakuty / Szybkozłączki",
    "szczotk": "Kula + Lina - Zbuduj zestaw do 200 zł!",
    "kula": "Lina kominiarska - Do kompletu",
    "rękawic": "Kalosze / Więcej par - Dobij do progu BHP",
    "kalosz": "Wkładki filcowe / Rękawice"
}

# ==========================================
# 2. SILNIK ANALIZY
# ==========================================

def clean_text(text):
    if not text: return ""
    return text.replace('\xa0', ' ').replace('\n', ' ')

def extract_client_data(text):
    """Filtruje dane GEKO i wyciąga prawdziwego klienta"""
    lines = text.splitlines()
    client_name = ""
    client_nip = ""
    
    # 1. Szukanie NIP
    # Znajdź wszystkie NIPy, wybierz pierwszy, który nie jest Twój
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != MOJ_NIP:
            client_nip = nip
            break

    # 2. Szukanie Firmy (Sekcja Nabywca)
    capture = False
    candidates = []
    
    for line in lines:
        if "Nabywca" in line or "Płatnik" in line:
            capture = True
            continue
        
        # Stopery
        if capture and ("Sprzedawca" in line or "Adres" in line or "Data" in line):
            capture = False
            
        if capture:
            clean = line.strip()
            # Musi być długie, bez słowa GEKO/Sprzedawca, bez NIPu
            if len(clean) > 3 and MOJA_NAZWA not in clean.upper() and "SPRZEDAWCA" not in clean.upper():
                 # Dodatkowy filtr - odrzucamy linie z samym adresem (często mają cyfry kodu pocztowego)
                 if not re.search(r'\d{2}-\d{3}', clean):
                     candidates.append(clean)

    if candidates:
        client_name = candidates[0]
    else:
        client_name = "Klient Detaliczny / Nieznany"

    return client_name, client_nip

def extract_amount_and_codes(text):
    """Wyciąga kwotę netto oraz kody produktów z treści"""
    # 1. Kwota
    try:
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = [float(a.replace(' ', '').replace(',', '.')) for a in amounts]
        netto = max(clean_amounts) if clean_amounts else 0.0
    except:
        netto = 0.0
        
    # 2. Kody produktów (do wielosztuk) - Szukamy wzorców Gxxxxx
    found_codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches:
        found_codes.add(m.lower())
        
    return netto, found_codes

def analyze_promotion(text, amount):
    """Wybiera najlepszą promocję na podstawie zawartości koszyka"""
    text_lower = text.lower()
    best_promo = None
    min_gap = 99999.0
    
    # Sortujemy promocje po progu (od najmniejszego)
    sorted_promos = sorted(PROMOS, key=lambda x: x[1])
    
    # Strategia: Szukamy dedykowanej promocji, która nie jest osiągnięta
    dedicated_active = False
    
    for keywords, threshold, reward, name in sorted_promos:
        # Sprawdź czy to promocja tematyczna (ma słowa kluczowe)
        if keywords:
            if any(k in text_lower for k in keywords):
                gap = threshold - amount
                # Jeśli brakuje do progu, to jest priorytet
                if gap > 0:
                    if gap < min_gap:
                        min_gap = gap
                        best_promo = (name, threshold, reward)
                        dedicated_active = True
                # Jeśli próg przekroczony, szukamy wyższego w tej samej kategorii
                # (np. mała BHP zdobyta, celujemy w dużą BHP)
                elif gap <= 0 and gap > -500: # Jeśli przekroczono niedużo, może walczymy o wyższy?
                    continue 

    # Jeśli nie ma aktywnej dedykowanej (lub wszystkie zdobyte), sprawdzamy ogólne
    if not dedicated_active:
        for keywords, threshold, reward, name in sorted_promos:
            if not keywords: # Promocje ogólne
                gap = threshold - amount
                if gap > 0 and gap < min_gap:
                    min_gap = gap
                    best_promo = (name, threshold, reward)

    # Fallback - wszystko zdobyte
    if not best_promo:
         return ("MAX", 0.0, "Wszystkie progi zdobyte!"), 0.0
         
    return best_promo, min_gap

def get_smart_suggestions(text, found_codes):
    """Generuje listę porad (Cross-sell + Wielosztuki)"""
    suggestions = []
    text_lower = text.lower()
    
    # 1. Sprawdź Wielosztuki (2026AB)
    for code, msg in WIELOSZTUKI.items():
        if code in found_codes or (code in text_lower and len(code)>3):
            suggestions.append(f"📦 **WIELOSZTUKA:** {msg}")
            
    # 2. Sprawdź Cross-selling
    for key, advice in SUGESTIE_CROSS.items():
        if key in text_lower:
            suggestions.append(f"💡 **SUGESTIA:** {advice}")
            
    if not suggestions:
        suggestions.append("💡 **SUGESTIA:** Chemia warsztatowa / Zmywacze (Dobicie do progu)")
        
    return suggestions

def send_email_report(data, secrets):
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {data['client']} - Brakuje {data['gap']:.0f} zł"
    
    sugestie_txt = "\n".join(data['suggestions'])
    
    body = f"""
    RAPORT ZAMÓWIENIA
    -------------------------------------
    KLIENT: {data['client']}
    NIP:    {data['nip']}
    KWOTA:  {data['amount']:.2f} zł
    -------------------------------------
    CEL:     {data['promo_name']} ({data['promo_target']} zł)
    BRAKUJE: {data['gap']:.2f} zł
    NAGRODA: {data['promo_reward']}
    -------------------------------------
    PODPOWIEDZI DLA HANDLOWCA:
    {sugestie_txt}
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
# 3. INTERFEJS (Streamlit)
# ==========================================
st.set_page_config(page_title="GEKO MONSTER", page_icon="🦖", layout="centered")

# CSS - Wygląd "Monster"
st.markdown("""
<style>
    .stButton>button {
        width: 100%; height: 70px; font-size: 26px; font-weight: bold;
        background: linear-gradient(90deg, #FF4B4B 0%, #FF914D 100%);
        color: white; border: none; border-radius: 12px;
    }
    .big-box {
        padding: 20px; border-radius: 15px; margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .success-mode { background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; }
    .alert-mode { background-color: #f8d7da; color: #842029; border: 1px solid #f5c2c7; }
    .info-mode { background-color: #cff4fc; color: #055160; border: 1px solid #b6effb; }
</style>
""", unsafe_allow_html=True)

# Hasła
try:
    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
except: SECRETS = None

st.title("🦖 GEKO MONSTER 5.0")
st.markdown("**Analiza: Styczeń | Kominiarska | BHP | Wielosztuki**")

uploaded_file = st.file_uploader("📂 WRZUĆ ZAMÓWIENIE (PDF)", type="pdf")

if uploaded_file:
    # 1. Parsowanie
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            raw_text += page.extract_text() or ""
    
    text = clean_text(raw_text)
    
    # 2. Ekstrakcja danych
    d_client, d_nip = extract_client_data(text)
    d_amount, d_codes = extract_amount_and_codes(text)
    
    # 3. PANEL WERYFIKACJI (Na górze)
    st.info("👇 SPRAWDŹ DANE PRZED ANALIZĄ 👇")
    col1, col2 = st.columns([2, 1])
    with col1:
        f_client = st.text_input("KLIENT", value=d_client)
        f_nip = st.text_input("NIP", value=d_nip)
    with col2:
        f_amount = st.number_input("KWOTA NETTO", value=float(d_amount), step=10.0)

    # 4. LOGIKA
    if f_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, f_amount)
        suggestions = get_smart_suggestions(text, d_codes)
        
        st.divider()
        
        # Pasek postępu
        if p_target > 0:
            prog = min(f_amount / p_target, 1.0)
            st.progress(prog, text=f"Postęp: {int(prog*100)}% (Cel: {p_target} zł)")

        # WYNIKI
        if gap <= 0:
            st.markdown(f"""
            <div class="big-box success-mode">
                <h2>✅ ZDOBYTE: {p_reward}</h2>
                <p>Promocja: {p_name}</p>
            </div>
            """, unsafe_allow_html=True)
            st.balloons()
            
        elif gap > MAX_BRAK_PLN:
            st.markdown(f"""
            <div class="big-box info-mode">
                <h3>🔵 Brakuje {gap:.2f} zł</h3>
                <p>Cel: {p_name} ({p_target} zł)</p>
                <small>Powyżej limitu {MAX_BRAK_PLN} zł - nie dzwonimy.</small>
            </div>
            """, unsafe_allow_html=True)
            
        else:
            # ALARM
            st.markdown(f"""
            <div class="big-box alert-mode">
                <h1>🔥 BRAKUJE {gap:.2f} ZŁ</h1>
                <h3>Nagroda: {p_reward}</h3>
                <p>Promocja: {p_name}</p>
            </div>
            """, unsafe_allow_html=True)
            
            # SUGESTIE
            with st.container(border=True):
                st.subheader("💡 CO ZAPROPONOWAĆ?")
                for sug in suggestions:
                    st.markdown(sug)
                
                st.divider()
                # SMS GENERATOR
                top_sug = suggestions[0].split(':')[-1].strip().replace('*', '')
                sms = f"Dzien dobry! Tu GEKO. Brakuje Panu {gap:.0f} zl do promocji '{p_name}'. Moze dorzucimy: {top_sug}?"
                st.code(sms, language="text")

            # EMAIL
            if st.button("📧 WYŚLIJ RAPORT"):
                report = {
                    "client": f_client, "nip": f_nip, "amount": f_amount,
                    "gap": gap, "promo_name": p_name, "promo_target": p_target,
                    "promo_reward": p_reward, "suggestions": suggestions
                }
                if send_email_report(report, SECRETS):
                    st.toast("Wysłano!", icon="✅")
                else:
                    st.error("Błąd wysyłki.")
                    
    else:
        st.warning("⚠️ Nie wykryto kwoty. Wpisz ją ręcznie.")
