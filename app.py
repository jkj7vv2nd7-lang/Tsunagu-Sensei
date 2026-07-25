import streamlit as st
import google.generativeai as genai
import csv
import io
import pandas as pd
import re
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ==========================================
# 1. ページ初期設定 & カスタムCSS（タブ2段折り返し対応）
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 校務総合支援システム (V8.2)",
    page_icon="📝",
    layout="wide"
)

# タブをモニター横幅に合わせて2段（折り返し）にするカスタムCSS
st.markdown("""
    <style>
    div[data-baseweb="tab-list"] {
        flex-wrap: wrap !important;
        gap: 6px 8px !important;
    }
    button[data-baseweb="tab"] {
        height: auto !important;
        padding: 8px 16px !important;
        border-radius: 8px !important;
        background-color: #f0f2f6;
        margin-bottom: 4px !important;
        font-weight: bold !important;
    }
    button[aria-selected="true"] {
        background-color: #1f77b4 !important;
        color: white !important;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. セッション状態の初期化
# ==========================================
if "school_rules" not in st.session_state:
    st.session_state.school_rules = "・具体的なエピソードに基づき、成長のプロセスを評価する。\n・ポジティブな変化や意欲を中心に記述する。\n・専門用語は避け、保護者に分かりやすい表現にする。"

if "generated_findings" not in st.session_state:
    st.session_state.generated_findings = ""

# 複数学年・複数クラスのデモデータ構造
if "multi_class_data" not in st.session_state:
    st.session_state.multi_class_data = {
        "2年1組": pd.DataFrame([
            {"出席番号": 1, "氏名": "相沢 拓海", "単元1_知識": "85", "単元2_知識": "90", "単元1_思考": "78", "単元2_思考": "82", "主体性": "A", "総合所見": "数学の方程式において自力で立式し、粘り強く解き進める姿勢が見られました。"},
            {"出席番号": 2, "氏名": "伊藤 葵", "単元1_知識": "欠", "単元2_知識": "88", "単元1_思考": "欠", "単元2_思考": "85", "主体性": "A", "総合所見": "グループワークで積極的に意見をまとめ、周囲を明るくリードしていました。"},
        ]),
        "2年2組": pd.DataFrame([
            {"出席番号": 1, "氏名": "加藤 健太", "単元1_知識": "70", "単元2_知識": "75", "単元1_思考": "68", "単元2_思考": "72", "主体性": "B", "総合所見": "授業中の集中力が高く、課題に対して粘り強く取り組むことができています。"},
            {"出席番号": 2, "氏名": "木村 結衣", "単元1_知識": "95", "単元2_知識": "92", "単元1_思考": "90", "単元2_思考": "94", "主体性": "A", "総合所見": "発展的な問題にも進んで挑戦し、クラスの学習意欲を高めてくれました。"},
        ])
    }

# 学期推移用データ
if "term_data" not in st.session_state:
    st.session_state.term_data = pd.DataFrame([
        {"出席番号": 1, "氏名": "相沢 拓海", "1学期_評定": 3, "2学期_評定": 4, "3学期_評定": 4, "推移": "上昇傾向"},
        {"出席番号": 2, "氏名": "伊藤 葵", "1学期_評定": 5, "2学期_評定": 4, "3学期_評定": 3, "推移": "要フォロー"},
        {"出席番号": 3, "氏名": "上野 翔太", "1学期_評定": 2, "2学期_評定": 2, "3学期_評定": 3, "推移": "改善傾向"},
    ])

# ==========================================
# 3. ヘルパー関数 & 列名自動標準化ロジック
# ==========================================
def mask_pii(text, student_name=""):
    masked_text = text
    name_map = {}
    if student_name and student_name.strip():
        masked_text = masked_text.replace(student_name.strip(), "[生徒名]")
        name_map["[生徒名]"] = student_name.strip()
    return masked_text, name_map

def unmask_pii(text, name_map):
    unmasked_text = text
    for placeholder, original_name in name_map.items():
        unmasked_text = unmasked_text.replace(placeholder, original_name)
    return unmasked_text

def replace_docx_tags(doc, data_dict):
    for p in doc.paragraphs:
        for key, value in data_dict.items():
            tag = f"{{{{{key}}}}}"
            if tag in p.text:
                p.text = p.text.replace(tag, str(value))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for key, value in data_dict.items():
                        tag = f"{{{{{key}}}}}"
                        if tag in p.text:
                            p.text = p.text.replace(tag, str(value))
    return doc

def normalize_column_name(col_name, file_label=""):
    """
    教科ごとにばらつく列名を自動解析し、標準キーワードに統合するロジック
    """
    c = col_name.strip()
    
    # 基本キーの標準化
    if re.search(r"番号|出席番号|No", c, re.IGNORECASE):
        return "出席番号"
    if re.search(r"氏名|名前|生徒名", c):
        return "氏名"
        
    # 教科名の判定（ファイル名または列名から抽出）
    subjects = ["国語", "社会", "数学", "理科", "英語", "音楽", "美術", "保体", "保健体育", "技術", "家庭", "技家"]
    found_subject = ""
    for s in subjects:
        if s in c or s in file_label:
            found_subject = s
            break
            
    if not found_subject:
        found_subject = "教科"

    # 評価・観点キーワードの検知
    if re.search(r"評定|5段階|成績|評価$", c):
        return f"{found_subject}_評定"
    elif re.search(r"知識|技能|観点1|観点A", c):
        return f"{found_subject}_観点_知識技能"
    elif re.search(r"思考|判断|表現|観点2|観点B", c):
        return f"{found_subject}_観点_思考判断"
    elif re.search(r"主体|態度|意欲|観点3|観点C", c):
        return f"{found_subject}_観点_主体性"
    elif re.search(r"所見|文章|備考", c):
        return f"{found_subject}_所見"
    
    return f"{found_subject}_{c}"

# APIキー設定
api_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

# ==========================================
# 4. サイドバー設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 全体設定")
    if not api_key:
        api_key = st.text_input("Gemini API Key", type="password")
    else:
        st.success("🔑 APIキー連携完了（Secrets）")
        
    if api_key:
        genai.configure(api_key=api_key)

    st.markdown("---")
    st.subheader("📋 文書・文末ルールの選択")
    doc_type = st.radio(
        "基本文末モード:",
        ["通知表用（です・ます調）", "指導要録用（である・した調）", "観点記述型（〜ができる/〜に努める）"],
        index=0
    )

    if doc_type == "通知表用（です・ます調）":
        ending_instruction = "文末は「〜でした。」「〜が見られました。」などの【敬体（です・ます調）】で統一。"
    elif doc_type == "指導要録用（である・した調）":
        ending_instruction = "文末は「〜した。」「〜が見られた。」などの【常体（である・した調）】で統一。"
    else:
        ending_instruction = "文末は「〜ができる。」「〜に意欲的に取り組む。」などの【観点評価形式】で統一。"

# ==========================================
# 5. メイン画面（8タブ構成）
# ==========================================
st.title("📝 ツナグ先生 - 校務総合支援システム (V8.2)")
st.caption(f"現在のモード: **{doc_type}** | 画面幅に合わせてタブが2段に折り返されます")

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "👤 所見作成(音声&リスク判定)", 
    "📁 CSVクラス一括生成", 
    "🔍 所見自動校正", 
    "💬 面談用カルテ", 
    "📊 学年・クラス別 成績＆部会", 
    "📈 学期推移ダッシュボード",
    "🔄 担任用 全教科成績集約",
    "🖨️ 様式出力 & テンプレート"
])

# ------------------------------------------
# タブ1: 👤 所見作成
# ------------------------------------------
with tab1:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("1. 観察記録の入力")
        st.markdown("**🎤 音声入力メモ（タップして話す）**")
        speech_html = """
        <script>
        function startDictation() {
            if (window.hasOwnProperty('webkitSpeechRecognition')) {
                var recognition = new webkitSpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = "ja-JP";
                recognition.start();
                recognition.onresult = function(e) {
                    document.getElementById('transcript').value = e.results[0][0].transcript;
                    recognition.stop();
                };
                recognition.onerror = function(e) { recognition.stop(); }
            } else {
                alert("お使いのブラウザは音声認識に対応していません（Google Chrome推奨）。");
            }
        }
        </script>
        <div style="margin-bottom: 10px;">
            <button onclick="startDictation()" style="background-color: #28a745; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold;">
                🎤 音声入力を開始
            </button>
            <br/><br/>
            <textarea id="transcript" rows="2" style="width: 100%; border: 1px solid #ccc; border-radius: 6px; padding: 6px;" placeholder="音声認識結果がここに表示されます。"></textarea>
        </div>
        """
        st.components.v1.html(speech_html, height=140)

        student_name = st.text_input("生徒名（省略可）", placeholder="例: 山田 太郎", key="t1_name")
        subject = st.selectbox("対象・分野", ["総合（通知表/要録）", "行動の記録", "数学", "国語", "理科", "社会", "英語", "特別活動・その他"])
        episodes = st.text_area("観察メモ・エピソード", placeholder="例: 数学 方程式で自力立式できた", height=130, key="t1_episodes")
        max_chars = st.number_input("希望文字数", min_value=50, max_value=500, value=150, step=10)
        
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            generate_btn = st.button("✨ 所見文案を生成する", use_container_width=True, type="primary")
        with col_btn2:
            risk_check_btn = st.button("🛡️ 保護者目線リスク判定", use_container_width=True)

    with col2:
        st.subheader("2. 生成結果 & AI判定")
        if generate_btn:
            if api_key and episodes:
                model = genai.GenerativeModel("gemini-2.5-flash")
                masked_episodes, name_map = mask_pii(episodes, student_name)
                prompt = f"ベテラン教員として所見を作成:\n分野:{subject}\nメモ:{masked_episodes}\n文字数:{max_chars}\nルール:{ending_instruction}\n{st.session_state.school_rules}\n本文のみ出力。"
                with st.spinner("AIが作成中..."):
                    res = model.generate_content(prompt)
                    st.session_state.generated_findings = unmask_pii(res.text.strip(), name_map)

        if st.session_state.generated_findings:
            edited_text = st.text_area("現在の文案:", value=st.session_state.generated_findings, height=130)
            st.session_state.generated_findings = edited_text

        if risk_check_btn and api_key and st.session_state.generated_findings:
            model = genai.GenerativeModel("gemini-2.5-flash")
            risk_prompt = f"文章を保護者目線で検証:\n{st.session_state.generated_findings}\n1.リスク判定 2.懸念点 3.温かい改善案を出力。"
            with st.spinner("保護者目線でリスクチェック中..."):
                risk_res = model.generate_content(risk_prompt)
                st.warning("🛡️ 保護者目線リスク判定結果:")
                st.markdown(risk_res.text)

# ------------------------------------------
# タブ2〜4: (CSV一括生成・自動校正・カルテ)
# ------------------------------------------
with tab2:
    st.subheader("CSVファイルからクラス全員分を一括生成")
    uploaded_file = st.file_uploader("CSVアップロード (名前, エピソード)", type=["csv"])
    if uploaded_file and st.button("🚀 全員分を一括生成する", type="primary"):
        if api_key:
            content = uploaded_file.getvalue().decode("utf-8")
            rows = list(csv.reader(io.StringIO(content)))[1:]
            model = genai.GenerativeModel("gemini-2.5-flash")
            results = [["名前", "入力エピソード", "生成所見"]]
            for row in rows:
                if len(row) >= 2:
                    res = model.generate_content(f"所見作成: {row[1]}\nルール:{ending_instruction}")
                    results.append([row[0], row[1], res.text.strip()])
            output = io.StringIO()
            csv.writer(output).writerows(results)
            st.download_button("📥 結果CSVダウンロード", data=output.getvalue().encode("utf-8-sig"), file_name="所見一括結果.csv")

with tab3:
    st.subheader("🔍 所見文章の自動校正")
    input_text_to_check = st.text_area("チェックする文章:", value=st.session_state.generated_findings, height=150)
    if st.button("🛡️ 校正する", type="primary") and api_key and input_text_to_check:
        model = genai.GenerativeModel("gemini-2.5-flash")
        res = model.generate_content(f"教頭として校正:\n文章:{input_text_to_check}\nルール:{ending_instruction}")
        st.markdown(res.text)

with tab4:
    st.subheader("💬 面談用カルテ作成")
    c_name = st.text_input("生徒名", key="t4_cname")
    g_pts = st.text_area("成長点")
    c_pts = st.text_area("課題点")
    if st.button("📋 カルテ作成", type="primary") and api_key and c_name:
        model = genai.GenerativeModel("gemini-2.5-flash")
        res = model.generate_content(f"面談カルテ作成: 生徒:{c_name}, 成長:{g_pts}, 課題:{c_pts}")
        st.markdown(res.text)

# ------------------------------------------
# タブ5: 📊 学年・クラス別 成績＆部会
# ------------------------------------------
with tab5:
    st.subheader("📊 学年・クラス別 成績管理 ＆ 教科部会資料作成")
    selected_class = st.selectbox("🏫 担当クラスを選択:", list(st.session_state.multi_class_data.keys()))
    df_class = st.session_state.multi_class_data[selected_class]

    st.markdown(f"### {selected_class} 成績データの入力・編集")
    edited_df = st.data_editor(df_class, num_rows="dynamic", use_container_width=True, key=f"editor_{selected_class}")
    st.session_state.multi_class_data[selected_class] = edited_df

    st.markdown("---")
    st.markdown("### 📤 教科部会用 全クラス統合Excel出力")
    if st.button("📊 全クラスの成績シートをまとめたExcelを出力"):
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            for cls_name, cls_df in st.session_state.multi_class_data.items():
                cls_df.to_excel(writer, index=False, sheet_name=cls_name)
        st.download_button(
            label="📥 全クラス統合Excel (.xlsx) をダウンロード",
            data=excel_buffer.getvalue(),
            file_name="教科部会_全クラス成績一覧.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ------------------------------------------
# タブ6: 📈 学期推移ダッシュボード
# ------------------------------------------
with tab6:
    st.subheader("📈 学期推移ダッシュボード")
    st.dataframe(st.session_state.term_data, use_container_width=True)
    st.markdown("#### 📊 クラス全体の評定推移")
    chart_df = st.session_state.term_data.set_index("氏名")[["1学期_評定", "2学期_評定", "3学期_評定"]].T
    st.line_chart(chart_df)

    st.markdown("#### ⚠️ 要フォロー生徒")
    follow_df = st.session_state.term_data[st.session_state.term_data["推移"] == "要フォロー"]
    if not follow_df.empty:
        st.warning(f"以下の {len(follow_df)} 名の生徒が下降傾向にあります。")
        st.table(follow_df[["出席番号", "氏名", "1学期_評定", "3学期_評定", "推移"]])

# ------------------------------------------
# タブ7: 🔄 担任用 全教科成績集約 (スマート列名自動マッチング対応!)
# ------------------------------------------
with tab7:
    st.subheader("🔄 担任用 全教科成績の自動集計・列名スマート統一")
    st.caption("教科ごとに異なる表記（「国語評価」「数学_観点1」など）をスマートに統一し、通知表差し込み印刷用の『1人1行マスター』を作成します。")

    uploaded_subject_files = st.file_uploader(
        "各教科の成績ファイル (CSV/Excel) を複数まとめてアップロード", 
        type=["csv", "xlsx"], 
        accept_multiple_files=True
    )

    if uploaded_subject_files:
        st.markdown("### 🔍 各教科ファイルの列名自動判定プレビュー")
        
        normalized_dfs = []
        for file in uploaded_subject_files:
            if file.name.endswith('.csv'):
                df_sub = pd.read_csv(file)
            else:
                df_sub = pd.read_excel(file)
            
            # 列名の標準化処理
            new_cols = {col: normalize_column_name(col, file.name) for col in df_sub.columns}
            df_sub_norm = df_sub.rename(columns=new_cols)
            normalized_dfs.append((file.name, df_sub_norm, new_cols))

            with st.expander(f"📄 {file.name} の列名マッピング結果"):
                mapping_df = pd.DataFrame([{"元の列名": k, "統一後の列名": v} for k, v in new_cols.items()])
                st.table(mapping_df)

        if st.button("🔗 上記の列名で全教科データを1人に名寄せ合体する", type="primary"):
            merged_df = None
            for fname, df_sub_norm, _ in normalized_dfs:
                if merged_df is None:
                    merged_df = df_sub_norm
                else:
                    # 出席番号または氏名でマージ
                    join_keys = [k for k in ["出席番号", "氏名"] if k in merged_df.columns and k in df_sub_norm.columns]
                    if not join_keys:
                        join_keys = ["氏名"] if "氏名" in merged_df.columns else ["出席番号"]
                    
                    merged_df = pd.merge(merged_df, df_sub_norm, on=join_keys, how="outer")

            st.success("🎉 列名の揺れを補正し、全教科のマスターシートを作成しました！")
            st.dataframe(merged_df, use_container_width=True)

            # Excelダウンロード
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
                merged_df.to_excel(writer, index=False, sheet_name='通知表差し込み用マスター')
            st.download_button(
                label="📥 差し込み印刷用 統合マスターシート (.xlsx) をダウンロード",
                data=excel_buf.getvalue(),
                file_name="学級担任用_全教科統合マスター_標準化済.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ------------------------------------------
# タブ8: 🖨️ 様式出力 & テンプレート
# ------------------------------------------
with tab8:
    st.subheader("🖨️ 学校独自様式（Word/Excel/PDF）への差し込み & 個別・一括出力")
    target_doc = st.selectbox("出力書類:", ["通知表（あゆみ）", "指導要録（様式2）", "個別の指導計画"])
    template_file = st.file_uploader("Word テンプレート (.docx) をアップロード", type=["docx"])

    df_current = list(st.session_state.multi_class_data.values())[0]

    selected_student = st.selectbox("対象の生徒を選択:", df_current["氏名"].tolist())
    student_row = df_current[df_current["氏名"] == selected_student].iloc[0].to_dict()

    if st.button("📄 この生徒の書類を生成する (Word)", type="primary"):
        if template_file:
            doc = Document(template_file)
        else:
            doc = Document()
            doc.add_heading(f"{target_doc} - {student_row['氏名']} 様", 0)
            doc.add_paragraph(f"出席番号: {student_row['出席番号']}")
            doc.add_paragraph(f"総合所見:\n{student_row.get('総合所見', '（未入力）')}")
        
        filled_doc = replace_docx_tags(doc, student_row)
        out_buffer = io.BytesIO()
        filled_doc.save(out_buffer)
        out_buffer.seek(0)
        
        st.download_button(
            label=f"📥 {selected_student}さんのWordをダウンロード",
            data=out_buffer.getvalue(),
            file_name=f"{target_doc}_{selected_student}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )