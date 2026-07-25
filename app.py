import streamlit as st
import google.generativeai as genai
import csv
import io
import pandas as pd
import re
from docx import Document

# ==========================================
# 1. ページ設定 & カスタムCSS
# ==========================================
st.set_page_config(
    page_title="ツナグ先生 - 統合校務支援システム (V9.3)",
    page_icon="🏫",
    layout="wide"
)

st.markdown("""
    <style>
    div[data-baseweb="tab-list"] { flex-wrap: wrap !important; gap: 4px 6px !important; }
    button[data-baseweb="tab"] { height: auto !important; padding: 6px 12px !important; border-radius: 6px !important; background-color: #f0f2f6; font-weight: bold !important; }
    button[aria-selected="true"] { background-color: #1f77b4 !important; color: white !important; }
    .student-card { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. データベース（セッション状態）の初期化
# ==========================================

# 年度・学級設定
if "school_year" not in st.session_state:
    st.session_state.school_year = "2026"
if "teacher_name" not in st.session_state:
    st.session_state.teacher_name = "山田 太郎"

# クラス基本名簿（転入・転出対応）
if "student_master" not in st.session_state:
    st.session_state.student_master = pd.DataFrame([
        {"クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "性別": "男", "ステータス": "在籍", "異動日": "", "備考": ""},
        {"クラス": "2年1組", "出席番号": 2, "氏名": "伊藤 葵", "性別": "女", "ステータス": "在籍", "異動日": "", "備考": ""},
        {"クラス": "2年2組", "出席番号": 1, "氏名": "加藤 健太", "性別": "男", "ステータス": "在籍", "異動日": "", "備考": ""},
        {"クラス": "2年2組", "出席番号": 2, "氏名": "木村 結衣", "性別": "女", "ステータス": "在籍", "異動日": "", "備考": ""},
    ])

# 日々の観察メモ蓄積DB
if "daily_logs" not in st.session_state:
    st.session_state.daily_logs = pd.DataFrame([
        {"日付": "2026-05-10", "クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "対象分野": "数学", "観察メモ": "方程式の文章題で自力で立式し、解き進めることができた。"},
        {"日付": "2026-06-15", "クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "対象分野": "総合・行動", "観察メモ": "班長としてグループの話し合いを主体的にまとめ、発表を担当した。"},
        {"日付": "2026-05-12", "クラス": "2年1組", "出席番号": 2, "氏名": "伊藤 葵", "対象分野": "英語", "観察メモ": "単語テストで満点を取り、ペアワークでも積極的に発音の練習を行っていた。"},
    ])

# 担当教科成績データ
if "subject_scores" not in st.session_state:
    st.session_state.subject_scores = pd.DataFrame([
        {"クラス": "2年1組", "出席番号": 1, "氏名": "相沢 拓海", "観点1_知識": 85, "観点2_思考": 78, "観点3_主体性": 90, "評定": 4, "総合所見": "方程式の立式において粘り強い取り組みが見られました。"},
        {"クラス": "2年1組", "出席番号": 2, "氏名": "伊藤 葵", "観点1_知識": 92, "観点2_思考": 88, "観点3_主体性": 95, "評定": 5, "総合所見": "ペアワーク等で周囲を明るくリードし、深く学習に取り組めました。"},
        {"クラス": "2年2組", "出席番号": 1, "氏名": "加藤 健太", "観点1_知識": 70, "観点2_思考": 65, "観点3_主体性": 75, "評定": 3, "総合所見": "授業中の集中力が高く、着実に課題を達成しています。"},
        {"クラス": "2年2組", "出席番号": 2, "氏名": "木村 結衣", "観点1_知識": 95, "観点2_思考": 92, "観点3_主体性": 90, "評定": 5, "総合所見": "発展的な学習課題に対しても自発的に挑戦する姿勢が素晴らしかったです。"},
    ])

# APIキー設定
api_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

with st.sidebar:
    st.header("⚙️ システム・基本情報")
    st.session_state.school_year = st.text_input("年度設定", st.session_state.school_year)
    st.session_state.teacher_name = st.text_input("担任教員名", st.session_state.teacher_name)
    
    st.markdown("---")
    if not api_key:
        api_key = st.text_input("Gemini API Key", type="password")
    else:
        st.success("🔑 API連携中")
    if api_key:
        genai.configure(api_key=api_key)
        
    doc_type = st.radio("文末モード:", ["です・ます調（通知表）", "である・した調（要録）"])
    ending_rule = "文末は「です・ます」調で統一。" if "です" in doc_type else "文末は「である・した」調で統一。"

# Wordタグ置換関数
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

# 登録済みクラス一覧を取得する関数（動的）
def get_all_classes():
    classes = sorted(st.session_state.student_master["クラス"].dropna().unique().tolist())
    return classes if classes else ["1年1組"]

# 在籍生徒リスト取得関数
def get_active_students(cls_name=None):
    df = st.session_state.student_master
    active_df = df[df["ステータス"] == "在籍"]
    if cls_name:
        active_df = active_df[active_df["クラス"] == cls_name]
    return active_df["氏名"].tolist()

# ==========================================
# 3. メイン画面（タブ構成）
# ==========================================
st.title(f"🏫 ツナグ先生 - 統合校務支援システム (V9.3 / {st.session_state.school_year}年度)")

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "⚙️ ⓪ 担任＆授業担当 名簿管理",
    "📝 ① 日々メモ蓄積 & 所見",
    "📁 ② CSV一括生成",
    "🔍 ③ 所見データ自動校正",
    "💬 ④ 蓄積連動カルテ",
    "📊 ⑤ 成績＆評定自動計算",
    "📈 ⑥ 学期推移ダッシュボード",
    "🔄 ⑦ 担任用 全教科成績集約",
    "🖨️ ⑧ 通知表・要録 印刷＆出力"
])

# ------------------------------------------
# タブ0: ⓪ 担任＆授業担当 名簿管理（クラス追加対応）
# ------------------------------------------
with tab0:
    st.subheader("⚙️ 学級名簿 ＆ 授業担当クラス名簿の管理")
    
    m_tab1, m_tab2 = st.tabs(["🏫 担任学級名簿・クラス追加・転入転出", "📚 授業担当クラス名簿（成績用コピペ出力）"])
    
    with m_tab1:
        col_m1, col_m2 = st.columns([1.2, 1])
        
        with col_m1:
            st.markdown("### 📋 現在のマスター学級名簿")
            st.caption("※ テーブル一番下の『＋』から生徒を追加したり、『クラス』名を直接「1年3組」などに変更・自由追加できます。")
            edited_master = st.data_editor(
                st.session_state.student_master,
                num_rows="dynamic",
                use_container_width=True,
                key="master_editor"
            )
            st.session_state.student_master = edited_master

        with col_m2:
            st.markdown("### 🔄 転入・転出・新クラス生徒追加")
            action_type = st.radio("手続き種別:", ["生徒の新規登録・転入処理", "年度途中 転出（除籍）処理"])
            
            if action_type == "生徒の新規登録・転入処理":
                with st.form("trans_in_form"):
                    current_classes = get_all_classes()
                    in_cls_select = st.selectbox("登録クラス（既存から選択）", current_classes + ["新規クラスを直接入力"])
                    
                    in_cls_custom = ""
                    if in_cls_select == "新規クラスを直接入力":
                        in_cls_custom = st.text_input("新規クラス名を入力（例: 1年3組、3年1組）", placeholder="3年1組")
                    
                    target_cls = in_cls_custom if in_cls_select == "新規クラスを直接入力" else in_cls_select
                    
                    in_num = st.number_input("出席番号", min_value=1, max_value=50, value=1)
                    in_name = st.text_input("生徒氏名")
                    in_gender = st.selectbox("性別", ["男", "女"])
                    in_date = st.date_input("登録日・転入日")
                    in_sub = st.form_submit_button("➕ 生徒を登録する")
                    
                    if in_sub and in_name and target_cls:
                        new_st = pd.DataFrame([{
                            "クラス": target_cls, "出席番号": in_num, "氏名": in_name, "性別": in_gender,
                            "ステータス": "在籍", "異動日": str(in_date), "備考": "新規登録"
                        }])
                        st.session_state.student_master = pd.concat([st.session_state.student_master, new_st], ignore_index=True)
                        st.success(f"{target_cls} に {in_name} さんを登録しました！")
                        st.rerun()

            else:
                with st.form("trans_out_form"):
                    active_list = get_active_students()
                    out_name = st.selectbox("転出する生徒を選択", active_list if active_list else ["なし"])
                    out_date = st.date_input("転出日")
                    out_reason = st.text_input("転出先・理由（例: 市外転出）")
                    out_sub = st.form_submit_button("⚠️ 転出処理を実行する")
                    
                    if out_sub and out_name in active_list:
                        idx = st.session_state.student_master[st.session_state.student_master["氏名"] == out_name].index
                        st.session_state.student_master.loc[idx, "ステータス"] = "転出"
                        st.session_state.student_master.loc[idx, "異動日"] = str(out_date)
                        st.session_state.student_master.loc[idx, "備考"] = out_reason
                        st.warning(f"{out_name} さんの転出手続きを完了しました。名簿上で除籍表示されます。")
                        st.rerun()

    with m_tab2:
        st.markdown("### 📚 授業を担当するクラス名簿の抽出・コピペ出力")
        st.caption("他学年を含む担当クラスを選択し、成績ファイルや他システムへ貼り付けられる名簿を生成します。")
        
        all_classes = get_all_classes()
        selected_teach_cls = st.multiselect("あなたが授業を担当するクラスを選択:", all_classes, default=all_classes)
        
        if selected_teach_cls:
            sub_df = st.session_state.student_master[
                (st.session_state.student_master["クラス"].isin(selected_teach_cls)) &
                (st.session_state.student_master["ステータス"] == "在籍")
            ][["クラス", "出席番号", "氏名"]].sort_values(by=["クラス", "出席番号"])
            
            st.write(f"📋 **授業担当名簿（計 {len(sub_df)} 名）**")
            st.dataframe(sub_df, use_container_width=True)
            
            tsv_text = sub_df.to_csv(sep='\t', index=False)
            
            st.markdown("#### 📋 成績管理ファイル（Excel・Googleスプレッドシート等）への貼り付け用データ")
            st.text_area("以下のテキストをコピーし、Excelや成績ファイルの先頭セルにそのまま貼り付け（Ctrl+V）できます:", tsv_text, height=150)
            
            st.download_button(
                label="📥 授業担当名簿（CSV）を保存",
                data=sub_df.to_csv(index=False).encode('utf-8-sig'),
                file_name="授業担当クラス名簿.csv",
                mime="text/csv"
            )

# ------------------------------------------
# タブ1: ① 日々メモ蓄積 & 所見生成
# ------------------------------------------
with tab1:
    col_a, col_b = st.columns([1, 1.2])
    active_students = get_active_students()
    all_cls = get_all_classes()
    
    with col_a:
        st.subheader("📌 1. 日々の観察メモを蓄積・登録")
        with st.form("add_log_form", clear_on_submit=True):
            f_date = st.date_input("日付")
            f_class = st.selectbox("クラス", all_cls)
            f_name = st.selectbox("生徒氏名（在籍者のみ）", active_students if active_students else ["在籍者なし"])
            f_cat = st.selectbox("対象分野", ["総合・行動の記録", "数学", "国語", "英語", "理科", "社会", "特別活動"])
            f_memo = st.text_area("観察メモ（音声入力可）", placeholder="例: 授業中に手を挙げて自力で答える姿が見られた。")
            submitted = st.form_submit_button("📥 データベースに保存")
            
            if submitted and f_name and f_memo:
                new_row = pd.DataFrame([{"日付": str(f_date), "クラス": f_class, "出席番号": 1, "氏名": f_name, "対象分野": f_cat, "観察メモ": f_memo}])
                st.session_state.daily_logs = pd.concat([st.session_state.daily_logs, new_row], ignore_index=True)
                st.success(f"{f_name} さんのメモを蓄積しました！")

    with col_b:
        st.subheader("✨ 2. 蓄積メモから所見自動生成")
        selected_student = st.selectbox("所見を作成する生徒を選択:", active_students, key="t1_st")
        
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
    target_cls = st.selectbox("一括生成対象クラス:", get_all_classes())
    
    if st.button("🚀 クラス全員の蓄積メモからCSVを一括生成"):
        cls_memos = st.session_state.daily_logs[st.session_state.daily_logs["クラス"] == target_cls]
        results = []
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        for name, group in cls_memos.groupby("氏名"):
            if name in get_active_students():
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
        student_for_check = st.selectbox("校正する生徒を選択:", get_active_students(), key="chk_st")
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
    kart_student = st.selectbox("面談対象の生徒を選択:", get_active_students(), key="kart_st")
    
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
    st.subheader("📊 授業担当用 成績入力 & 評定自動計算")
    st.caption("※ タブ⓪で作成した授業担当名簿に合わせて、観点評価・テスト得点を入力・編集できます。")
    edited_scores = st.data_editor(st.session_state.subject_scores, num_rows="dynamic", use_container_width=True, key="score_editor")
    st.session_state.subject_scores = edited_scores
    
    if st.button("⚡ 観点から5段階評定を自動計算して付与"):
        def calc_grade(row):
            avg = (row["観点1_知識"] + row["観点2_思考"] + row["観点3_主体性"]) / 3
            if avg >= 85: return 5
            elif avg >= 70: return 4
            elif avg >= 55: return 3
            elif avg >= 40: return 2
            else: return 1
            
        edited_scores["評定"] = edited_scores.apply(calc_grade, axis=1)
        st.session_state.subject_scores = edited_scores
        st.success("🎉 全クラスの観点平均から5段階評定を自動計算しました！")
        st.dataframe(edited_scores, use_container_width=True)

# ------------------------------------------
# タブ6: ⑥ 学期推移ダッシュボード
# ------------------------------------------
with tab6:
    st.subheader("📈 担任用 学期推移ダッシュボード")
    trend_df = pd.DataFrame([
        {"氏名": "相沢 拓海", "1学期": 3, "2学期": 4, "3学期": 4, "状態": "上昇傾向"},
        {"氏名": "伊藤 葵", "1学期": 5, "2学期": 4, "3学期": 3, "状態": "要フォロー"},
    ])
    st.dataframe(trend_df, use_container_width=True)
    st.line_chart(trend_df.set_index("氏名")[["1学期", "2学期", "3学期"]].T)

# ------------------------------------------
# タブ7: ⑦ 全教科成績集約
# ------------------------------------------
with tab7:
    st.subheader("🔄 各教科のバラバラな成績ファイルを1人1行に自動合体")
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

# ------------------------------------------
# タブ8: 🖨️ 通知表・要録 印刷＆個別ファイル出力
# ------------------------------------------
with tab8:
    st.subheader("🖨️ 通知表・指導要録 個別表示 ＆ ファイル印刷出力")
    st.caption("全タブの蓄積データ・成績・所見を集約し、生徒ごとの『完成版・通知表プレビュー』を表示・出力します。")

    col_out1, col_out2 = st.columns([1, 2])

    with col_out1:
        st.markdown("### 1. 対象書類と生徒の選択")
        doc_kind = st.selectbox("出力書類種別", ["通知表（あゆみ）", "指導要録（様式2）", "個別の指導計画"])
        selected_cls = st.selectbox("対象クラス", get_all_classes(), key="out_cls")
        
        # 該当クラスの在籍生徒
        cls_active_students = get_active_students(selected_cls)
        print_student = st.selectbox("対象生徒を選択:", cls_active_students if cls_active_students else ["なし"])
        
        template_word = st.file_uploader("学校独自Wordテンプレート (.docx) をアップロード (任意)", type=["docx"])

    with col_out2:
        st.markdown(f"### 📄 画面表示プレビュー ({doc_kind})")
        
        if print_student and print_student != "なし":
            st_info = st.session_state.student_master[st.session_state.student_master["氏名"] == print_student].iloc[0].to_dict()
            score_match = st.session_state.subject_scores[st.session_state.subject_scores["氏名"] == print_student]
            st_score = score_match.iloc[0].to_dict() if not score_match.empty else {}
            
            st.markdown(f"""
            <div class="student-card">
                <h3>【{st.session_state.school_year}年度 {doc_kind}】</h3>
                <p><strong>クラス:</strong> {st_info.get('クラス')} | <strong>出席番号:</strong> {st_info.get('出席番号')}番 | <strong>氏名:</strong> <span style="font-size:1.2em; font-weight:bold;">{print_student}</span> 様</p>
                <p><strong>担任教員:</strong> {st.session_state.teacher_name}</p>
                <hr>
                <h4>📊 評価・評定状況</h4>
                <ul>
                    <li>知識・技能 観点: <strong>{st_score.get('観点1_知識', '-')}</strong> 点</li>
                    <li>思考・判断・表現 観点: <strong>{st_score.get('観点2_思考', '-')}</strong> 点</li>
                    <li>主体的に学習に取り組む態度: <strong>{st_score.get('観点3_主体性', '-')}</strong> 点</li>
                    <li>学習評定（5段階）: <strong style="font-size:1.3em; color:#d9534f;">{st_score.get('評定', '-')}</strong></li>
                </ul>
                <hr>
                <h4>📝 総合所見</h4>
                <p style="background-color: white; padding: 10px; border-radius: 5px; border: 1px solid #ccc;">
                    {st_score.get('総合所見', '（所見がまだ登録・生成されていません）')}
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("📄 この生徒のWord通知表を生成・ダウンロード", type="primary"):
                doc_data = {
                    "年度": st.session_state.school_year,
                    "担任名": st.session_state.teacher_name,
                    "クラス": st_info.get('クラス'),
                    "出席番号": st_info.get('出席番号'),
                    "氏名": print_student,
                    "観点1": st_score.get('観点1_知識', ''),
                    "観点2": st_score.get('観点2_思考', ''),
                    "観点3": st_score.get('観点3_主体性', ''),
                    "評定": st_score.get('評定', ''),
                    "総合所見": st_score.get('総合所見', '')
                }
                
                if template_word:
                    doc = Document(template_word)
                else:
                    doc = Document()
                    doc.add_heading(f"{doc_kind} - {print_student} 様", 0)
                    doc.add_paragraph(f"年度: {st.session_state.school_year}年度 | 担任: {st.session_state.teacher_name}")
                    doc.add_paragraph(f"クラス: {st_info.get('クラス')}  出席番号: {st_info.get('出席番号')}")
                    doc.add_paragraph(f"評定: {st_score.get('評定', '')}")
                    doc.add_paragraph(f"総合所見:\n{st_score.get('総合所見', '')}")
                
                filled_doc = replace_docx_tags(doc, doc_data)
                out_buffer = io.BytesIO()
                filled_doc.save(out_buffer)
                
                st.download_button(
                    label=f"📥 {print_student} さんの Wordファイルを保存",
                    data=out_buffer.getvalue(),
                    file_name=f"{doc_kind}_{print_student}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )