import streamlit as st
import pdfplumber
import re
import smtplib
import pandas as pd
import matplotlib.pyplot as plt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ KONFIGURACJA I MÓZG SYSTEMU
# ==========================================
PROG_KWOTOWY = 1000.00
NAGRODA_ZA_PROG = "Bluza Polarowa (za 1 zł)"
LIMIT_INTERWENCJI = 300.00
MOJ_NIP = "7722420459"

# Baza Inteligentnych Reguł (Możesz tu dopisywać nowe!)
INTELIGENTNE_REGULY = {
    "Prowadnica": {"produkt": "Ostrzałka (G81207)", "cena": 79.29, "opis": "Serwis pił łańcuchowych"},
    "Łańcuch": {"produkt": "Olej do łańcuchów (G82000)", "cena": 19.99, "opis": "Eksploatacja"},
    "Siekiera": {"produkt": "Ostrzałka 2w1 (T02-009)", "cena": 15.00, "opis": "Cross-sell do siekier"},
    "Wykrętaki": {"produkt": "Gwintowniki (G38301)", "cena": 50.89, "opis": "Naprawa gwintów po wykręcaniu"},
    "Nagrzewnica": {"produkt": "Druga sztuka (Rabat!)", "cena": 164.76, "opis": "Wielosztuki: Taniej przy 2 szt."},
    "Prostownik": {"produkt": "Kable rozruchowe (G02400)", "cena": 35.50, "opis": "Zestaw zimowy"},
    "Podnośnik": {"produkt": "Kobyłki warsztatowe (para)", "cena": 55.00, "opis": "BHP przy podnoszeniu"},
    "Tarcza": {"produkt": "Rękawice Wampirki (10 par)", "cena": 25.00, "opis": "BHP - zużywalne"},
    "Spawarka": {"produkt": "Przyłbica samościemniająca", "cena": 45.00, "opis": "Ochrona oczu"},
    "Pistolet": {"produkt": "Wąż pneumatyczny", "cena": 30.00, "opis": "Akcesoria pneumatyczne"}
}
DOMYSLNA_REKOMENDACJA = {"produkt": "Chemia warsztatowa", "cena": 50.00, "opis": "Uniwersalne dobicie do progu"}

# ==========================================
# 🔧 FUNKCJE
# ==========================================

# Inicjalizacja sesji (Pamięć podręczna aplikacji)
if 'historia' not in st.session_state:
    st.session_state['historia'] = []

def wyslij_maila(dane, rekomendacja, email_nadawcy, haslo_nadawcy, email_odbiorcy):
    msg = MIMEMultipart()
    msg['From'] = email_nadawcy
    msg['To'] = email_odbiorcy
    msg['Subject'] = f"🔔 UPSELL: {dane['firma']} (Brakuje {dane['brakuje']:.2f} zł)"
    
    body = f"""
    RAPORT ASYSTENTA GEKO
    --------------------------------
    👤 KLIENT: {dane['firma']}
    📍 ADRES: {dane['adres']}
    📞 NIP: {dane['nip']}
    --------------------------------
    💰 NETTO: {dane['netto']:.2f} zł
    📉 BRAKUJE: {dane['brakuje']:.2f} zł
    --------------------------------
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
    except Exception as e:
        return False

def analizuj_pdf(uploaded_file):
    try:
        text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted: text += extracted
        return text
    except Exception:
        return ""

def wyciagnij_dane(text):
    # Kwota
    kwoty = re.findall(r"(\d+[\.,]\d{2})\s?PLN", text)
    if not kwoty: kwoty = re.findall(r"(\d+[\.,]\d{2})", text)
    netto = max([float(k.replace(',', '.').replace(' ', '')) for k in kwoty]) if kwoty else 0.0

    # NIP
    nipy = re.findall(r'\d{10}', text.replace('-', ''))
    nip = next((n for n in nipy if n != MOJ_NIP), "Brak NIP")

    # Firma (Pod "Nabywca")
    firma = "Nieznana Firma"
    adres = "Brak adresu"
    if "Nabywca" in text:
        try:
            parts = text.split("Nabywca")
            if len(parts) > 1:
                blok = parts[1].strip().splitlines()
                if len(blok) > 0: firma = blok[0][:40]
                if len(blok) > 1 and "NIP" not in blok[1]: adres = blok[1][:50]
        except: pass
        
    return {"netto": netto, "nip": nip, "firma": firma, "adres": adres}

def znajdz_rekomendacje(text):
    for slowo, regula in INTELIGENTNE_REGULY.items():
        if slowo.lower() in text.lower(): return regula
    return DOMYSLNA_REKOMENDACJA

# ==========================================
# 📱 UI (WYGLĄD)
# ==========================================
st.set_page_config(page_title="GEKO Ultra", page_icon="💎", layout="centered")

# CSS dla lepszego wyglądu
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .success { color: #28a745; }
    .warning { color: #ffc107; }
    .danger { color: #dc3545; }
    </style>
    """, unsafe_allow_html=True)

