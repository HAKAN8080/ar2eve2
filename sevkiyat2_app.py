import streamlit as st
import pandas as pd
import time
import altair as alt

# -------------------------------
# 0️⃣ Sayfa yapılandırması ve tema
# -------------------------------
st.set_page_config(
    page_title="EVE Sevkiyat Planlama",
    page_icon="📦",
    layout="wide"
)

# CSS ile küçük görsel iyileştirmeler
st.markdown(
    """
    <style>
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        padding: 10px 20px;
        border-radius: 8px;
        border: none;
        font-size: 16px;
        cursor: pointer;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    .stFileUploader>div {
        border: 2px dashed #4CAF50;
        border-radius: 8px;
        padding: 10px;
        background-color: #f9f9f9;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("📦 Thorius-EVE Replanishment")
st.markdown("**Adım 1:** CSV dosyalarını yükleyin ve ardından hesaplayın.", unsafe_allow_html=True)

# -------------------------------
# 1️⃣ CSV yükleme alanları (iki sütunlu düzen)
# -------------------------------
col1, col2 = st.columns(2)

with col1:
    sevkiyat_file = st.file_uploader("Sevkiyat CSV yükle", type=["csv"])
    depo_file = st.file_uploader("Depo Stok CSV yükle", type=["csv"])

with col2:
    cover_file = st.file_uploader("Cover CSV yükle", type=["csv"])
    kpi_file = st.file_uploader("KPI CSV yükle", type=["csv"])

st.markdown("---")  # yatay ayırıcı

# -------------------------------
# 2️⃣ Hesapla butonu
# -------------------------------
if st.button("🚀 Hesapla"):
    if not (sevkiyat_file and depo_file and cover_file and kpi_file):
        st.error("⚠️ Lütfen tüm dosyaları yükleyin!")
    else:
        start_time = time.time()

        # CSV'leri oku
        def read_csv(uploaded_file):
            try:
                return pd.read_csv(uploaded_file, encoding="utf-8")
            except pd.errors.ParserError:
                return pd.read_csv(uploaded_file, encoding="utf-8", sep="\t")

        df = read_csv(sevkiyat_file)
        depo_stok_df = read_csv(depo_file)
        cover_df = read_csv(cover_file)
        kpi_df = read_csv(kpi_file)

        for d in [df, depo_stok_df, cover_df, kpi_df]:
            d.columns = d.columns.str.strip().str.replace('\ufeff','')

        if "yolda" not in df.columns:
            df["yolda"] = 0

        # KPI ve Cover ekle
        df = df.merge(kpi_df, on="klasmankod", how="left")
        df = df.merge(cover_df, on="magaza_id", how="left")
        df["cover"] = df["cover"].fillna(999)
        df_filtered = df[df["cover"] <= 20].copy()

        # İhtiyaç hesabı
        df_filtered["ihtiyac"] = (
            (df_filtered["haftalik_satis"] * df_filtered["hedef_hafta"])
            - (df_filtered["mevcut_stok"] + df_filtered["yolda"])
        ).clip(lower=0)

        df_sorted = df_filtered.sort_values(by=["urun_id", "haftalik_satis"], ascending=[True, False]).copy()

        # Sevkiyat planı
        sevk_listesi = []

        for (depo, urun), grup in df_sorted.groupby(["depo_id", "urun_id"]):
            stok_idx = (depo_stok_df["depo_id"] == depo) & (depo_stok_df["urun_id"] == urun)
            stok = int(depo_stok_df.loc[stok_idx, "depo_stok"].sum()) if stok_idx.any() else 0

            # Tur 1
            for _, row in grup.iterrows():
                min_adet = row["min_adet"] if pd.notna(row["min_adet"]) else 0
                MAKS_SEVK = row["maks_adet"] if pd.notna(row["maks_adet"]) else 200
                ihtiyac = row["ihtiyac"]
                sevk = int(min(ihtiyac, stok, MAKS_SEVK)) if stok > 0 and ihtiyac > 0 else 0
                stok -= sevk
                sevk_listesi.append({
                    "depo_id": depo,
                    "magaza_id": row["magaza_id"],
                    "urun_id": urun,
                    "klasmankod": row["klasmankod"],
                    "tur": 1,
                    "ihtiyac": ihtiyac,
                    "yolda": row["yolda"],
                    "sevk_miktar": sevk,
                    "haftalik_satis": row["haftalik_satis"],
                    "mevcut_stok": row["mevcut_stok"],
                    "cover": row["cover"]
                })

            # Tur 2
            if stok > 0:
                for _, row in grup.iterrows():
                    if row["cover"] >= 12:
                        continue
                    min_adet = row["min_adet"] if pd.notna(row["min_adet"]) else 0
                    MAKS_SEVK = row["maks_adet"] if pd.notna(row["maks_adet"]) else 200
                    mevcut = row["mevcut_stok"] + row["yolda"]
                    eksik_min = max(0, min_adet - mevcut)
                    sevk2 = int(min(eksik_min, stok, MAKS_SEVK)) if eksik_min > 0 else 0
                    stok -= sevk2
                    sevk_listesi.append({
                        "depo_id": depo,
                        "magaza_id": row["magaza_id"],
                        "urun_id": urun,
                        "klasmankod": row["klasmankod"],
                        "tur": 2,
                        "ihtiyac": row["ihtiyac"],
                        "yolda": row["yolda"],
                        "sevk_miktar": sevk2,
                        "haftalik_satis": row["haftalik_satis"],
                        "mevcut_stok": row["mevcut_stok"],
                        "cover": row["cover"]
                    })

            if stok_idx.any():
                depo_stok_df.loc[stok_idx, "depo_stok"] = stok
            else:
                depo_stok_df = pd.concat([depo_stok_df, pd.DataFrame([{
                    "depo_id": depo, "urun_id": urun, "depo_stok": stok
                }])], ignore_index=True)

        sevk_df = pd.DataFrame(sevk_listesi)

        # Çıktılar
        total_sevk = sevk_df.groupby(
            ["depo_id", "magaza_id", "urun_id", "klasmankod"], as_index=False
        ).agg({
            "sevk_miktar": "sum",
            "yolda": "first",
            "haftalik_satis": "first",
            "ihtiyac": "first",
            "mevcut_stok": "first",
            "cover": "first"
        })

        toplam_sevk_adet = total_sevk["sevk_miktar"].sum()
        toplam_magaza = total_sevk["magaza_id"].nunique()
        toplam_satir = sevk_df.shape[0]
        toplam_min_tamamlama = sevk_df[sevk_df["tur"] == 2]["sevk_miktar"].sum()

        magaza_bazli = total_sevk.groupby("magaza_id")["sevk_miktar"].sum().reset_index().sort_values(by="sevk_miktar", ascending=False)
        urun_bazli = total_sevk.groupby("urun_id")["sevk_miktar"].sum().reset_index().sort_values(by="sevk_miktar", ascending=False)

        end_time = time.time()
        sure_sn = round(end_time - start_time, 2)

        # -------------------------------
        # ✅ İlk 20 mağaza bazlı sevk miktarı grafiği
        # -------------------------------
        magaza_top20 = magaza_bazli.head(20)

        st.subheader("📊 En Çok Sevk Alan İlk 20 Mağaza (Sevk Miktarı)")

        chart = alt.Chart(magaza_top20).mark_bar().encode(
            x=alt.X('magaza_id:N', title='Mağaza ID'),
            y=alt.Y('sevk_miktar:Q', title='Toplam Sevk Miktarı'),
            color=alt.Color('sevk_miktar:Q', scale=alt.Scale(scheme='greens')),
            tooltip=['magaza_id', 'sevk_miktar']
        )

        st.altair_chart(chart, use_container_width=True)

        # -------------------------------
        # ✅ Özet KPI’lar
        # -------------------------------
        st.subheader("📊 Genel KPI'lar")
        
        # Metrik kartlar
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("Toplam Sevk", f"{toplam_sevk_adet:,}", 
                      help="Toplam sevk edilen ürün miktarı")
        
        with col2:
            st.metric("Min Tamamlama", f"{toplam_min_tamamlama:,}", 
                      help="2. turda min stok tamamlamak için yapılan sevk")
        
        with col3:
            st.metric("Mağaza Sayısı", toplam_magaza, 
                      help="Sevkiyat yapılan toplam mağaza sayısı")
        
        with col4:
            ortalama_cover = total_sevk['cover'].mean() if not total_sevk.empty else 0
            st.metric("Ortalama Cover", f"{ortalama_cover:.2f}", 
                      help="Sevk yapılan mağazaların ortalama cover değeri")
        
        with col5:
            st.metric("İşlem Süresi", f"{sure_sn}s", 
                      help="Hesaplama için geçen süre")

        # -------------------------------
        # 3️⃣ Gelişmiş Raporlama ve Görselleştirme
        # -------------------------------
        st.markdown("---")
        st.header("📈 Detaylı Analiz ve Raporlar")
        
        # Sekmeli raporlar
        tab1, tab2, tab3, tab4 = st.tabs(["Mağaza Performansı", "Ürün Analizi", "Depo Durumu", "Tur Bazlı Dağılım"])
        
        with tab1:
            st.subheader("Mağaza Bazlı Performans Analizi")
            
            # Mağaza cover değerlerine göre sevkiyat dağılımı
            cover_bins = [0, 4, 8, 12, 16, 20]
            cover_labels = ["0-4", "5-8", "9-12", "13-16", "17-20"]
            total_sevk['cover_grubu'] = pd.cut(total_sevk['cover'], bins=cover_bins, labels=cover_labels)
            
            cover_summary = total_sevk.groupby('cover_grubu').agg({
                'magaza_id': 'count',
                'sevk_miktar': 'sum'
            }).rename(columns={'magaza_id': 'mağaza_sayısı', 'sevk_miktar': 'toplam_sevk'})
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Cover Gruplarına Göre Dağılım**")
                st.dataframe(cover_summary)
            
            with col2:
                chart_cover = alt.Chart(cover_summary.reset_index()).mark_arc(innerRadius=50).encode(
                    theta=alt.Theta(field="toplam_sevk", type="quantitative"),
                    color=alt.Color(field="cover_grubu", type="nominal", 
                                  legend=alt.Legend(title="Cover Aralığı")),
                    tooltip=['cover_grubu', 'toplam_sevk']
                ).properties(width=300, height=300, title="Cover Gruplarına Göre Sevkiyat Dağılımı")
                st.altair_chart(chart_cover)
        
        with tab2:
            st.subheader("Ürün Bazlı Analiz")
            
            # En çok sevk edilen ilk 10 ürün
            top10_urun = urun_bazli.head(10)
            
            chart_urun = alt.Chart(top10_urun).mark_bar().encode(
                x=alt.X('urun_id:N', title='Ürün ID', sort='-y'),
                y=alt.Y('sevk_miktar:Q', title='Sevk Miktarı'),
                color=alt.Color('sevk_miktar:Q', scale=alt.Scale(scheme='blues')),
                tooltip=['urun_id', 'sevk_miktar']
            ).properties(height=400, title="En Çok Sevk Edilen İlk 10 Ürün")
            
            st.altair_chart(chart_urun, use_container_width=True)
            
            # Ürün bazlı detay tablo
            urun_detay = total_sevk.groupby('urun_id').agg({
                'magaza_id': 'count',
                'sevk_miktar': 'sum',
                'haftalik_satis': 'mean'
            }).rename(columns={
                'magaza_id': 'sevk_yapılan_mağaza_sayısı',
                'sevk_miktar': 'toplam_sevk_miktarı',
                'haftalik_satis': 'ortalama_haftalık_satış'
            }).round(2)
            
            st.write("**Ürün Bazlı Detaylı Rapor**")
            st.dataframe(urun_detay.head(15))
        
        with tab3:
            st.subheader("Depo Bazlı Analiz")
            
            # Depo bazlı sevkiyat dağılımı
            depo_bazli = total_sevk.groupby("depo_id")["sevk_miktar"].sum().reset_index().sort_values(by="sevk_miktar", ascending=False)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Depo Bazlı Sevkiyat Dağılımı**")
                st.dataframe(depo_bazli)
            
            with col2:
                chart_depo = alt.Chart(depo_bazli).mark_bar().encode(
                    x=alt.X('depo_id:N', title='Depo ID', sort='-y'),
                    y=alt.Y('sevk_miktar:Q', title='Sevk Miktarı'),
                    color=alt.Color('sevk_miktar:Q', scale=alt.Scale(scheme='oranges')),
                    tooltip=['depo_id', 'sevk_miktar']
                ).properties(height=300, title="Depolara Göre Sevkiyat Dağılımı")
                st.altair_chart(chart_depo, use_container_width=True)
            
            # Depo stok durumu
            st.write("**Depo Stok Durumu (Sevkiyat Sonrası)**")
            st.dataframe(depo_stok_df[depo_stok_df['depo_stok'] > 0].sort_values('depo_stok', ascending=False))
        
        with tab4:
            st.subheader("Tur Bazlı Sevkiyat Analizi")
            
            # Tur bazlı dağılım
            tur_bazli = sevk_df.groupby("tur").agg({
                'sevk_miktar': 'sum',
                'magaza_id': 'nunique',
                'urun_id': 'nunique'
            }).rename(columns={
                'sevk_miktar': 'toplam_sevk',
                'magaza_id': 'farklı_mağaza_sayısı',
                'urun_id': 'farklı_ürün_sayısı'
            })
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Tur Bazlı Özet**")
                st.dataframe(tur_bazli)
            
            with col2:
                chart_tur = alt.Chart(tur_bazli.reset_index()).mark_arc(innerRadius=50).encode(
                    theta=alt.Theta(field="toplam_sevk", type="quantitative"),
                    color=alt.Color(field="tur", type="nominal", 
                                  legend=alt.Legend(title="Sevkiyat Turu")),
                    tooltip=['tur', 'toplam_sevk']
                ).properties(width=300, height=300, title="Turlara Göre Sevkiyat Dağılımı")
                st.altair_chart(chart_tur)
        
        # -------------------------------
        # 4️⃣ Çoklu İndirme Seçenekleri
        # -------------------------------
        st.markdown("---")
        st.header("📊 Raporları İndir")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Ana sevkiyat planı
            csv_out = total_sevk.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Ana Sevkiyat Planı (CSV)",
                data=csv_out,
                file_name="sevkiyat_planı.csv",
                mime="text/csv"
            )
        
        with col2:
            # Detaylı sevkiyat kaydı
            csv_detay = sevk_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Detaylı Sevkiyat Kaydı (CSV)",
                data=csv_detay,
                file_name="detaylı_sevkiyat_kaydı.csv",
                mime="text/csv"
            )
        
        with col3:
            # Depo stok durumu
            csv_depo = depo_stok_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Depo Stok Durumu (CSV)",
                data=csv_depo,
                file_name="depo_stok_durumu.csv",
                mime="text/csv"
            )
        
        # HTML rapor oluşturma
        def create_html_report(total_sevk, sevk_df, depo_stok_df):
            # Basit bir HTML rapor şablonu
            html_template = f"""
            <html>
            <head>
                <title>Sevkiyat Raporu</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .header {{ text-align: center; padding: 10px; background-color: #f0f0f0; }}
                    .summary {{ margin: 20px 0; }}
                    .metric {{ display: inline-block; margin: 10px; padding: 15px; background: #f9f9f9; border-radius: 5px; }}
                    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                    th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background-color: #4CAF50; color: white; }}
                    tr:hover {{ background-color: #f5f5f5; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Sevkiyat Planlama Raporu</h1>
                    <p>Oluşturulma Tarihi: {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}</p>
                </div>
                
                <div class="summary">
                    <h2>Özet Metrikler</h2>
                    <div class="metric">Toplam Sevk: <b>{total_sevk['sevk_miktar'].sum():,}</b></div>
                    <div class="metric">Mağaza Sayısı: <b>{total_sevk['magaza_id'].nunique()}</b></div>
                    <div class="metric">Ürün Çeşidi: <b>{total_sevk['urun_id'].nunique()}</b></div>
                    <div class="metric">Ortalama Cover: <b>{total_sevk['cover'].mean():.2f}</b></div>
                </div>
                
                <h2>Mağaza Bazlı Özet (İlk 10)</h2>
                {total_sevk.groupby('magaza_id')['sevk_miktar'].sum().head(10).to_frame().to_html()}
                
                <h2>Ürün Bazlı Özet (İlk 10)</h2>
                {total_sevk.groupby('urun_id')['sevk_miktar'].sum().head(10).to_frame().to_html()}
                
                <h2>Depo Stok Durumu</h2>
                {depo_stok_df[depo_stok_df['depo_stok'] > 0].to_html(index=False)}
            </body>
            </html>
            """
            
            return html_template

        # HTML indirme butonu
        html_report = create_html_report(total_sevk, sevk_df, depo_stok_df)
        st.download_button(
            label="📄 HTML Rapor İndir",
            data=html_report,
            file_name="sevkiyat_raporu.html",
            mime="text/html"
        )
        
        # -------------------------------
        # 5️⃣ Filtreleme ve Özelleştirme
        # -------------------------------
        st.markdown("---")
        st.header("🔍 Verileri Filtrele")
        
        # Mağaza ID'ye göre filtreleme
        magaza_listesi = sorted(total_sevk['magaza_id'].unique())
        selected_magaza = st.multiselect(
            "Mağaza ID'leri seçin:",
            options=magaza_listesi,
            default=magaza_listesi[:3] if len(magaza_listesi) > 3 else magaza_listesi
        )
        
        if selected_magaza:
            filtered_data = total_sevk[total_sevk['magaza_id'].isin(selected_magaza)]
            st.write(f"**Seçilen Mağazalar için Sevkiyat Özeti ({len(selected_magaza)} mağaza)**")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Toplam Sevkiyat", f"{filtered_data['sevk_miktar'].sum():,}")
            with col2:
                st.metric("Ortalama Cover", f"{filtered_data['cover'].mean():.2f}")
            with col3:
                st.metric("Ortalama Haftalık Satış", f"{filtered_data['haftalik_satis'].mean():.2f}")
            
            st.dataframe(filtered_data)
            
            # Filtrelenmiş veri için indirme butonu
            csv_filtered = filtered_data.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Filtrelenmiş Veriyi İndir",
                data=csv_filtered,
                file_name="filtrelenmiş_sevkiyat.csv",
                mime="text/csv"
            )