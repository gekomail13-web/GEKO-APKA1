import streamlit as st
import pdfplumber
import re
import smtplib
import pandas as pd
import matplotlib.pyplot as plt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ KONFIGURACJA PROGÓW (WSZYSTKIE PROMOCJE)
# ==========================================

# 1. OGÓLNE (Dla każdego zamówienia)
PROG_OGOLNY_1 = 1000.00
NAGRODA_OGOLNA_1 = "Bluza Polarowa (za 1 zł)"

PROG_OGOLNY_2 = 3000.00
NAGRODA_OGOLNA_2 = "Nagroda PREMIUM (za 1 zł)"

# 2. SPECJALISTYCZNE (Z nowych gazetek)
PROG_KOMINIARSKI = 200.00
NAGRODA_KOMINIARSKA = "T-SHIRT GEKO (za 0.01 zł)"

PROG_BHP_MALY = 250.00
NAGRODA_BHP_MALA = "Wieszak G90406 (za 1 zł)"
PROG_BHP_DUZY = 500.00
NAGRODA_BHP_DUZA = "Rabat 3% + Wieszak"

LIMIT_INTERWENCJI = 300.00 # Maksymalna kwota braku, przy której dzwonimy
MOJ_NIP = "7722420459"

# BAZA WIEDZY - CO PROPONOWAĆ?
INTELIGENTNE_REGULY = {
    # --- KOMINIARKA (GAZETKA) ---
    "Szczotka": {"produkt": "Kula kominiarska (G66718)", "cena": 35.00, "opis": "Kominiarka: Dobij do 200 zł po T-shirt!"},
    "Wycior": {"produkt": "Przepychacz elastyczny", "cena": 55.00, "opis": "Kominiarka: Brakuje do 200 zł?"},
    "Kula": {"produkt": "Lina kominiarska", "cena": 40.00, "opis": "Kominiarka: Zestaw do kuli."},
    
    # --- RĘKAWICE I KALOSZE (BHP) ---
    "Rękawic": {"produkt": "Rękawice Zimowe Green/Orange", "cena": 15.00, "opis": "BHP: Przy 250 zł wieszak, przy 500 zł RABAT 3%!"},
    "Kalosz": {"produkt": "Gumofilce EVA (G90550)", "cena": 45.00, "opis": "Kalosze: Przy 500 zł wchodzi rabat 3%!"},
    "Gumofilc": {"produkt": "Wkładki do butów", "cena": 10.00, "opis": "Dobij do 250 zł po gratis."},

    # --- OGÓLNE ---
    "Prowadnica": {"produkt": "Ostrzałka (G81207)", "cena": 79.29, "opis": "Serwis pił - towar powiązany"},
    "Nagrzewnica": {"produkt": "Druga sztuka (Rabat!)", "cena": 164.76, "opis": "Wielosztuki: Taniej przy 2 szt."},
}

