import streamlit as st
import google.generativeai as genai
import csv
import io
import pandas as pd
import re

# ==========================================
# 1. ページ設定 & カスタムCSS
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 統合校務支援システム (V9.0)",
    page_icon="🏫",
    layout="wide"
)

st.markdown("""
    <style>
    div[data-baseweb="tab-list"] { flex-wrap: wrap !important; gap: 4px 6px !important; }
    button[data-baseweb="tab"] { height: auto !important; padding: 6px 12px !important; border-radius: 6px !important; background-color: #f0f2f6; font-weight: bold !important; }
    button[aria-selected="true"] { background-color: #1f77b4 !important; color: white !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. データベース（セッション状態）の初期化
# ==========================================

# 日々の観察メモ蓄積DB
if "daily_logs" not in st.session_state:
    st.session_state.daily_logs = pd.DataFrame([
        {"日付": "2026-05-10", "クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "対象分野": "数学", "観察メモ": "方程式の文章題で自力で立式し、解き進めることができた。"},
        {"日付": "2026-06-15", "クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "対象分野": "総合・行動", "観察メモ": "班長としてグループの話し合いを主体的にまとめ、発表を担当した。"},
        {"日付": "2026-05-12", "クラス": "2年1組", "出席番号": 2, "氏名": "伊藤 葵", "対象分野": "英語", "観察メモ": "単語テストで満点を取り、ペアワークでも積極的に発音の練習を行っていた。"},
    ])

# 担当教科成績データ（全クラス一括管理）
if "subject_scores" not in st.session_state:
    st.session_state.subject_scores = pd.DataFrame([
        {"クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "観点1_知識": 85, "観点2_思考": 78, "観点3_主体性": 90},
        {"クラス": "2年1組", "出席番号": 2, "氏名": "伊藤 葵", "観点1_知識": 92, "観点2_思考": 88, "観点3_主体性": 95},
        {"クラス": "2年2組", "出席番号": 1, "氏名": "加藤 健太", "観点1_知識": 70, "観点2_思考": 65, "観点3_主体性": 75},
        {"クラス": "2年2組", "出席番号": 2, "氏名": "木村 結衣", "観点1_知識": 95, "観点2_思考": 92, "観点3_主体性": 90},
    ])

# APIキー設定
api_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

with st.sidebar:
    st.header("⚙️ システム設定")
    if not api_key:
        api_key = st.text_input("Gemini API Key", type="password")
    else:
        st.success("🔑 Gemini API連携中")
    if api_key:
        genai.configure(api_key=api_key)
        
    doc_type = st.radio("文末モード:", ["です・ます調（通知表）", "である・した調（要録）"])
    ending_rule = "文末は「です・ます」調で統一。" if "です" in doc_type else "文末は「である・した」調で統一。"

# 列名自動正規化関数
def normalize_col(col, file_name=""):
    c = str(col).strip()
    if re.search(r"番号|No", c): return "出席番号"
    if re.search(r"氏名|名前", c): return "氏名"
    
    subj = "教科"
    for s in ["国語", "社会", "数学", "理科", "英語", "音楽", "美術", "保体", "技術", "家庭"]:
        if s in c or s in file_name:
            subj = s; break
            
    if "評定" in c or "評価" in c: return f"{subj}_評定"
    if "知識" in c: return f"{subj}_観点_知識"
    if "思考" in c: return f"{subj}_観点_思考"
    if "主体" in c: return f"{subj}_観点_主体性"
    if "所見" in c: return f"{subj}_所見"
    return f"{subj}_{c}"

# ==========================================
# 3. メイン画面（タブ構成）
# ==========================================
st.title("🏫 ツナグ先生 - 学務一体型校務支援システム (V9.0)")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📝 ① 日々メモ蓄積 & 所見生成",
    "📁 ② CSV一括生成・連携",
    "🔍 ③ 所見データ自動校正",
    "💬 ④ 蓄積データ自動連携カルテ",
    "📊 ⑤ 授業担当用 全クラス成績&評定算出",
    "📈 ⑥ 担任用 学期推移ダッシュボード",
    "🔄 ⑦ 担任用 全教科成績集約"
])

# ------------------------------------------
# タブ1: ① 日々メモ蓄積 & 所見生成
# ------------------------------------------
with tab1:
    col_a, col_b = st.columns([1, 1.2])
    
    with col_a:
        st.subheader("📌 1. 日々の観察メモを蓄積・登録")
        with st.form("add_log_form", clear_on_submit=True):
            f_date = st.date_input("日付")
            f_class = st.selectbox("クラス", ["2年1組", "2年2組"])
            f_name = st.text_input("生徒氏名（例: 相沢 拓海）")
            f_cat = st.selectbox("対象分野", ["総合・行動の記録", "数学", "国語", "英語", "理科", "社会", "特別活動"])
            f_memo = st.text_area("観察メモ（音声入力可）", placeholder="例: 授業中に手を挙げて自力で答える姿が見られた。")
            submitted = st.form_submit_button("📥 データベースに保存")
            
            if submitted and f_name and f_memo:
                new_row = pd.DataFrame([{"日付": str(f_date), "クラス": f_class, "出席番号": 1, "氏名": f_name, "対象分野": f_cat, "観察メモ": f_memo}])
                st.session_state.daily_logs = pd.concat([st.session_state.daily_logs, new_row], ignore_index=True)
                st.success(f"{f_name} さんのメモを蓄積しました！")

    with col_b:
        st.subheader("✨ 2. 蓄積メモから所見自動生成")
        selected_student = st.selectbox("所見を作成する生徒を選択:", st.session_state.daily_logs["氏名"].unique())
        
        # 該当生徒の蓄積メモを自動抽出
        student_memos = st.session_state.daily_logs[st.session_state.daily_logs["氏名"] == selected_student]
        st.write("📜 **これまでに蓄積された観察記録:**")
        st.dataframe(student_memos[["日付", "対象分野", "観察メモ"]], use_container_width=True)
        
        if st.button("🪄 蓄積メモから所見文案を一括合成・生成", type="primary"):
            if api_key and not student_memos.empty:
                combined_memos = "\n".join(student_memos["観察メモ"].tolist())
                prompt = f"生徒『{selected_student}』の蓄積メモ:\n{combined_memos}\n\n上記メモをもとに通知表・要録用の所見文案を作成してください。{ending_rule}"
                model = genai.GenerativeModel("gemini-2.5-flash")
                with st.spinner("AIが過去の記録を合体して所見を生成中..."):
                    res = model.generate_content(prompt)
                    st.text_area("生成された所見文案:", value=res.text.strip(), height=150)

# ------------------------------------------
# タブ2: ② CSV一括生成
# ------------------------------------------
with tab2:
    st.subheader("📁 蓄積データをもとにクラス全員の所見を一括生成")
    target_cls = st.selectbox("一括生成対象クラス:", ["2年1組", "2年2組"])
    
    if st.button("🚀 クラス全員の蓄積メモからCSVを一括生成"):
        cls_memos = st.session_state.daily_logs[st.session_state.daily_logs["クラス"] == target_cls]
        results = []
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        for name, group in cls_memos.groupby("氏名"):
            all_memos = " / ".join(group["観察メモ"].tolist())
            if api_key:
                res = model.generate_content(f"生徒:{name} メモ:{all_memos} の所見を作成。{ending_rule}")
                results.append({"氏名": name, "まとめメモ": all_memos, "生成所見": res.text.strip()})
            else:
                results.append({"氏名": name, "まとめメモ": all_memos, "生成所見": "APIキー未設定"})
                
        res_df = pd.DataFrame(results)
        st.dataframe(res_df, use_container_width=True)
        
        csv_data = res_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 クラス全員の所見一括CSVをダウンロード", csv_data, f"{target_cls}_一括所見.csv", "text/csv")

# ------------------------------------------
# タブ3: ③ 所見自動校正
# ------------------------------------------
with tab3:
    st.subheader("🔍 所見データの自動校正 & 直接編集")
    check_source = st.radio("校正対象の指定方法:", ["蓄積データから選択", "直接テキスト入力"])
    
    if check_source == "蓄積データから選択":
        student_for_check = st.selectbox("校正する生徒を選択:", st.session_state.daily_logs["氏名"].unique(), key="chk_st")
        sample_text = " ".join(st.session_state.daily_logs[st.session_state.daily_logs["氏名"] == student_for_check]["観察メモ"].tolist())
    else:
        sample_text = st.text_area("校正する文章を入力:", height=100)
        
    if st.button("🛡️ 校正・不適切表現チェック実行", type="primary") and api_key and sample_text:
        model = genai.GenerativeModel("gemini-2.5-flash")
        res = model.generate_content(f"誤字脱字チェックおよび保護者目線での適切な文章校正:\n{sample_text}\n{ending_rule}")
        st.markdown(res.text)

# ------------------------------------------
# タブ4: ④ 面談用自動連携カルテ
# ------------------------------------------
with tab4:
    st.subheader("💬 面談用カルテ（蓄積メモ＆成績から自動生成）")
    kart_student = st.selectbox("面談対象の生徒を選択:", st.session_state.daily_logs["氏名"].unique(), key="kart_st")
    
    # 生徒のメモと成績を横断抽出
    st_memos = st.session_state.daily_logs[st.session_state.daily_logs["氏名"] == kart_student]
    st_scores = st.session_state.subject_scores[st.session_state.subject_scores["氏名"] == kart_student]
    
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        st.markdown("### 📜 観察エピソード")
        st.table(st_memos[["日付", "対象分野", "観察メモ"]])
    with col_k2:
        st.markdown("### 📊 教科観点データ")
        st.table(st_scores)
        
    if st.button("📋 面談用トークポイント・カルテをAI自動生成", type="primary") and api_key:
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"生徒『{kart_student}』の観察記録:\n{st_memos['観察メモ'].str.cat(sep=' ')}\n面談で保護者に伝える【1.成長点 2.今後の課題 3.家庭での連携アドバイス】をまとめて作成。"
        res = model.generate_content(prompt)
        st.info("💡 面談カルテ出力結果:")
        st.markdown(res.text)

# ------------------------------------------
# タブ5: ⑤ 全クラス成績 & 評定自動算出
# ------------------------------------------
with tab5:
    st.subheader("📊 授業担当用 全クラス成績入力 & 評定自動計算")
    st.caption("授業担当するすべてのクラスを一覧表示・一括編集できます。観点点数から5段階評定を自動計算します。")
    
    # 担当全クラス一覧データ編集
    edited_scores = st.data_editor(
        st.session_state.subject_scores, 
        num_rows="dynamic", 
        use_container_width=True,
        key="score_editor"
    )
    st.session_state.subject_scores = edited_scores
    
    if st.button("⚡ 観点から5段階評定を自動計算して付与"):
        def calc_grade(row):
            avg = (row["観点1_知識"] + row["観点2_思考"] + row["観点3_主体性"]) / 3
            if avg >= 85: return 5
            elif avg >= 70: return 4
            elif avg >= 55: return 3
            elif avg >= 40: return 2
            else: return 1
            
        edited_scores["算定評定"] = edited_scores.apply(calc_grade, axis=1)
        st.session_state.subject_scores = edited_scores
        st.success("🎉 全クラスの観点平均から5段階評定を自動計算しました！")
        st.dataframe(edited_scores, use_container_width=True)

# ------------------------------------------
# タブ6: ⑥ 学期推移ダッシュボード
# ------------------------------------------
with tab6:
    st.subheader("📈 担任用 学期推移ダッシュボード")
    dash_cls = st.selectbox("表示クラス:", ["2年1組", "2年2組"], key="dash_cls")
    
    # デモ推移データ
    trend_df = pd.DataFrame([
        {"氏名": "相沢 拓海", "1学期": 3, "2学期": 4, "3学期": 4, "状態": "上昇傾向"},
        {"氏名": "伊藤 葵", "1学期": 5, "2学期": 4, "3学期": 3, "状態": "要フォロー"},
    ])
    st.dataframe(trend_df, use_container_width=True)
    st.line_chart(trend_df.set_index("氏名")[["1学期", "2学期", "3学期"]].T)

# ------------------------------------------
# タブ7: ⑦ 全教科成績集約（名寄せ）
# ------------------------------------------
with tab7:
    st.subheader("🔄 各教科のバラバラな成績ファイルを1人1行に自動合体")
    st.caption("教科担当の先生から集めたCSV/Excelファイルをまとめてアップロードするだけで、列名を統一して担任用マスターを作成します。")
    
    up_files = st.file_uploader("各教科の成績ファイルをまとめてドロップ", type=["csv", "xlsx"], accept_multiple_files=True)
    
    if up_files and st.button("🔗 全教科データを名寄せ・自動統合"):
        merged = None
        for f in up_files:
            df = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
            df = df.rename(columns={c: normalize_col(c, f.name) for c in df.columns})
            
            if merged is None:
                merged = df
            else:
                keys = [k for k in ["出席番号", "氏名"] if k in merged.columns and k in df.columns]
                merged = pd.merge(merged, df, on=keys if keys else ["氏名"], how="outer")
                
        st.success("🎉 全教科の列名をスマート合体しました！")
        st.dataframe(merged, use_container_width=True)