import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path


TYPE_NAMES = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "short_answer": "简答题",
    "essay": "论述题",
}


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_bank(script_dir):
    candidates = []
    for path in script_dir.glob("*.json"):
        if path.name == "quiz_history.json":
            continue
        try:
            data = load_json(path, {})
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            candidates.append(path)
    if not candidates:
        raise SystemExit("未找到题库 JSON，请用 --bank 指定文件")
    return candidates[0]


def normalize_answer(answer):
    if isinstance(answer, bool):
        return "√" if answer else "×"
    if isinstance(answer, list):
        return "".join(str(x).strip().upper() for x in answer)
    return str(answer).strip().upper()


def normalize_user_answer(text, qtype):
    text = text.strip()
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


def flatten_questions(bank):
    questions = bank.get("questions") or []
    return [q for q in questions if isinstance(q, dict) and q.get("id")]


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


def choose_questions(questions, num, exclude_ids, types):
    pool = questions
    if types:
        allowed = set(types)
        pool = [q for q in pool if q.get("type") in allowed]
    available = [q for q in pool if q.get("id") not in exclude_ids]
    if len(available) < num:
        print(f"可用题目不足 {num} 道，已排除后仅剩 {len(available)} 道，将从可用题中抽取。")
    sample_size = min(num, len(available))
    if sample_size <= 0:
        raise SystemExit("没有可抽取的题目")
    return random.sample(available, sample_size)


def print_question(index, total, q):
    print("\n" + "=" * 60)
    print(f"第 {index}/{total} 题 [{q.get('typeName') or TYPE_NAMES.get(q.get('type'), q.get('type'))}] {q.get('chapter', '')}")
    print(q.get("question", ""))
    options = q.get("options") or {}
    if isinstance(options, dict):
        for key in sorted(options.keys()):
            print(f"{key}. {options[key]}")


def ask_objective(q):
    qtype = q.get("type")
    if qtype == "true_false":
        prompt = "请输入答案（√/×，或 对/错）："
    elif qtype == "multiple_choice":
        prompt = "请输入答案（多选直接输入字母，如 ABC）："
    else:
        prompt = "请输入答案："
    while True:
        user = input(prompt).strip()
        if user:
            return user


def ask_subjective(q):
    user = input("请输入你的作答，直接回车可跳过：").strip()
    print("\n参考答案：")
    print(q.get("answer", ""))
    while True:
        judged = input("请自行判断是否答对？(y/n)：").strip().lower()
        if judged in ("y", "yes", "对", "正确"):
            return user, True
        if judged in ("n", "no", "错", "错误"):
            return user, False


