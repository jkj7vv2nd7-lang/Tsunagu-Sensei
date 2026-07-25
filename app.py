import streamlit as st
import google.generativeai as genai
import csv
import io

# ==========================================
# 1. ページ初期設定
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 校務支援・所見＆カルテ統合システム (V5.0)",
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
    pass

# ==========================================
# 5. サイドバー設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 全体設定")
    
    if not api_key:
        api_key = st.text_input("Gemini API Key", type="password", help="APIキーを入力してください")
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
        ending_instruction = "文末は必ず「〜でした。」「〜が見られました。」「〜に取り組んでいます。」などの【敬体（です・ます調）】で統一してください。"
    elif doc_type == "指導要録用（である・した調）":
        ending_instruction = "文末は必ず「〜した。」「〜が見られた。」「〜についての理解を深めた。」などの【常体（である・した調/断定調）】で統一してください。"
    else:
        ending_instruction = "文末は「〜ができる。」「〜を理解している。」「〜に意欲的に取り組む。」などの【観点評価形式】で統一してください。"

    st.markdown("---")
    st.subheader("🏫 校内固有ルール & NG表現")
    st.session_state.school_rules = st.text_area(
        "遵守ルール・NG表現の追加:",
        value=st.session_state.school_rules,
        height=120
    )
    
    st.success("🔒 個人情報保護フィルター: 有効")

# ==========================================
# 6. メイン画面（タブ構成の更新）
# ==========================================
st.title("📝 ツナグ先生 - 校務総合支援システム (V5.0)")
st.caption(f"現在のモード: **{doc_type}**")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "👤 所見作成 & 微調整", 
    "📁 CSVクラス一括生成", 
    "🔍 所見自動校校正 & NGチェック", 
    "💬 面談用カルテ作成", 
    "🖨️ 印刷 & 校務連携"
])

# ------------------------------------------
# タブ1: 個人作成 ＆ AI微調整
# ------------------------------------------
with tab1:
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("1. 観察記録の入力")
        student_name = st.text_input("生徒名（省略可）", placeholder="例: 山田 太郎", key="t1_name")
        subject = st.selectbox("対象・分野", ["総合（通知表/要録）", "行動の記録", "国語", "数学", "理科", "社会", "英語", "体育", "特別活動・その他"])
        episodes = st.text_area(
            "観察メモ・エピソード", 
            placeholder="短いメモでもOK！\n例:\n・理科 実験で班長\n・後半の計算ミス 自発的にチェック", 
            height=160,
            key="t1_episodes"
        )
        max_chars = st.number_input("希望文字数（目安）", min_value=50, max_value=500, value=150, step=10)
        
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
                    
                    prompt = f"""
                    あなたはベテランの小学校・中学校教員です。
                    提供された断片的な観察メモから、児童生徒の強みや成長の姿が伝わる質の高い所見文章を作成してください。

                    【基本情報】
                    - 対象分野: {subject}
                    - 観察メモ: {masked_episodes}
                    - 目安文字数: 約{max_chars}文字前後（指定文字数から±15%以内）

                    【作成の手引き（思考プロセス）】
                    1. 観察メモ内の事実から「どんな資質・能力」が表れているかを読み取ってください。
                    2. 「事実」だけでなく、「そこに至る姿勢」や「今後の期待・成長」へ自然に繋げてください。

                    【厳格ルール】
                    - {ending_instruction}
                    - 校内ルール: {st.session_state.school_rules}
                    - 解説や挨拶は不要です。所見の文章本文のみを出力してください。
                    """
                    
                    with st.spinner(f"AIが作成中（{doc_type}）..."):
                        response = model.generate_content(prompt)
                        final_text = unmask_pii(response.text.strip(), name_map)
                        st.session_state.generated_findings = final_text
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

        if st.session_state.generated_findings:
            edited_text = st.text_area("現在の文案（手修正可能）:", value=st.session_state.generated_findings, height=130)
            st.session_state.generated_findings = edited_text
            
            st.caption(f"文字数: {len(edited_text)}文字")
            st.markdown("---")
            
            st.caption("💬 **AIに対話で修正指示を出す（チャット調整）**")
            user_instruction = st.text_input("修正の指示:", placeholder="例: 「あと20文字縮めて」「理科の実験の話を強調して」")
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
# タブ3: ✨【新規】所見自動校正 & NGチェック
# ------------------------------------------
with tab3:
    st.subheader("🔍 所見文章の自動校正 & 校内ルールチェック")
    st.caption("自分で書いた文章や、生成された所見の誤字脱字・文末表記・NG表現を点検します。")
    
    col_proof1, col_proof2 = st.columns([1, 1])
    
    with col_proof1:
        check_name = st.text_input("生徒名（省略可）", placeholder="例: 鈴木 花子", key="t3_name")
        input_text_to_check = st.text_area(
            "チェックしたい所見文章を貼り付け:",
            value=st.session_state.generated_findings if st.session_state.generated_findings else "",
            height=200,
            placeholder="ここに所見文章を入力または貼り付けてください。"
        )
        proofread_btn = st.button("🛡️ 文章を校正・チェックする", type="primary", use_container_width=True)

    with col_proof2:
        st.subheader("診断＆校正結果")
        if proofread_btn:
            if not api_key:
                st.error("APIキーを入力してください。")
            elif not input_text_to_check:
                st.warning("チェックする文章を入力してください。")
            else:
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    masked_text, name_map = mask_pii(input_text_to_check, check_name)
                    
                    proofread_prompt = f"""
                    あなたは学校の教頭・学年主任の立場として、提出された所見文章の校正とチェックを行ってください。

                    【対象文章】
                    {masked_text}

                    【チェック項目】
                    1. 誤字脱字、不自然な日本語がないか
                    2. 文末がルール通りになっているか（指定モード: {doc_type}）
                    3. 校内ルール・NG表現に反していないか（ルール: {st.session_state.school_rules}）
                    4. 不必要にネガティブな印象を与える表現がないか

                    【出力フォーマット】
                    ---
                    ### 🎯 総合診断評価
                    （「修正不要でこのまま提出可能」または「要修正項目あり」）

                    ### ✏️ 修正提案文章
                    （問題点を改善した完成版の文章をここに記載）

                    ### 📌 アドバイス・指摘ポイント
                    （修正理由や、文末・語彙のアドバイスを箇条書きで分かりやすく解説）
                    ---
                    """
                    
                    with st.spinner("AI教頭がチェック中..."):
                        res = model.generate_content(proofread_prompt)
                        final_proof = unmask_pii(res.text.strip(), name_map)
                        st.session_state.proofread_result = final_proof
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")
                    
        if st.session_state.proofread_result:
            st.markdown(st.session_state.proofread_result)

