import json
import random
from datetime import datetime
from pathlib import Path

import streamlit as st


TYPE_NAMES = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "short_answer": "简答题",
    "essay": "论述题",
}

SCRIPT_DIR = Path(__file__).resolve().parent
HISTORY_FILE = SCRIPT_DIR / "quiz_history.json"


st.set_page_config(
    page_title="概论题库练习",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.main .block-container { padding-top: 1.5rem; max-width: 1180px; }
.hero {
    padding: 1.3rem 1.5rem;
    border-radius: 20px;
    background: linear-gradient(135deg, #eef2ff 0%, #fdf2f8 55%, #ecfeff 100%);
    border: 1px solid rgba(99,102,241,.18);
    margin-bottom: 1rem;
}
.hero h1 { margin: 0; font-size: 2.1rem; }
.hero p { margin: .35rem 0 0 0; color: #475569; }
.card {
    padding: 1rem 1.1rem;
    border-radius: 16px;
    background: white;
    border: 1px solid #e5e7eb;
    box-shadow: 0 8px 26px rgba(15, 23, 42, .05);
    margin-bottom: .8rem;
}
.question-title { font-size: 1.08rem; font-weight: 700; line-height: 1.8; }
.meta { color: #64748b; font-size: .9rem; margin-bottom: .45rem; }
.option-box {
    border: 1px solid #e5e7eb;
    background: #f8fafc;
    border-radius: 12px;
    padding: .55rem .75rem;
    margin: .35rem 0;
}
.correct { color: #15803d; font-weight: 700; }
.wrong { color: #dc2626; font-weight: 700; }
.small-muted { color: #64748b; font-size: .9rem; }
</style>
""",
    unsafe_allow_html=True,
)


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_banks():
    banks = []
    for path in SCRIPT_DIR.glob("*.json"):
        if path.name == HISTORY_FILE.name:
            continue
        try:
            data = load_json(path, {})
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            banks.append(path)
    return banks


@st.cache_data(show_spinner=False)
def load_bank(path_str):
    path = Path(path_str)
    data = load_json(path, {})
    questions = [q for q in data.get("questions", []) if isinstance(q, dict) and q.get("id")]
    return data, questions


def normalize_answer(answer):
    if isinstance(answer, bool):
        return "√" if answer else "×"
    if isinstance(answer, list):
        return "".join(str(x).strip().upper() for x in answer)
    return str(answer).strip().upper()


def normalize_user_answer(answer, qtype):
    text = str(answer).strip()
    if qtype == "true_false":
        mapping = {
            "Y": "√", "YES": "√", "TRUE": "√", "T": "√", "1": "√", "对": "√", "正确": "√", "√": "√",
            "N": "×", "NO": "×", "FALSE": "×", "F": "×", "0": "×", "错": "×", "错误": "×", "X": "×", "×": "×",
        }
        return mapping.get(text.upper(), mapping.get(text, text))
    if qtype in ("single_choice", "multiple_choice"):
        return "".join(sorted(text.replace(" ", "").replace(",", "").replace("，", "").upper()))
    return text


def answer_equal(user_answer, correct_answer, qtype):
    user = normalize_user_answer(user_answer, qtype)
    correct = normalize_answer(correct_answer)
    if qtype in ("single_choice", "multiple_choice"):
        correct = "".join(sorted(correct))
    return user == correct


def recent_question_ids(history, count):
    ids = set()
    if count <= 0:
        return ids
    for quiz in history[-count:]:
        for item in quiz.get("items", []):
            qid = item.get("id") or item.get("question_id")
            if qid:
                ids.add(qid)
    return ids


def choose_questions(questions, num, exclude_ids, types, chapters):
    pool = questions
    if types:
        pool = [q for q in pool if q.get("type") in types]
    if chapters:
        pool = [q for q in pool if q.get("chapter") in chapters]
    available = [q for q in pool if q.get("id") not in exclude_ids]
    return random.sample(available, min(num, len(available))) if available else []


def init_quiz(selected):
    st.session_state.quiz_questions = selected
    st.session_state.quiz_index = 0
    st.session_state.quiz_results = []
    st.session_state.quiz_finished = False
    st.session_state.feedback = None


def reset_quiz():
    for key in ["quiz_questions", "quiz_index", "quiz_results", "quiz_finished", "feedback"]:
        st.session_state.pop(key, None)


def render_options(q):
    options = q.get("options") or {}
    if isinstance(options, dict) and options:
        for key in sorted(options.keys()):
            st.markdown(f"<div class='option-box'><b>{key}.</b> {options[key]}</div>", unsafe_allow_html=True)


def answer_widget(q, key_prefix):
    qtype = q.get("type")
    options = q.get("options") or {}
    keys = sorted(options.keys()) if isinstance(options, dict) else []
    if qtype == "single_choice":
        return st.radio("选择答案", keys, format_func=lambda x: f"{x}. {options.get(x, '')}", key=f"{key_prefix}_single")
    if qtype == "multiple_choice":
        values = st.multiselect("选择答案（可多选）", keys, format_func=lambda x: f"{x}. {options.get(x, '')}", key=f"{key_prefix}_multi")
        return "".join(values)
    if qtype == "true_false":
        return st.radio("判断", ["√", "×"], format_func=lambda x: "正确 √" if x == "√" else "错误 ×", key=f"{key_prefix}_tf")
    return st.text_area("你的答案", height=130, key=f"{key_prefix}_text")


def submit_answer(q, user_answer, subjective_correct=None):
    qtype = q.get("type")
    if qtype in ("short_answer", "essay"):
        is_correct = bool(subjective_correct)
        correct_answer = str(q.get("answer", ""))
    else:
        is_correct = answer_equal(user_answer, q.get("answer"), qtype)
        correct_answer = normalize_answer(q.get("answer"))
    st.session_state.quiz_results.append({
        "id": q.get("id"),
        "chapter": q.get("chapter"),
        "type": qtype,
        "typeName": q.get("typeName") or TYPE_NAMES.get(qtype, qtype),
        "question": q.get("question"),
        "options": q.get("options"),
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "is_correct": is_correct,
    })
    st.session_state.feedback = {"is_correct": is_correct, "correct_answer": correct_answer}


def next_question(history_path):
    st.session_state.feedback = None
    st.session_state.quiz_index += 1
    if st.session_state.quiz_index >= len(st.session_state.quiz_questions):
        finish_quiz(history_path)


def finish_quiz(history_path):
    results = st.session_state.quiz_results
    total = len(results)
    correct = sum(1 for item in results if item.get("is_correct"))
    score = round(correct / total * 100, 2) if total else 0
    history = load_json(history_path, [])
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bank": str(st.session_state.get("bank_path", "")),
        "total": total,
        "correct": correct,
        "score": score,
        "items": results,
    })
    save_json(history_path, history)
    st.session_state.quiz_finished = True


def quiz_page(bank_path, questions, history_path):
    history = load_json(history_path, [])
    chapters = sorted({q.get("chapter", "未分章") for q in questions})
    type_labels = {v: k for k, v in TYPE_NAMES.items()}

    with st.sidebar:
        st.subheader("练习设置")
        num = st.slider("抽题数量", 1, max(1, min(100, len(questions))), min(10, max(1, len(questions))))
        exclude_recent = st.number_input("排除最近 N 次测验", 0, 50, 0, 1)
        chosen_type_labels = st.multiselect("题型筛选", list(type_labels.keys()), default=[])
        chosen_chapters = st.multiselect("章节筛选", chapters, default=[])
        types = [type_labels[x] for x in chosen_type_labels]
        if st.button("开始新测验", type="primary", use_container_width=True):
            selected = choose_questions(questions, num, recent_question_ids(history, exclude_recent), types, chosen_chapters)
            if not selected:
                st.error("没有符合条件的题目")
            else:
                st.session_state.bank_path = str(bank_path)
                init_quiz(selected)
                st.rerun()
        if st.button("清空当前测验", use_container_width=True):
            reset_quiz()
            st.rerun()

    if "quiz_questions" not in st.session_state:
        st.info("请在左侧设置后点击“开始新测验”。")
        col1, col2, col3 = st.columns(3)
        col1.metric("题目总数", len(questions))
        col2.metric("历史测验", len(history))
        wrong_total = sum(1 for r in history for i in r.get("items", []) if not i.get("is_correct"))
        col3.metric("累计错题记录", wrong_total)
        return

    if st.session_state.quiz_finished:
        results = st.session_state.quiz_results
        total = len(results)
        correct = sum(1 for item in results if item.get("is_correct"))
        score = round(correct / total * 100, 2) if total else 0
        st.success("本次测验已完成")
        c1, c2, c3 = st.columns(3)
        c1.metric("得分", score)
        c2.metric("答对", correct)
        c3.metric("总题数", total)
        with st.expander("查看本次答题详情", expanded=True):
            for i, item in enumerate(results, 1):
                mark = "✅" if item.get("is_correct") else "❌"
                st.markdown(f"**{i}. {mark} [{item.get('typeName')}] {item.get('question')}**")
                st.caption(f"你的答案：{item.get('user_answer')} | 正确答案：{item.get('correct_answer')}")
        if st.button("再来一组", type="primary"):
            reset_quiz()
            st.rerun()
        return

    selected = st.session_state.quiz_questions
    idx = st.session_state.quiz_index
    q = selected[idx]
    progress = (idx + 1) / len(selected)
    st.progress(progress, text=f"第 {idx + 1} / {len(selected)} 题")
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='meta'>{q.get('chapter', '')} · {q.get('typeName') or TYPE_NAMES.get(q.get('type'), q.get('type'))}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='question-title'>{q.get('question', '')}</div>", unsafe_allow_html=True)
    if q.get("type") not in ("single_choice", "multiple_choice"):
        render_options(q)
    user_answer = answer_widget(q, f"q_{idx}_{q.get('id')}")
    st.markdown("</div>", unsafe_allow_html=True)

    feedback = st.session_state.feedback
    if feedback is None:
        if q.get("type") in ("short_answer", "essay"):
            with st.expander("查看参考答案并自评"):
                st.write(q.get("answer", ""))
                c1, c2 = st.columns(2)
                if c1.button("我答对了", type="primary", use_container_width=True):
                    submit_answer(q, user_answer, True)
                    st.rerun()
                if c2.button("我答错了", use_container_width=True):
                    submit_answer(q, user_answer, False)
                    st.rerun()
        else:
            if st.button("提交答案", type="primary"):
                if not str(user_answer).strip():
                    st.warning("请先作答")
                else:
                    submit_answer(q, user_answer)
                    st.rerun()
    else:
        if feedback["is_correct"]:
            st.markdown("<p class='correct'>回答正确</p>", unsafe_allow_html=True)
        else:
            st.markdown(f"<p class='wrong'>回答错误，正确答案：{feedback['correct_answer']}</p>", unsafe_allow_html=True)
        if st.button("下一题", type="primary"):
            next_question(history_path)
            st.rerun()


def history_page(history_path):
    history = load_json(history_path, [])
    if not history:
        st.info("暂无历史成绩")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("测验次数", len(history))
    c2.metric("平均分", round(sum(r.get("score", 0) for r in history) / len(history), 2))
    c3.metric("最高分", max(r.get("score", 0) for r in history))
    rows = [{"序号": i + 1, "时间": r.get("time"), "得分": r.get("score"), "正确": r.get("correct"), "总题数": r.get("total")} for i, r in enumerate(history)]
    st.dataframe(rows[::-1], use_container_width=True, hide_index=True)
    selected = st.selectbox("查看详情", list(range(len(history), 0, -1)), format_func=lambda x: f"第 {x} 次：{history[x - 1].get('time')} / {history[x - 1].get('score')} 分")
    record = history[selected - 1]
    for i, item in enumerate(record.get("items", []), 1):
        mark = "✅" if item.get("is_correct") else "❌"
        with st.expander(f"{i}. {mark} [{item.get('typeName')}] {item.get('question')}"):
            options = item.get("options") or {}
            if isinstance(options, dict):
                for key in sorted(options.keys()):
                    st.write(f"{key}. {options[key]}")
            st.write(f"你的答案：{item.get('user_answer')}")
            st.write(f"正确答案：{item.get('correct_answer')}")


def wrong_page(bank_path, questions, history_path):
    history = load_json(history_path, [])
    question_map = {q.get("id"): q for q in questions}
    wrong = {}
    for record in history:
        for item in record.get("items", []):
            if not item.get("is_correct"):
                qid = item.get("id")
                wrong.setdefault(qid, {"count": 0, "last": item})
                wrong[qid]["count"] += 1
                wrong[qid]["last"] = item
    if not wrong:
        st.info("暂无错题")
        return
    rows = sorted(wrong.items(), key=lambda x: x[1]["count"], reverse=True)
    st.metric("错题数量", len(rows))
    if st.button("从错题中开始练习", type="primary"):
        selected = [question_map.get(qid, info["last"]) for qid, info in rows]
        st.session_state.bank_path = str(bank_path)
        init_quiz(selected)
        st.rerun()
    for index, (qid, info) in enumerate(rows, 1):
        q = question_map.get(qid) or info["last"]
        with st.expander(f"{index}. 错 {info['count']} 次 · [{q.get('typeName') or TYPE_NAMES.get(q.get('type'), q.get('type'))}] {q.get('question')}"):
            st.caption(q.get("chapter", ""))
            options = q.get("options") or {}
            if isinstance(options, dict):
                for key in sorted(options.keys()):
                    st.write(f"{key}. {options[key]}")
            st.write(f"正确答案：{normalize_answer(q.get('answer', info['last'].get('correct_answer')))}")
            st.write(f"最近作答：{info['last'].get('user_answer')}")


def main():
    st.markdown(
        "<div class='hero'><h1>概论题库练习系统</h1><p>随机抽题、交互答题、成绩统计、错题回顾</p></div>",
        unsafe_allow_html=True,
    )
    banks = find_banks()
    if not banks:
        st.error("未找到题库 JSON，请把题库 JSON 放在本脚本同目录。")
        return
    with st.sidebar:
        bank_path = st.selectbox("题库文件", banks, format_func=lambda p: p.name)
        page = st.radio("功能", ["开始练习", "历史成绩", "错题回顾"], label_visibility="collapsed")
    bank, questions = load_bank(str(bank_path))
    st.caption(f"当前题库：{bank.get('title', bank_path.name)} · 共 {len(questions)} 道题")
    if page == "开始练习":
        quiz_page(bank_path, questions, HISTORY_FILE)
    elif page == "历史成绩":
        history_page(HISTORY_FILE)
    else:
        wrong_page(bank_path, questions, HISTORY_FILE)


if __name__ == "__main__":
    main()
