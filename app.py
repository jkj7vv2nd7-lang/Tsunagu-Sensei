import streamlit as st
import google.generativeai as genai
import csv
import io
import pandas as pd

# ==========================================
# 1. ページ初期設定
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 校務支援・成績＆所見統合システム (V6.0)",
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

# デモ用成績データの初期化
if "score_data" not in st.session_state:
    st.session_state.score_data = pd.DataFrame([
        {"出席番号": 1, "氏名": "相沢 拓海", "単元1_知識": "85", "単元2_知識": "90", "単元1_思考": "78", "単元2_思考": "82", "主体性": "A", "備考": ""},
        {"出席番号": 2, "氏名": "伊藤 葵", "単元1_知識": "欠", "単元2_知識": "88", "単元1_思考": "欠", "単元2_思考": "85", "主体性": "A", "備考": "単元1病欠（見込み処理）"},
        {"出席番号": 3, "氏名": "上野 翔太", "単元1_知識": "62", "単元2_知識": "58", "単元1_思考": "55", "単元2_思考": "欠", "主体性": "B", "備考": "単元2公欠"},
        {"出席番号": 4, "氏名": "遠藤 桜", "単元1_知識": "45", "単元2_知識": "50", "単元1_思考": "40", "単元2_思考": "42", "主体性": "C", "備考": "要支援"},
    ])

# ==========================================
# 3. セキュリティ：ローカル完全匿名化ロジック
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
# 4. APIキーの自動取得
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
        height=100
    )
    
    st.success("🔒 個人情報保護フィルター: 有効")

# ==========================================
# 6. メイン画面（6タブ構成へ拡張）
# ==========================================
st.title("📝 ツナグ先生 - 校務総合支援システム (V6.0)")
st.caption(f"現在のモード: **{doc_type}**")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "👤 所見作成 & 微調整", 
    "📁 CSVクラス一括生成", 
    "🔍 所見自動校正 & NGチェック", 
    "💬 面談用カルテ作成", 
    "📊 成績蓄積 & 数学科部会支援", 
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
        subject = st.selectbox("対象・分野", ["総合（通知表/要録）", "行動の記録", "数学", "国語", "理科", "社会", "英語", "体育", "特別活動・その他"])
        episodes = st.text_area(
            "観察メモ・エピソード", 
            placeholder="短いメモでもOK！\n例:\n・数学 方程式の文章題で自力で立式できた\n・後半の計算ミス 自発的に見直し実施", 
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
                    あなたはベテラン教員です。提供された観察メモから質の高い所見文章を作成してください。
                    - 対象分野: {subject}
                    - 観察メモ: {masked_episodes}
                    - 目安文字数: 約{max_chars}文字前後

                    【ルール】
                    - {ending_instruction}
                    - 校内ルール: {st.session_state.school_rules}
                    - 本文のみを出力してください。
                    """
                    with st.spinner(f"AIが作成中..."):
                        response = model.generate_content(prompt)
                        st.session_state.generated_findings = unmask_pii(response.text.strip(), name_map)
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

        if st.session_state.generated_findings:
            edited_text = st.text_area("現在の文案（手修正可能）:", value=st.session_state.generated_findings, height=130)
            st.session_state.generated_findings = edited_text
            st.caption(f"文字数: {len(edited_text)}文字")
            st.markdown("---")
            
            user_instruction = st.text_input("修正の指示:", placeholder="例: 「数学の論理的思考をもっとほめて」")
            if st.button("✨ 指示通りに微調整する"):
                if user_instruction and api_key:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    refine_prompt = f"""
                    現在の所見文章を修正してください。
                    文章: {st.session_state.generated_findings}
                    指示: {user_instruction}
                    ルール: {ending_instruction} / {st.session_state.school_rules}
                    本文のみ出力してください。
                    """
                    with st.spinner("微調整中..."):
                        res = model.generate_content(refine_prompt)
                        st.session_state.generated_findings = res.text.strip()
                        st.rerun()

# ------------------------------------------
# タブ2: CSV一括作成
# ------------------------------------------
with tab2:
    st.subheader("CSVファイルからクラス全員分を一括生成")
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
                        ベテラン教員として、以下のエピソードから所見を作成してください。
                        エピソード: {masked_ep}
                        ルール: {ending_instruction} / {st.session_state.school_rules}
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
                csv.writer(output).writerows(results)
                st.download_button("📥 生成結果をCSVでダウンロード", data=output.getvalue().encode("utf-8-sig"), file_name="所見一括生成結果.csv", mime="text/csv")

# ------------------------------------------
# タブ3: 所見自動校正 & NGチェック
# ------------------------------------------
with tab3:
    st.subheader("🔍 所見文章の自動校正 & 校内ルールチェック")
    col_proof1, col_proof2 = st.columns([1, 1])
    
    with col_proof1:
        check_name = st.text_input("生徒名（省略可）", placeholder="例: 鈴木 花子", key="t3_name")
        input_text_to_check = st.text_area(
            "チェックしたい所見文章:",
            value=st.session_state.generated_findings if st.session_state.generated_findings else "",
            height=200
        )
        proofread_btn = st.button("🛡️ 文章を校正・チェックする", type="primary", use_container_width=True)

    with col_proof2:
        st.subheader("診断＆校正結果")
        if proofread_btn:
            if not api_key:
                st.error("APIキーを入力してください。")
            elif not input_text_to_check:
                st.warning("文章を入力してください。")
            else:
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    masked_text, name_map = mask_pii(input_text_to_check, check_name)
                    
                    proofread_prompt = f"""
                    学校の教頭として、以下の所見文章をチェック・校正してください。
                    文章: {masked_text}
                    項目: 誤字脱字、文末統一（{doc_type}）、校内ルール（{st.session_state.school_rules}）、不適切な表現の有無

                    フォーマット:
                    ### 🎯 総合診断評価
                    ### ✏️ 修正提案文章
                    ### 📌 アドバイス・指摘ポイント
                    """
                    with st.spinner("AI教頭がチェック中..."):
                        res = model.generate_content(proofread_prompt)
                        st.session_state.proofread_result = unmask_pii(res.text.strip(), name_map)
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")
                    
        if st.session_state.proofread_result:
            st.markdown(st.session_state.proofread_result)

# ------------------------------------------
# タブ4: 面談用カルテ作成
# ------------------------------------------
with tab4:
    st.subheader("💬 個人面談・三者面談用「児童・生徒カルテ」作成")
    col_c1, col_c2 = st.columns([1, 1])
    
    with col_c1:
        carte_name = st.text_input("生徒名", placeholder="例: 佐藤 健太", key="t4_name")
        growth_points = st.text_area("学校での良かった点・成長したエピソード", height=100)
        challenges = st.text_area("今後改善したい課題・気になる点", height=100)
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
                    保護者面談用に以下の情報からカルテを作成してください。
                    生徒名: {carte_name} / 成長点: {growth_points} / 課題: {challenges}

                    フォーマット:
                    ### 🌟 面談で伝える3つのポイント（1.褒める点 2.伸びしろ 3.家庭への相談）
                    ### 💬 面談オープニングの言葉掛け例
                    """
                    with st.spinner("面談カルテを作成中..."):
                        res = model.generate_content(carte_prompt)
                        st.session_state.carte_result = res.text.strip()
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")
                    
        if st.session_state.carte_result:
            st.markdown(st.session_state.carte_result)

# ------------------------------------------
# タブ5: ✨【新規拡張】成績蓄積 & 数学科部会支援
# ------------------------------------------
with tab5:
    st.subheader("📊 成績蓄積・観点別自動集計・教科部会（成績会議）支援")
    st.caption("テスト点数（欠席時は「欠」と入力）から観点別評価・評定を算出し、部会での協議資料を作成します。")

    # 成績計算ヘルパー関数
    def calc_score_and_grade(row):
        # 知識・技能の計算
        k_scores = []
        for col in ["単元1_知識", "単元2_知識"]:
            val = str(row[col]).strip()
            if val.isdigit():
                k_scores.append(float(val))
        
        k_avg = sum(k_scores) / len(k_scores) if k_scores else 0
        k_eval = "A" if k_avg >= 80 else ("B" if k_avg >= 60 else "C")
        if len(k_scores) < 2:
            k_eval += " (見込み)"

        # 思考・判断・表現の計算
        t_scores = []
        for col in ["単元1_思考", "単元2_思考"]:
            val = str(row[col]).strip()
            if val.isdigit():
                t_scores.append(float(val))
                
        t_avg = sum(t_scores) / len(t_scores) if t_scores else 0
        t_eval = "A" if t_avg >= 80 else ("B" if t_avg >= 60 else "C")
        if len(t_scores) < 2:
            t_eval += " (見込み)"

        # 主体性
        j_eval = str(row["主体性"]).strip()

        # 5段階評定の暫定算出
        score_map = {"A": 3, "A (見込み)": 3, "B": 2, "B (見込み)": 2, "C": 1, "C (見込み)": 1}
        total_pts = score_map.get(k_eval, 2) + score_map.get(t_eval, 2) + score_map.get(j_eval, 2)
        
        if total_pts >= 8:
            rating = 5
        elif total_pts >= 7:
            rating = 4
        elif total_pts >= 5:
            rating = 3
        elif total_pts >= 4:
            rating = 2
        else:
            rating = 1

        return pd.Series({
            "知識・技能 (平均/評価)": f"{k_avg:.1f}点 ➔ {k_eval}",
            "思考・判断 (平均/評価)": f"{t_avg:.1f}点 ➔ {t_eval}",
            "主体性": j_eval,
            "仮評定 (1~5)": rating,
            "判定理由・部会検討メモ": "未受験あり（要確認）" if ("見込み" in k_eval or "見込み" in t_eval) else "順調"
        })

    st.markdown("### 1. 成績データの入力・編集（テスト結果 & 未受験『欠』の管理）")
    edited_df = st.data_editor(
        st.session_state.score_data,
        num_rows="dynamic",
        use_container_width=True,
        key="score_editor"
    )
    st.session_state.score_data = edited_df

    st.markdown("---")
    st.markdown("### 2. 🧮 観点別自動算定 & 数学科部会（成績会議）提示プロジェクター画面")
    
    calc_results = edited_df.apply(calc_score_and_grade, axis=1)
    summary_df = pd.concat([edited_df[["出席番号", "氏名", "備考"]], calc_results], axis=1)

    # ハイライト用スタイリング関数
    def highlight_borderline(val):
        color = ''
        if '未受験' in str(val):
            color = 'background-color: #fff3cd; color: #856404; font-weight: bold;' # 黄色ハイライト
        return color

    st.dataframe(
        summary_df.style.applymap(highlight_borderline, subset=["判定理由・部会検討メモ"]),
        use_container_width=True
    )

    st.markdown("---")
    st.markdown("### 3. 📤 教科部会用資料・Excelエクスポート")
    
    # Excelデータ作成
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        summary_df.to_excel(writer, index=False, sheet_name='数学科評定一覧')
    excel_data = excel_buffer.getvalue()

    col_ex1, col_ex2 = st.columns([1, 1])
    with col_ex1:
        st.download_button(
            label="📊 部会用成績一覧表をExcel (.xlsx) でダウンロード",
            data=excel_data,
            file_name="数学科_観点別評価・評定集計表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

# ------------------------------------------
# タブ6: 印刷 & 校務連携
# ------------------------------------------
with tab6:
    st.subheader("🖨️ 印刷プレビュー ＆ 校務システム用コピペ")
    
    if st.session_state.generated_findings:
        st.markdown("### 📋 校務Webシステム貼り付け用")
        st.code(st.session_state.generated_findings, language=None)
        st.markdown("---")
        st.markdown("### 📄 確認・提出用カード印刷プレビュー")
        
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