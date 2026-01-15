import streamlit as st
import pdfplumber
import re
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ KONFIGURACJA
# ==========================================
MOJ_NIP = "7722420459"
MOJA_NAZWA = "GEKO" # Twoja nazwa, żeby system ją ignorował

# PROGI
PROG_OGOLNY_1 = 1000.00
NAGRODA_OGOLNA_1 = "Bluza Polarowa (za 1 zł)"
PROG_OGOLNY_2 = 3000.00
NAGRODA_OGOLNA_2 = "Nagroda PREMIUM"

PROG_KOMINIARSKI = 200.00
NAGRODA_KOMINIARSKA = "T-SHIRT GEKO (za 0.01 zł)"

PROG_BHP_MALY = 250.00
NAGRODA_BHP_MALA = "Wieszak G90406 (za 1 zł)"
PROG_BHP_DUZY = 500.00
NAGRODA_BHP_DUZA = "Rabat 3% + Wieszak"

LIMIT_INTERWENCJI = 300.00 

# ==========================================
# 🧠 MÓZG SYSTEMU - INTELIGENTNE PODPOWIADANIE
# ==========================================
# System szuka słowa kluczowego (po lewej) i dobiera produkt (po prawej)
INTELIGENTNE_REGULY = {
    # --- GRUPA: PIŁY I DREWNO ---
    "Prowadnica": {"produkt": "Ostrzałka łańcuchów (G81207)", "opis": "Klient serwisuje piły. Ostrzałka to idealny dodatek."},
    "Łańcuch": {"produkt": "Olej do smarowania (G82000)", "opis": "Produkt eksploatacyjny. Kto tnie, ten musi smarować."},
    "Siekiera": {"produkt": "Ostrzałka 2w1 (T02-009)", "opis": "Mała, tania ostrzałka do siekier i noży."},
    
    # --- GRUPA: WARSZTAT SAMOCHODOWY ---
    "Wykrętak": {"produkt": "Zestaw gwintowników (G38301)", "opis": "Jak wykręca urwane śruby, to pewnie musi poprawić gwint."},
    "Prostownik": {"produkt": "Kable rozruchowe (G02400)", "opis": "Zestaw zimowy: Prostownik + Kable."},
    "Podnośnik": {"produkt": "Kobyłki warsztatowe (G02160)", "opis": "BHP: Podnośnik zawsze sprzedajemy z kobyłkami."},
    "Klucz udar": {"produkt": "Nasadki udarowe (zestaw)", "opis": "Do klucza pneumatycznego/elektrycznego potrzebne są nasadki."},
    
    # --- GRUPA: KOMINIARSKA (GAZETKA) ---
    "Szczotka": {"produkt": "Kula kominiarska (G66718)", "opis": "PROMOCJA: Buduj zestaw (Szczotka+Kula+Lina) by dobić do 200 zł!"},
    "Kula": {"produkt": "Lina kominiarska", "opis": "PROMOCJA: Masz kulę, brakuje liny do kompletu."},
    "Wycior": {"produkt": "Przepychacz elastyczny", "opis": "PROMOCJA: Dobij do 200 zł, T-shirt czeka."},
    
    # --- GRUPA: BHP (GAZETKA) ---
    "Rękawic": {"produkt": "Rękawice Zimowe Green/Orange", "opis": "PROMOCJA: Przy 250 zł Wieszak, przy 500 zł RABAT 3%!"},
    "Kalosz": {"produkt": "Gumofilce EVA (G90550)", "opis": "PROMOCJA: Kalosze liczą się do progu 500 zł (Rabat)."},
    
    # --- GRUPA: PNEUMATYKA / SPAWALNICTWO ---
    "Pistolet": {"produkt": "Wąż pneumatyczny zakuty", "opis": "Do pistoletu niezbędny jest wąż."},
    "Spawark": {"produkt": "Przyłbica samościemniająca", "opis": "Ochrona oczu przy spawaniu to podstawa."},
    "Tarcza": {"produkt": "Okulary ochronne / Rękawice", "opis": "BHP - przy cięciu zawsze potrzebna ochrona."},
    
    # --- WIELOSZTUKI ---
    "Nagrzewnica": {"produkt": "Druga sztuka (Rabat Wielosztuka!)", "opis": "Wielosztuki: Przy 2 sztukach cena drastycznie spada!"},
}

