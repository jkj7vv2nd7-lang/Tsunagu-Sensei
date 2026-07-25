import streamlit as st
import google.generativeai as genai
import csv
import io

# ==========================================
# 1. ページ初期設定
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 所見自動生成・編集システム (V4.0)",
    page_icon="📝",
    layout="wide"
)

# ==========================================
# 2. セッション状態の初期化
# ==========================================
if "school_rules" not in st.session_state:
    st.session_state.school_rules = "・具体的なエピソードに基づき、成長のプロセスを評価する。\n・ポジティブな変化や意欲を中心に記述する。\n・専門用語は避け、保護者に分かりやすい表現にする。"

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "generated_findings" not in st.session_state:
    st.session_state.generated_findings = ""

# ==========================================
# 3. セキュリティ：ローカル完全匿名化ロジック
# ==========================================
def mask_pii(text, student_name=""):
    """送信前に個人情報をダミーに置き換える"""
    masked_text = text
    name_map = {}
    
    if student_name and student_name.strip():
        masked_text = masked_text.replace(student_name.strip(), "[生徒名]")
        name_map["[生徒名]"] = student_name.strip()
    
    return masked_text, name_map

def unmask_pii(text, name_map):
    """受信後にダミーを元の名前に復元する"""
    unmasked_text = text
    for placeholder, original_name in name_map.items():
        unmasked_text = unmasked_text.replace(placeholder, original_name)
    return unmasked_text

# ==========================================
# 4. APIキーの自動取得 (エラー安全処理)
# ==========================================
api_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    # ローカル環境等で secrets.toml が存在しない場合はエラーを出さずにパス
    pass

# ==========================================
# 5. サイドバー設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 全体設定")
    
    # Secretsになければ画面から手入力
    if not api_key:
        api_key = st.text_input("Gemini API Key", type="password", help="APIキーを入力してください")
    else:
        st.success("🔑 APIキー連携完了（Secrets）")
        
    if api_key:
        genai.configure(api_key=api_key)

    st.markdown("---")
    st.subheader("📋 用途・文末ルールの選択")
    
    doc_type = st.radio(
        "作成する文書の種類を選んでください:",
        ["通知表用（です・ます調）", "指導要録用（である・した調）", "観点記述型（〜ができる/〜に努める）"],
        index=0
    )

    if doc_type == "通知表用（です・ます調）":
        ending_instruction = "文末は必ず「〜でした。」「〜が見られました。」「〜に取り組んでいます。」などの【敬体（です・ます調）】で統一してください。"
    elif doc_type == "指導要録用（である・した調）":
        ending_instruction = "文末は必ず「〜した。」「〜が見られた。」「〜についての理解を深めた。」などの【常体（である・した調/断定調）】で統一してください。"
    else:
        ending_instruction = "文末は「〜ができる。」「〜を理解している。」「〜に意欲的に取り組む。」などの【観点評価形式】で統一してください。"

    st.markdown("---")
    st.subheader("🏫 校内固有のルール")
    st.session_state.school_rules = st.text_area(
        "追加ルールがあれば記述:",
        value=st.session_state.school_rules,
        height=120
    )
    
    st.success("🔒 個人情報保護フィルター: 有効")

# ==========================================
# 6. メイン画面
# ==========================================
st.title("📝 ツナグ先生 - 所見自動生成システム")
st.caption(f"現在のモード: **{doc_type}**")

tab1, tab2, tab3 = st.tabs(["👤 個人作成 & AI微調整", "📁 CSVクラス一括作成", "🖨️ 印刷プレビュー・校務連携"])

# ------------------------------------------
# タブ1: 個人作成 ＆ 高度化プロンプト
# ------------------------------------------
with tab1:
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("1. 観察記録の入力")
        student_name = st.text_input("生徒名（省略可）", placeholder="例: 山田 太郎")
        subject = st.selectbox("対象・分野", ["総合（通知表/要録）", "行動の記録", "国語", "数学", "理科", "社会", "英語", "体育", "特別活動・その他"])
        episodes = st.text_area(
            "具体的なエピソード・観察メモ", 
            placeholder="短いメモでもOK！\n例:\n・理科 実験で班長\n・後半の計算ミス 自発的にチェック", 
            height=160
        )
        max_chars = st.number_input("希望文字数（目安）", min_value=50, max_value=500, value=150, step=10)
        
        generate_btn = st.button("✨ 所見文案を生成する", use_container_width=True, type="primary")

    with col2:
        st.subheader("2. 生成結果 & AIチャット微調整")
        
        if generate_btn:
            if not api_key:
                st.error("サイドバーでAPIキーを入力してください。")
            elif not episodes:
                st.warning("エピソードを入力してください。")
            else:
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    masked_episodes, name_map = mask_pii(episodes, student_name)
                    
                    # 💡 高度化プロンプト（段階的思考の導入）
                    prompt = f"""
                    あなたはベテランの小学校・中学校教員です。
                    提供された断片的な観察メモから、児童生徒の強みや成長の姿が伝わる質の高い所見文章を作成してください。

                    【基本情報】
                    - 対象分野: {subject}
                    - 観察メモ: {masked_episodes}
                    - 目安文字数: 約{max_chars}文字前後（指定文字数から±15%以内）

                    【作成の手引き（思考プロセス）】
                    1. 観察メモ内の事実から「どんな資質・能力（主体性、協調性、思考力など）」が表れているかを読み取ってください。
                    2. 「事実（行い）」だけでなく、「そこに至る姿勢」や「今後の期待・成長」へ自然に繋げてください。
                    3. 重複した表現を避け、一文一文を適度な長さに保って可読性を高めてください。

                    【厳格ルール】
                    - {ending_instruction}
                    - 校内ルール: {st.session_state.school_rules}
                    - 解説、挨拶、前置きは一切不要です。所見の文章本文のみを出力してください。
                    """
                    
                    with st.spinner(f"AIが作成中（{doc_type}）..."):
                        response = model.generate_content(prompt)
                        final_text = unmask_pii(response.text.strip(), name_map)
                        
                        st.session_state.generated_findings = final_text
                        st.session_state.chat_history = [{"role": "assistant", "content": final_text}]
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

        if st.session_state.generated_findings:
            edited_text = st.text_area("現在の文案（手修正可能）:", value=st.session_state.generated_findings, height=130)
            st.session_state.generated_findings = edited_text
            
            st.caption(f"文字数: {len(edited_text)}文字")
            st.markdown("---")
            
            st.caption("💬 **AIに対話で修正指示を出す（チャット調整）**")
            user_instruction = st.text_input("修正の指示:", placeholder="例: 「あと20文字縮めて」「後半の算数の努力をもっと強調して」")
            if st.button("✨ 指示通りに微調整する"):
                if user_instruction and api_key:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    refine_prompt = f"""
                    現在の所見文章を、指示に従って修正・再構築してください。
                    
                    【現在の文章】
                    {st.session_state.generated_findings}
                    
                    【修正指示】
                    {user_instruction}
                    
                    【遵守ルール】
                    - {ending_instruction}
                    - {st.session_state.school_rules}
                    
                    本文のみを出力してください。
                    """
                    with st.spinner("微調整中..."):
                        response = model.generate_content(refine_prompt)
                        st.session_state.generated_findings = response.text.strip()
                        st.rerun()

