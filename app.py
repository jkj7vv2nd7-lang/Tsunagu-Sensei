import streamlit as st
import google.generativeai as genai
import csv
import io
import pandas as pd
from docx import Document
import re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ==========================================
# 1. ページ初期設定
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 校務支援・成績＆所見統合システム (V7.0)",
    page_icon="📝",
    layout="wide"
)

# ==========================================
# 2. セッション状態の初期化
# ==========================================
if "school_rules" not in st.session_state:
    st.session_state.school_rules = "・具体的なエピソードに基づき、成長のプロセスを評価する。\n・ポジティブな変化や意欲を中心に記述する。\n・専門用語は避け、保護者に分かりやすい表現にする。"

if "generated_findings" not in st.session_state:
    st.session_state.generated_findings = ""

if "proofread_result" not in st.session_state:
    st.session_state.proofread_result = ""

if "carte_result" not in st.session_state:
    st.session_state.carte_result = ""

# デモ用生徒・成績データの初期化
if "score_data" not in st.session_state:
    st.session_state.score_data = pd.DataFrame([
        {"出席番号": 1, "氏名": "相沢 拓海", "単元1_知識": "85", "単元2_知識": "90", "単元1_思考": "78", "単元2_思考": "82", "主体性": "A", "総合所見": "数学の方程式において自力で立式し、粘り強く解き進める姿勢が見られました。", "備考": ""},
        {"出席番号": 2, "氏名": "伊藤 葵", "単元1_知識": "欠", "単元2_知識": "88", "単元1_思考": "欠", "単元2_思考": "85", "主体性": "A", "総合所見": "グループワークで積極的に意見をまとめ、周囲を明るくリードしていました。", "備考": "単元1病欠"},
        {"出席番号": 3, "氏名": "上野 翔太", "単元1_知識": "62", "単元2_知識": "58", "単元1_思考": "55", "単元2_思考": "欠", "主体性": "B", "総合所見": "計算の見直しを丁寧に行うようになり、着実に着眼点が向上しています。", "備考": "単元2公欠"},
        {"出席番号": 4, "氏名": "遠藤 桜", "単元1_知識": "45", "単元2_知識": "50", "単元1_思考": "40", "単元2_思考": "42", "主体性": "C", "総合所見": "基礎的な問題に繰り返し取り組み、最後まで諦めずに努力を重ねました。", "備考": "要支援"},
    ])

# ==========================================
# 3. 匿名化ロジック
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

# ==========================================
# 4. Word / PDF 生成ヘルパー関数
# ==========================================
def replace_docx_tags(doc, data_dict):
    """Word文書内の {{タグ}} をデータに置き換える"""
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

def generate_simple_pdf(student_name, doc_type_name, finding_text):
    """簡易PDF生成処理"""
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    
    # 描画処理
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, 800, f"[{doc_type_name}] {student_name}")
    p.setLineWidth(1)
    p.line(50, 785, 550, 785)
    
    p.setFont("Helvetica", 10)
    p.drawString(50, 760, "Shoken / General Comments:")
    
    # テキストを折り返して描画（簡易）
    y = 730
    lines = [finding_text[i:i+40] for i in range(0, len(finding_text), 40)]
    for line in lines:
        p.drawString(50, y, line)
        y -= 20
        if y < 100:
            break
            
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

# ==========================================
# 5. APIキーの自動取得
# ==========================================
api_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

# ==========================================
# 6. サイドバー設定
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
        ending_instruction = "文末は必ず「〜でした。」「〜が見られました。」などの【敬体（です・ます調）】で統一してください。"
    elif doc_type == "指導要録用（である・した調）":
        ending_instruction = "文末は必ず「〜した。」「〜が見られた。」などの【常体（である・した調）】で統一してください。"
    else:
        ending_instruction = "文末は「〜ができる。」「〜に意欲的に取り組む。」などの【観点評価形式】で統一してください。"

    st.markdown("---")
    st.subheader("🏫 校内固有ルール & NG表現")
    st.session_state.school_rules = st.text_area(
        "遵守ルール・NG表現の追加:",
        value=st.session_state.school_rules,
        height=100
    )