DOMYSLNA_REKOMENDACJA = {"produkt": "Chemia warsztatowa / Zmywacze", "opis": "Uniwersalny produkt, by dobić brakującą kwotę."}

# ==========================================
# 🔧 FUNKCJE
# ==========================================

if 'historia' not in st.session_state:
    st.session_state['historia'] = []

def wyslij_maila(dane, rekomendacja, email_nadawcy, haslo_nadawcy, email_odbiorcy):
    msg = MIMEMultipart()
    msg['From'] = email_nadawcy
    msg['To'] = email_odbiorcy
    msg['Subject'] = f"🔔 UPSELL: {dane['firma']} (Brakuje {dane['brakuje']:.2f} zł)"
    
    body = f"""
    RAPORT SPRZEDAŻOWY
    ===============================
    KLIENT: {dane['firma']}
    NIP: {dane['nip']}
    ADRES: {dane['adres']}
    ===============================
    KWOTA ZAMÓWIENIA: {dane['netto']:.2f} zł
    CEL PROMOCJI: {dane['cel_nazwa']} ({dane['cel_kwota']} zł)
    BRAKUJE DO CELU: {dane['brakuje']:.2f} zł
    ===============================
    💡 CO DORZUCIĆ (SUGESTIA SYSTEMU):
    Produkt: {rekomendacja['produkt']}
    Dlaczego: {rekomendacja['opis']}
    """
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_nadawcy, haslo_nadawcy)
        server.sendmail(email_nadawcy, email_odbiorcy, msg.as_string())
        server.quit()
        return True
    except: return False

def analizuj_pdf(uploaded_file):
    try:
        text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t
        return text
    except: return ""

def wyciagnij_dane(text):
    # 1. Kwota
    kwoty = re.findall(r"(\d+[\.,]\d{2})\s?PLN", text)
    if not kwoty: kwoty = re.findall(r"(\d+[\.,]\d{2})", text)
    netto = max([float(k.replace(',', '.').replace(' ', '')) for k in kwoty]) if kwoty else 0.0

    # 2. Klient (Ignorowanie GEKO)
    firma = "Nieznana Firma"
    adres = "Brak adresu"
    nip = "Brak NIP"
    
    lines = text.splitlines()
    sekcja_klienta = False
    
    for i, line in enumerate(lines):
        # Wykrywamy początek sekcji nabywcy
        if "Nabywca" in line or "Płatnik" in line or "Odbiorca" in line:
            sekcja_klienta = True
            continue # Przeskakujemy sam nagłówek
            
        if sekcja_klienta:
            # Jak trafimy na sekcję Sprzedawca, to koniec szukania
            if "Sprzedawca" in line:
                sekcja_klienta = False
                continue
            
            # Szukamy nazwy firmy (musi być dłuższa niż 3 znaki i NIE może być GEKO)
            # Używamy .upper() żeby wyłapać też "geko", "Geko" itp.
            if len(line.strip()) > 3 and MOJA_NAZWA not in line.upper():
                if firma == "Nieznana Firma":
                    firma = line.strip()
                    # Często adres jest linię niżej
                    if i + 1 < len(lines):
                        adres = lines[i+1].strip()
        
        # NIP szukamy wszędzie, ale ignorujemy Twój
        found_nips = re.findall(r'\d{10}', line.replace('-', ''))
        for n in found_nips:
            if n != MOJ_NIP:
                nip = n

    return netto, nip, firma, adres

def detekcja_promocji(text, netto):
    text_lower = text.lower()
    cele = []
    
    # Logika priorytetów
    if any(x in text_lower for x in ['szczotk', 'wycior', 'kula', 'lina']):
        cele.append((PROG_KOMINIARSKI, NAGRODA_KOMINIARSKA, "Kominiarska"))
        
    if any(x in text_lower for x in ['rękawic', 'kalosz', 'gumofilc']):
        cele.append((PROG_BHP_MALY, NAGRODA_BHP_MALA, "BHP (Wieszak)"))
        cele.append((PROG_BHP_DUZY, NAGRODA_BHP_DUZA, "BHP (Rabat 3%)"))
        
    cele.append((PROG_OGOLNY_1, NAGRODA_OGOLNA_1, "Ogólna (Polar)"))
    cele.append((PROG_OGOLNY_2, NAGRODA_OGOLNA_2, "Ogólna (Premium)"))

    # Sortowanie i wybór celu
    cele.sort(key=lambda x: x[0])
    wybrany = (PROG_OGOLNY_1, NAGRODA_OGOLNA_1, "Ogólna")
    
    min_brak = 99999.0
    for prog, nagroda, nazwa in cele:
        brakuje = prog - netto
        # Szukamy celu, który jest NAJBLIŻEJ, ale jeszcze nie osiągnięty
        if brakuje > 0 and brakuje < min_brak:
            min_brak = brakuje
            wybrany = (prog, nagroda, nazwa)
            
    return wybrany