DOMYSLNA_REKOMENDACJA = {"produkt": "Chemia warsztatowa / Zmywacze", "cena": 50.00, "opis": "Idealny produkt, by dobić do progu"}

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
    RAPORT ASYSTENTA GEKO
    ===============================
    👤 KLIENT: {dane['firma']} (NIP: {dane['nip']})
    📍 ADRES: {dane['adres']}
    ===============================
    💰 NETTO: {dane['netto']:.2f} zł
    🎯 CEL: {dane['cel_nazwa']} ({dane['cel_kwota']} zł)
    📉 BRAKUJE: {dane['brakuje']:.2f} zł
    ===============================
    💡 REKOMENDACJA: {rekomendacja['produkt']}
    📝 ARGUMENT: {rekomendacja['opis']}
    """
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_nadawcy, haslo_nadawcy)
        server.sendmail(email_nadawcy, email_odbiorcy, msg.as_string())
        server.quit()
        return True
    except Exception: return False

def analizuj_pdf(uploaded_file):
    try:
        text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t
        return text
    except: return ""

def detekcja_promocji(text, netto):
    """
    Mózg aplikacji: Wybiera NAJLEPSZĄ promocję dla klienta.
    Sprawdza, co jest najbliżej zasięgu.
    """
    text_lower = text.lower()
    najlepsza_opcja = (PROG_OGOLNY_1, NAGRODA_OGOLNA_1, "Ogólna (1000 zł)") # Domyślna
    min_brak = 99999.0
    
    # Lista potencjalnych celów
    cele = []
    
    # 1. Czy są produkty Kominiarskie?
    if any(x in text_lower for x in ['szczotk', 'wycior', 'kula', 'lina', 'przepychacz']):
        cele.append((PROG_KOMINIARSKI, NAGRODA_KOMINIARSKA, "🔥 Kominiarska"))

    # 2. Czy są produkty BHP (Rękawice/Kalosze)?
    if any(x in text_lower for x in ['rękawic', 'kalosz', 'gumofilc', 'obuwie']):
        cele.append((PROG_BHP_MALY, NAGRODA_BHP_MALA, "🔥 BHP (Wieszak)"))
        cele.append((PROG_BHP_DUZY, NAGRODA_BHP_DUZA, "🔥 BHP (Rabat 3%)"))

    # 3. Zawsze dodajemy progi ogólne
    cele.append((PROG_OGOLNY_1, NAGRODA_OGOLNA_1, "Ogólna (Polar)"))
    cele.append((PROG_OGOLNY_2, NAGRODA_OGOLNA_2, "Ogólna (Premium)"))

    # WYBÓR NAJLEPSZEGO CELU (Tego, do którego brakuje najmniej, ale > 0)
    wybrany_cel = None
    
    # Sortujemy cele od najmniejszej kwoty progu
    cele.sort(key=lambda x: x[0])
    
    for prog, nagroda, nazwa in cele:
        brakuje = prog - netto
        # Interesuje nas cel, który jeszcze nie został osiągnięty, ale jest blisko
        if brakuje > 0:
            if brakuje < min_brak:
                min_brak = brakuje
                wybrany_cel = (prog, nagroda, nazwa)
        # Jeśli próg już osiągnięty, sprawdzamy następny wyższy
        elif brakuje <= 0 and abs(brakuje) < 50: 
             # Opcjonalnie: Info że próg właśnie zdobyty
             pass

    if wybrany_cel:
        return wybrany_cel
    else:
        # Jeśli wszystkie progi przekroczone, bierzemy najwyższy ogólny
        return (PROG_OGOLNY_2, NAGRODA_OGOLNA_2, "Ogólna (Premium)")

def wyciagnij_dane(text):
    # Szukanie kwoty
    kwoty = re.findall(r"(\d+[\.,]\d{2})\s?PLN", text)
    if not kwoty: kwoty = re.findall(r"(\d+[\.,]\d{2})", text)
    netto = max([float(k.replace(',', '.').replace(' ', '')) for k in kwoty]) if kwoty else 0.0

    # Szukanie firmy i NIP
    firma = "Nieznana Firma"
    adres = "Brak adresu"
    nip = "Brak NIP"
    
    if "Nabywca" in text:
        try:
            parts = text.split("Nabywca")
            if len(parts) > 1:
                lines = [l.strip() for l in parts[1].splitlines() if l.strip()]
                clean_lines = []
                for l in lines:
                    if "Adres dostawy" in l: break
                    clean_lines.append(l)
                
                if clean_lines:
                    firma = clean_lines[0][:50]
                    for l in clean_lines:
                        found_nip = re.findall(r'\d{10}', l.replace('-', ''))
                        if found_nip and found_nip[0] != MOJ_NIP:
                            nip = found_nip[0]
                    for l in clean_lines[1:]:
                        if nip not in l and len(l) > 5:
                            adres = l[:60]
                            break
        except: pass
    return netto, nip, firma, adres

def znajdz_rekomendacje(text):
    for slowo, regula in INTELIGENTNE_REGULY.items():
        if slowo.lower() in text.lower(): return regula
    return DOMYSLNA_REKOMENDACJA

# ==========================================
# 📱 INTERFEJS
# ==========================================
st.set_page_config(page_title="GEKO Master", page_icon="📈")

# CSS
st.markdown("""
    <style>
    .big-font { font-size:18px !important; }
    .stProgress > div > div > div > div { background-color: #28a745; }
    </style>
    """, unsafe_allow_html=True)

try:
    EMAIL_NADAWCY = st.secrets["EMAIL_NADAWCY"]
    HASLO_NADAWCY = st.secrets["HASLO_NADAWCY"]
    EMAIL_ODBIORCY = st.secrets["EMAIL_ODBIORCY"]
except: EMAIL_NADAWCY = None

st.title("📈 GEKO Sales Booster")
st.markdown("**Aktywne Gazetki:** Styczeń (1000/3000 zł), Kominiarska, Rękawice, Kalosze")

uploaded_file = st.file_uploader("Wrzuć fakturę (PDF)", type="pdf")

if uploaded_file:
    text = analizuj_pdf(uploaded_file)
    if text:
        # 1. Dane
        netto_auto, nip, firma, adres = wyciagnij_dane(text)
        
        st.markdown("---")
        # 2. Edycja
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(firma)
            st.caption(f"{nip} | {adres}")
        with col2:
            netto_final = st.number_input("Kwota Netto:", value=netto_auto, step=10.0)
        
        # 3. DETEKCJA NAJLEPSZEJ PROMOCJI
        cel_kwota, cel_nagroda, cel_nazwa = detekcja_promocji(text, netto_final)
        brakuje = cel_kwota - netto_final
        rekomendacja = znajdz_rekomendacje(text)
        
        # 4. WYNIK
        st.markdown(f"### 🎯 Cel: {cel_nazwa}")
        
        postep = min(netto_final / cel_kwota, 1.0)
        st.progress(postep, text=f"Postęp: {int(postep*100)}% ({netto_final:.2f} / {cel_kwota} zł)")
        
        if brakuje <= 0:
            st.balloons()
            st.success(f"✅ BRAWO! Próg {cel_kwota} zł zdobyty!")
            st.info(f"🎁 Nagroda: **{cel_nagroda}**")
            
            # Sprawdź czy jest sens walczyć o wyższy próg (np. 3000)
            if cel_kwota == 1000 and netto_final < 3000:
                 brakuje_do_3k = 3000 - netto_final
                 if brakuje_do_3k <= 500:
                     st.warning(f"🚀 Walcz dalej! Brakuje {brakuje_do_3k:.2f} zł do progu 3000 zł!")

        elif brakuje > LIMIT_INTERWENCJI:
            st.info(f"Brakuje {brakuje:.2f} zł. Powyżej limitu interwencji (300 zł).")
            
        else:
            # ALARM UPSELL
            st.error(f"🔥 ALARM! Brakuje tylko {brakuje:.2f} zł")
            st.write(f"🎁 Walczymy o: **{cel_nagroda}**")
            
            with st.container(border=True):
                st.markdown(f"**Proponuj:** {rekomendacja['produkt']}")
                st.caption(rekomendacja['opis'])
                st.markdown("---")
                sms = f"Dzień dobry! Brakuje Panu {brakuje:.0f} zł do promocji '{cel_nazwa}'. Może dorzucimy {rekomendacja['produkt']}?"
                st.code(sms, language="text")
                st.caption("Treść SMS")

            if st.button("📧 Wyślij Raport"):
                dane_mail = {
                    "firma": firma, "nip": nip, "adres": adres, 
                    "netto": netto_final, "brakuje": brakuje, 
                    "cel_nazwa": cel_nazwa, "cel_kwota": cel_kwota
                }
                if EMAIL_NADAWCY:
                    wyslij_maila(dane_mail, rekomendacja, EMAIL_NADAWCY, HASLO_NADAWCY, EMAIL_ODBIORCY)
                    st.toast("Wysłano!", icon="✅")
                else: st.error("Brak konfiguracji maila.")

        # Zapis historii
        uid = f"{firma}_{netto_final}"
        if not any(h['id'] == uid for h in st.session_state['historia']):
             st.session_state['historia'].append({"id": uid, "firma": firma, "netto": netto_final, "cel": cel_nazwa})

# --- STATYSTYKI ---
if st.session_state['historia']:
    st.markdown("---")
    df = pd.DataFrame(st.session_state['historia'])
    st.metric("Dzisiejszy Obrót", f"{df['netto'].sum():.2f} zł")
    st.dataframe(df[['firma', 'netto', 'cel']], hide_index=True)