def run_quiz(args, bank_path, history_path):
    bank = load_json(bank_path, {})
    history = load_json(history_path, [])
    questions = flatten_questions(bank)
    exclude_ids = recent_question_ids(history, args.exclude_recent)
    selected = choose_questions(questions, args.num, exclude_ids, args.types)
    results = []
    correct_count = 0

    print(f"题库：{bank_path.name}")
    print(f"本次抽题：{len(selected)} 道")

    for index, q in enumerate(selected, 1):
        print_question(index, len(selected), q)
        qtype = q.get("type")
        if qtype in ("short_answer", "essay"):
            user_answer, is_correct = ask_subjective(q)
            correct_answer = str(q.get("answer", ""))
        else:
            user_answer = ask_objective(q)
            correct_answer = normalize_answer(q.get("answer"))
            is_correct = answer_equal(user_answer, q.get("answer"), qtype)
            print("正确" if is_correct else f"错误，正确答案：{correct_answer}")
        if is_correct:
            correct_count += 1
        results.append({
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

    total = len(selected)
    score = round(correct_count / total * 100, 2) if total else 0
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bank": str(bank_path),
        "total": total,
        "correct": correct_count,
        "score": score,
        "items": results,
    }
    history.append(record)
    save_json(history_path, history)

    print("\n" + "=" * 60)
    print(f"本次得分：{score} 分，答对 {correct_count}/{total}")
    print(f"记录已保存：{history_path}")


def show_history(args, history_path):
    history = load_json(history_path, [])
    if not history:
        print("暂无历史记录")
        return
    records = history[-args.limit:] if args.limit else history
    for i, record in enumerate(records, len(history) - len(records) + 1):
        print(f"{i}. {record.get('time')}  得分：{record.get('score')}  正确：{record.get('correct')}/{record.get('total')}")
        if args.details:
            for item in record.get("items", []):
                mark = "√" if item.get("is_correct") else "×"
                print(f"   {mark} [{item.get('typeName')}] {item.get('question')}")


def show_wrong(args, bank_path, history_path):
    history = load_json(history_path, [])
    bank = load_json(bank_path, {})
    question_map = {q.get("id"): q for q in flatten_questions(bank)}
    wrong = {}
    for record in history:
        for item in record.get("items", []):
            if not item.get("is_correct"):
                qid = item.get("id")
                if qid not in wrong:
                    wrong[qid] = {"count": 0, "last": item}
                wrong[qid]["count"] += 1
                wrong[qid]["last"] = item
    if not wrong:
        print("暂无错题")
        return
    rows = sorted(wrong.items(), key=lambda x: x[1]["count"], reverse=True)
    if args.limit:
        rows = rows[:args.limit]
    for index, (qid, info) in enumerate(rows, 1):
        q = question_map.get(qid) or info["last"]
        print("\n" + "=" * 60)
        print(f"错题 {index}  错误次数：{info['count']}  [{q.get('typeName') or TYPE_NAMES.get(q.get('type'), q.get('type'))}]")
        print(q.get("chapter", ""))
        print(q.get("question", ""))
        options = q.get("options") or {}
        if isinstance(options, dict):
            for key in sorted(options.keys()):
                print(f"{key}. {options[key]}")
        print(f"正确答案：{normalize_answer(q.get('answer', info['last'].get('correct_answer')))}")
        print(f"最近作答：{info['last'].get('user_answer')}")


def build_parser():
    parser = argparse.ArgumentParser(description="题库随机测验命令行工具")
    parser.add_argument("--bank", type=Path, help="题库 JSON 文件路径，默认自动查找同目录题库")
    parser.add_argument("--history-file", type=Path, help="历史记录 JSON 文件路径，默认同目录 quiz_history.json")
    subparsers = parser.add_subparsers(dest="command")

    quiz = subparsers.add_parser("quiz", help="开始随机测验")
    quiz.add_argument("-n", "--num", type=int, default=10, help="抽题数量，默认 10")
    quiz.add_argument("--exclude-recent", type=int, default=0, help="排除最近 N 次测验出现过的题")
    quiz.add_argument("--types", nargs="+", choices=list(TYPE_NAMES.keys()), help="限定题型")

    history = subparsers.add_parser("history", help="查看历史成绩")
    history.add_argument("--limit", type=int, default=20, help="显示最近 N 条，默认 20")
    history.add_argument("--details", action="store_true", help="显示每题对错")

    wrong = subparsers.add_parser("wrong", help="错题回顾")
    wrong.add_argument("--limit", type=int, default=0, help="显示前 N 道错题，默认全部")

    return parser


def main():
    script_dir = Path(__file__).resolve().parent
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "quiz"
        args.num = 10
        args.exclude_recent = 0
        args.types = None
    bank_path = args.bank.resolve() if args.bank else find_bank(script_dir)
    history_path = args.history_file.resolve() if args.history_file else script_dir / "quiz_history.json"
    if args.command == "quiz":
        if args.num <= 0:
            raise SystemExit("抽题数量必须大于 0")
        run_quiz(args, bank_path, history_path)
    elif args.command == "history":
        show_history(args, history_path)
    elif args.command == "wrong":
        show_wrong(args, bank_path, history_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出")
        sys.exit(1)