def znajdz_rekomendacje(text):
    # Iterujemy po słowniku reguł i szukamy pasujących słów
    for slowo_klucz, regula in INTELIGENTNE_REGULY.items():
        if slowo_klucz.lower() in text.lower():
            return regula
    return DOMYSLNA_REKOMENDACJA

# ==========================================
# 📱 INTERFEJS APLIKACJI
# ==========================================
st.set_page_config(page_title="GEKO Asystent PRO", page_icon="🧠")

try:
    EMAIL_NADAWCY = st.secrets["EMAIL_NADAWCY"]
    HASLO_NADAWCY = st.secrets["HASLO_NADAWCY"]
    EMAIL_ODBIORCY = st.secrets["EMAIL_ODBIORCY"]
except: EMAIL_NADAWCY = None

st.title("🧠 GEKO Asystent - Wersja PRO")
st.markdown("**Inteligentne podpowiadanie + Baza Gazetek**")

uploaded_file = st.file_uploader("Wrzuć zamówienie (PDF)", type="pdf")

if uploaded_file:
    text = analizuj_pdf(uploaded_file)
    if text:
        # Automatyczne czytanie
        netto_auto, nip, firma, adres = wyciagnij_dane(text)
        
        st.markdown("---")
        
        # Sekcja Edycji (Gdyby automat się pomylił)
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("👤 Klient (Nabywca)")
            firma_final = st.text_input("Nazwa firmy:", value=firma)
            st.caption(f"NIP: {nip} | {adres}")
        with col2:
            netto_final = st.number_input("Kwota Netto:", value=netto_auto, step=10.0)
            
        # --- ANALIZA MÓZGOWA ---
        cel_kwota, cel_nagroda, cel_nazwa = detekcja_promocji(text, netto_final)
        brakuje = cel_kwota - netto_final
        rekomendacja = znajdz_rekomendacje(text) # Tu działa Twój "idealny podpowiadacz"
        
        st.markdown("---")
        st.markdown(f"### 🎯 Cel: {cel_nazwa} ({cel_kwota} zł)")
        st.progress(min(netto_final/cel_kwota, 1.0))
        
        # WYNIKI
        if brakuje <= 0:
            st.success(f"✅ Próg zdobyty! Nagroda: {cel_nagroda}")
        elif brakuje > LIMIT_INTERWENCJI:
            st.warning(f"Do progu brakuje {brakuje:.2f} zł. Za dużo, by dzwonić.")
        else:
            # ALARM SPRZEDAŻOWY
            st.error(f"🔥 ALARM! Brakuje tylko {brakuje:.2f} zł")
            
            # WYŚWIETLANIE IDEALNEJ PODPOWIEDZI
            with st.container(border=True):
                st.markdown("### 💡 INTELIGENTNA PODPOWIEDŹ:")
                st.markdown(f"**Proponuj:** {rekomendacja['produkt']}")
                st.info(f"**Argument dla klienta:** {rekomendacja['opis']}")
                
                # Gotowiec SMS
                sms = f"Dzień dobry! Brakuje Panu {brakuje:.0f} zł do promocji '{cel_nazwa}'. Widzę, że zamówił Pan {next((k for k in INTELIGENTNE_REGULY if k.lower() in text.lower()), 'towar')}, więc może dorzucimy {rekomendacja['produkt']}?"
                st.code(sms, language="text")
                st.caption("Skopiuj treść SMS")

            if st.button("📧 Wyślij Raport"):
                dane = {"firma": firma_final, "nip": nip, "adres": adres, "netto": netto_final, "brakuje": brakuje, "cel_nazwa": cel_nazwa, "cel_kwota": cel_kwota}
                if EMAIL_NADAWCY:
                    wyslij_maila(dane, rekomendacja, EMAIL_NADAWCY, HASLO_NADAWCY, EMAIL_ODBIORCY)
                    st.toast("Wysłano!", icon="✅")