# ==========================================
# 7. メイン画面（7タブ構成）
# ==========================================
st.title("📝 ツナグ先生 - 校務総合支援システム (V7.0)")
st.caption(f"現在のモード: **{doc_type}**")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "👤 所見作成 & 微調整", 
    "📁 CSVクラス一括生成", 
    "🔍 所見自動校正", 
    "💬 面談用カルテ", 
    "📊 成績蓄積 & 部会支援", 
    "🖨️ 様式出力 & テンプレート差し込み",
    "📄 印刷 & 校務連携"
])

# ------------------------------------------
# タブ1〜5: (既存の機能)
# ------------------------------------------
with tab1:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("1. 観察記録の入力")
        student_name = st.text_input("生徒名（省略可）", placeholder="例: 山田 太郎", key="t1_name")
        subject = st.selectbox("対象・分野", ["総合（通知表/要録）", "行動の記録", "数学", "国語", "理科", "社会", "英語", "特別活動・その他"])
        episodes = st.text_area("観察メモ・エピソード", placeholder="例: 数学 方程式で自力立式できた", height=160, key="t1_episodes")
        max_chars = st.number_input("希望文字数", min_value=50, max_value=500, value=150, step=10)
        generate_btn = st.button("✨ 所見文案を生成する", use_container_width=True, type="primary")

    with col2:
        st.subheader("2. 生成結果 & AIチャット微調整")
        if generate_btn:
            if not api_key:
                st.error("APIキーを入力してください。")
            elif not episodes:
                st.warning("エピソードを入力してください。")
            else:
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    masked_episodes, name_map = mask_pii(episodes, student_name)
                    prompt = f"ベテラン教員として所見を作成:\n分野:{subject}\nメモ:{masked_episodes}\n文字数:{max_chars}\nルール:{ending_instruction}\n{st.session_state.school_rules}\n本文のみ出力。"
                    with st.spinner("AIが作成中..."):
                        res = model.generate_content(prompt)
                        st.session_state.generated_findings = unmask_pii(res.text.strip(), name_map)
                except Exception as e:
                    st.error(f"エラー: {e}")

        if st.session_state.generated_findings:
            edited_text = st.text_area("現在の文案:", value=st.session_state.generated_findings, height=130)
            st.session_state.generated_findings = edited_text
            st.caption(f"文字数: {len(edited_text)}文字")

with tab2:
    st.subheader("CSVファイルからクラス全員分を一括生成")
    uploaded_file = st.file_uploader("CSVアップロード (名前, エピソード)", type=["csv"])
    if uploaded_file:
        content = uploaded_file.getvalue().decode("utf-8")
        rows = list(csv.reader(io.StringIO(content)))[1:]
        if st.button("🚀 全員分を一括生成する", type="primary"):
            if api_key:
                model = genai.GenerativeModel("gemini-2.5-flash")
                results = [["名前", "入力エピソード", "生成所見"]]
                for row in rows:
                    if len(row) >= 2:
                        name, ep = row[0], row[1]
                        prompt = f"所見作成: {ep}\nルール:{ending_instruction}\n{st.session_state.school_rules}"
                        res = model.generate_content(prompt)
                        results.append([name, ep, res.text.strip()])
                output = io.StringIO()
                csv.writer(output).writerows(results)
                st.download_button("📥 結果CSVダウンロード", data=output.getvalue().encode("utf-8-sig"), file_name="所見一括結果.csv")

with tab3:
    st.subheader("🔍 所見文章の自動校正")
    input_text_to_check = st.text_area("チェックする文章:", value=st.session_state.generated_findings, height=150)
    if st.button("🛡️ 校正する", type="primary"):
        if api_key and input_text_to_check:
            model = genai.GenerativeModel("gemini-2.5-flash")
            prompt = f"教頭として校正:\n文章:{input_text_to_check}\nルール:{ending_instruction}"
            res = model.generate_content(prompt)
            st.markdown(res.text)

with tab4:
    st.subheader("💬 面談用カルテ作成")
    c_name = st.text_input("生徒名", key="t4_cname")
    g_pts = st.text_area("成長点")
    c_pts = st.text_area("課題点")
    if st.button("📋 カルテ作成", type="primary"):
        if api_key and c_name:
            model = genai.GenerativeModel("gemini-2.5-flash")
            prompt = f"面談カルテ作成: 生徒:{c_name}, 成長:{g_pts}, 課題:{c_pts}"
            res = model.generate_content(prompt)
            st.markdown(res.text)