# ------------------------------------------
# タブ2: CSV一括作成
# ------------------------------------------
with tab2:
    st.subheader("CSVファイルからクラス全員分を一括生成")
    st.caption(f"※現在設定されているルール: **{doc_type}**")
    
    uploaded_file = st.file_uploader("CSVファイルをアップロード (列: 名前, エピソード)", type=["csv"])
    
    if uploaded_file:
        content = uploaded_file.getvalue().decode("utf-8")
        csv_reader = csv.reader(io.StringIO(content))
        header = next(csv_reader, None)
        rows = list(csv_reader)
        
        st.write(f"📂 読み込んだ生徒数: **{len(rows)}名**")
        
        if st.button("🚀 全員分を一括生成する", type="primary"):
            if not api_key:
                st.error("APIキーを入力してください。")
            else:
                model = genai.GenerativeModel("gemini-2.5-flash")
                results = [["名前", "入力エピソード", "生成所見"]]
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, row in enumerate(rows):
                    if len(row) >= 2:
                        name, ep = row[0], row[1]
                        status_text.text(f"処理中 ({i+1}/{len(rows)}): {name}さん")
                        
                        masked_ep, name_map = mask_pii(ep, name)
                        
                        prompt = f"""
                        ベテラン教員として、以下のエピソードから適切な所見を作成してください。
                        - エピソード: {masked_ep}
                        
                        【必須ルール】
                        - {ending_instruction}
                        - {st.session_state.school_rules}
                        
                        本文のみを出力してください。
                        """
                        try:
                            res = model.generate_content(prompt)
                            clean_res = unmask_pii(res.text.strip(), name_map)
                            results.append([name, ep, clean_res])
                        except Exception as e:
                            results.append([name, ep, f"エラー: {e}"])
                        
                        progress_bar.progress((i + 1) / len(rows))
                
                status_text.success("全員分の生成が完了しました！")
                
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerows(results)
                
                st.download_button(
                    label="📥 生成結果をCSVでダウンロード",
                    data=output.getvalue().encode("utf-8-sig"),
                    file_name="所見一括生成結果.csv",
                    mime="text/csv"
                )

# ------------------------------------------
# タブ3: 印刷・校務システム連携
# ------------------------------------------
with tab3:
    st.subheader("🖨️ 印刷プレビュー ＆ 校務システム用コピペ")
    
    if st.session_state.generated_findings:
        st.markdown("### 📋 校務Webシステム（ミライシード/C4th等）貼り付け用")
        st.code(st.session_state.generated_findings, language=None)
        
        st.markdown("---")
        st.markdown("### 📄 確認・提出用カード印刷プレビュー")
        st.caption("※ブラウザの「印刷」（Ctrl + P）でそのままPDF化・紙印刷が可能です。")
        
        print_html = f"""
        <div style="border: 2px solid #333; padding: 20px; border-radius: 8px; background-color: #fff; color: #000;">
            <div style="display: flex; justify-content: space-between; border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 12px;">
                <h3 style="margin: 0;">所見確認シート ({doc_type})</h3>
                <span style="font-size: 14px;">対象: {student_name if student_name else '未設定'}</span>
            </div>
            <p style="font-size: 15px; line-height: 1.8; white-space: pre-wrap; margin-top: 10px;">{st.session_state.generated_findings}</p>
            <div style="margin-top: 20px; text-align: right; font-size: 12px; color: #666;">
                文字数: {len(st.session_state.generated_findings)}文字
            </div>
        </div>
        """
        st.components.v1.html(print_html, height=260, scrolling=True)
    else:
        st.info("※「個人作成」タブで所見を生成すると、ここにコピー用テキストと印刷枠が表示されます。")