try:
    EMAIL_NADAWCY = st.secrets["EMAIL_NADAWCY"]
    HASLO_NADAWCY = st.secrets["HASLO_NADAWCY"]
    EMAIL_ODBIORCY = st.secrets["EMAIL_ODBIORCY"]
except:
    EMAIL_NADAWCY = None

# --- ZAKŁADKI ---
tab1, tab2 = st.tabs(["📥 SKANER FAKTUR", "📊 STATYSTYKI SESJI"])

with tab1:
    st.header("💎 GEKO Sales Booster Ultra")
    uploaded_file = st.file_uploader("Wrzuć fakturę (PDF)", type="pdf")

    if uploaded_file:
        text = analizuj_pdf(uploaded_file)
        if text:
            dane = wyciagnij_dane(text)
            rekomendacja = znajdz_rekomendacje(text)
            brakuje = PROG_KWOTOWY - dane['netto']
            dane['brakuje'] = brakuje # Dodajemy do słownika

            # Zapis do historii (tylko raz dla danego pliku w sesji)
            if not any(h['firma'] == dane['firma'] and h['netto'] == dane['netto'] for h in st.session_state['historia']):
                st.session_state['historia'].append({
                    "firma": dane['firma'], "netto": dane['netto'], 
                    "status": "OK" if brakuje <= 0 else ("ALARM" if brakuje <= LIMIT_INTERWENCJI else "SKIP")
                })

            # --- WIDOK GŁÓWNY ---
            st.markdown("---")
            col1, col2 = st.columns([1, 1])
            with col1:
                st.subheader("👤 Klient")
                st.write(f"**{dane['firma']}**")
                st.caption(f"NIP: {dane['nip']}")
                st.caption(dane['adres'])
            with col2:
                st.subheader("💰 Finanse")
                st.metric("Netto", f"{dane['netto']:.2f} zł")
                postep = min(dane['netto'] / PROG_KWOTOWY, 1.0)
                st.progress(postep, text=f"Postęp do nagrody: {int(postep*100)}%")

            # --- LOGIKA DECYZYJNA ---
            st.markdown("---")
            if brakuje <= 0:
                st.success(f"✅ BRAWO! Próg {PROG_KWOTOWY} zł przekroczony! Nagroda przysługuje.")
                st.balloons()
            
            elif brakuje > LIMIT_INTERWENCJI:
                st.info(f"🔵 Brakuje {brakuje:.2f} zł. To powyżej limitu {LIMIT_INTERWENCJI} zł. Nie dzwonimy.")
            
            else:
                # ALARM - UPSELL
                st.error(f"🔥 ALARM SPRZEDAŻOWY! Brakuje tylko {brakuje:.2f} zł")
                
                with st.container():
                    st.markdown(f"### 💡 Proponuj: {rekomendacja['produkt']}")
                    st.markdown(f"*{rekomendacja['opis']}*")
                    
                    # Gotowiec do skopiowania
                    msg_text = f"Dzień dobry! Tu GEKO. Dziękujemy za zamówienie. Brakuje Panu tylko {brakuje:.2f} zł do darmowej bluzy polarowej! Może dorzucimy {rekomendacja['produkt']}? Akurat pasuje do zamówienia."
                    st.code(msg_text, language="text")
                    st.caption("👆 Skopiuj treść SMS/Wiadomości")

                # Przycisk maila
                if st.button("📧 Wyślij raport do centrali"):
                    if EMAIL_NADAWCY:
                        if wyslij_maila(dane, rekomendacja, EMAIL_NADAWCY, HASLO_NADAWCY, EMAIL_ODBIORCY):
                            st.toast("Mail wysłany pomyślnie!", icon="🚀")
                        else:
                            st.error("Błąd wysyłki.")
                    else:
                        st.warning("Skonfiguruj hasła w Secrets.")
        else:
            st.error("Nie udało się odczytać pliku PDF. Sprawdź czy nie jest uszkodzony.")

with tab2:
    st.header("📊 Twoje Statystyki (Ta sesja)")
    
    if st.session_state['historia']:
        df = pd.DataFrame(st.session_state['historia'])
        
        # Podsumowanie liczbowe
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Zeskanowane", len(df))
        col_b.metric("Łączny Obrót", f"{df['netto'].sum():.2f} zł")
        okazje = len(df[df['status'] == 'ALARM'])
        col_c.metric("Znalezione Okazje", okazje, delta_color="inverse")
        
        # Wykres
        st.subheader("Obrót vs Status")
        fig, ax = plt.subplots()
        colors = {'OK': 'green', 'ALARM': 'red', 'SKIP': 'gray'}
        df['color'] = df['status'].map(colors)
        
        ax.bar(df['firma'], df['netto'], color=df['color'])
        plt.xticks(rotation=45, ha='right')
        plt.ylabel("Kwota Netto (PLN)")
        st.pyplot(fig)
        
        st.dataframe(df)
        
        if st.button("Wyczyść historię"):
            st.session_state['historia'] = []
            st.rerun()
    else:
        st.info("Zeskanuj pierwsze faktury, aby zobaczyć wykresy.")