with tab5:
    st.subheader("📊 成績蓄積 & 部会支援")
    edited_df = st.data_editor(st.session_state.score_data, num_rows="dynamic", use_container_width=True)
    st.session_state.score_data = edited_df

# ------------------------------------------
# タブ6: 🖨️ 様式出力 & テンプレート差し込み (新機能!)
# ------------------------------------------
with tab6:
    st.subheader("🖨️ 学校独自様式（Word/Excel/PDF）への差し込み & 個別・一括出力")
    st.caption("学校で使っている通知表や指導要録のWordテンプレート（.docx）にデータを自動で埋め込んで出力します。")

    st.markdown("### 1. 出力対象・様式の選択")
    col_s1, col_s2 = st.columns([1, 1])
    with col_s1:
        target_doc = st.selectbox("出力書類の種類:", ["通知表（あゆみ）", "指導要録（様式2）", "個別の指導計画"])
    with col_s2:
        export_format = st.selectbox("出力フォーマット:", ["Word (.docx) テンプレート差し込み", "Excel (.xlsx) 一括データ出力", "簡易一括 PDF"])

    st.markdown("---")
    st.markdown("### 2. Wordテンプレートのアップロード（任意）")
    st.info("💡 **使い方:** Wordファイル内に `{{出席番号}}` `{{氏名}}` `{{総合所見}}` と書いた枠を用意しておくと、その場所が生徒ごとのデータに自動で置き換わります！")
    
    template_file = st.file_uploader("学校独自の Word テンプレート (.docx) をアップロード", type=["docx"])

    st.markdown("---")
    st.markdown("### 3. 出力実行 (個別 / クラス全員分)")

    df_current = st.session_state.score_data

    col_out1, col_out2 = st.columns([1, 1])

    # ① 個別出力
    with col_out1:
        st.markdown("#### 👤 特定の1人分を出力")
        selected_student = st.selectbox("対象の生徒を選択:", df_current["氏名"].tolist())
        student_row = df_current[df_current["氏名"] == selected_student].iloc[0].to_dict()

        if st.button("📄 この生徒の書類を生成する", type="primary"):
            if export_format.startswith("Word"):
                if template_file:
                    doc = Document(template_file)
                else:
                    # デモ用簡易Docx生成
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
            elif export_format.startswith("簡易"):
                pdf_buf = generate_simple_pdf(student_row['氏名'], target_doc, str(student_row.get('総合所見', '')))
                st.download_button(
                    label=f"📥 {selected_student}さんのPDFをダウンロード",
                    data=pdf_buf.getvalue(),
                    file_name=f"{target_doc}_{selected_student}.pdf",
                    mime="application/pdf"
                )

    # ② 全員分一括出力
    with col_out2:
        st.markdown("#### 📁 クラス全員分を一括出力")
        if st.button("🚀 クラス全員分をまとめて生成・ダウンロード"):
            if export_format.startswith("Excel"):
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                    df_current.to_excel(writer, index=False, sheet_name='一括データ')
                st.download_button(
                    label="📥 全員分データ (Excel) をダウンロード",
                    data=excel_buffer.getvalue(),
                    file_name=f"{target_doc}_全員一括.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.success("全員分のWord/PDFを準備しました。個別出力をご利用いただくか、Zip一括出力が可能です。")

# ------------------------------------------
# タブ7: 印刷 & 校務連携
# ------------------------------------------
with tab7:
    st.subheader("🖨️ 印刷プレビュー ＆ 校務システム用コピペ")
    if st.session_state.generated_findings:
        st.code(st.session_state.generated_findings, language=None)
        print_html = f"""
        <div style="border: 2px solid #333; padding: 20px; border-radius: 8px; background-color: #fff;">
            <h3>所見確認シート ({doc_type})</h3>
            <p style="font-size: 15px; line-height: 1.8;">{st.session_state.generated_findings}</p>
        </div>
        """
        st.components.v1.html(print_html, height=220, scrolling=True)
    else:
        st.info("※「所見作成」タブで所見を生成すると、ここにコピー用テキストと印刷枠が表示されます。")