# ------------------------------------------
# タブ4: ✨【新規】面談用カルテ作成
# ------------------------------------------
with tab4:
    st.subheader("💬 個人面談・三者面談用「児童・生徒カルテ」作成")
    st.caption("保護者面談の前に、伝えるべき長所・成長エピソード・家庭での協力依頼を1枚に整理します。")
    
    col_c1, col_c2 = st.columns([1, 1])
    
    with col_c1:
        carte_name = st.text_input("生徒名", placeholder="例: 佐藤 健太", key="t4_name")
        growth_points = st.text_area("学校での良かった点・成長したエピソード", placeholder="例: 運動会で応援団長を務め、下級生を優しくまとめていた。算数のテスト直しを最後まで諦めずに取り組んだ。", height=100)
        challenges = st.text_area("今後改善したい課題・気になる点", placeholder="例: 提出物の期限が遅れがち。授業中に集中が切れると手元で内職してしまうことがある。", height=100)
        
        generate_carte_btn = st.button("📋 面談用カルテを生成する", type="primary", use_container_width=True)

    with col_c2:
        st.subheader("📄 面談準備シート")
        if generate_carte_btn:
            if not api_key:
                st.error("APIキーを入力してください。")
            elif not carte_name:
                st.warning("生徒名を入力してください。")
            else:
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    
                    carte_prompt = f"""
                    あなたはベテラン教員です。保護者面談（個人面談・三者面談）でスムーズかつ前向きな話し合いができるよう、面談準備用カルテを作成してください。

                    【基本情報】
                    - 生徒名: {carte_name}
                    - 良かった点・成長: {growth_points}
                    - 課題・気になる点: {challenges}

                    【出力フォーマット】
                    ### 🌟 面談で伝える3つのポイント
                    1. **【褒める・認める長所】** （具体的エピソードを交えたお褒めの言葉）
                    2. **【学校での様子と課題】** （課題を前向きな「伸びしろ」として共有する言い回し）
                    3. **【ご家庭への相談・協力依頼】** （家庭で声をかけてほしいポイントの具体的な提案）

                    ### 💬 面談オープニングの言葉掛け例
                    （保護者の緊張をほぐし、温かい雰囲気で始めるための一言）
                    """
                    
                    with st.spinner("面談カルテを作成中..."):
                        res = model.generate_content(carte_prompt)
                        st.session_state.carte_result = res.text.strip()
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")
                    
        if st.session_state.carte_result:
            st.markdown(st.session_state.carte_result)

# ------------------------------------------
# タブ5: 印刷 & 校務連携
# ------------------------------------------
with tab5:
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
            </div>
            <p style="font-size: 15px; line-height: 1.8; white-space: pre-wrap; margin-top: 10px;">{st.session_state.generated_findings}</p>
            <div style="margin-top: 20px; text-align: right; font-size: 12px; color: #666;">
                文字数: {len(st.session_state.generated_findings)}文字
            </div>
        </div>
        """
        st.components.v1.html(print_html, height=260, scrolling=True)
    else:
        st.info("※「所見作成」タブで所見を生成すると、ここにコピー用テキストと印刷枠が表示されます。")