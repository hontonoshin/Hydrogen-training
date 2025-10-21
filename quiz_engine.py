#!/usr/bin/env python3
# quiz_engine.py — question model and engine

from dataclasses import dataclass
from typing import List, Dict, Optional
import random

@dataclass
class Question:
    id: str
    category: str
    difficulty: str
    question: str
    choices: List[str]
    correct_index: int
    rationale: str = ""

    @staticmethod
    def from_dict(d: Dict) -> "Question":
        return Question(
            id=str(d.get("id","")),
            category=d.get("category","General"),
            difficulty=d.get("difficulty",""),
            question=d["question"],
            choices=list(d["choices"]),
            correct_index=int(d["correct_index"]),
            rationale=d.get("rationale","")
        )

class QuizEngine:
    def __init__(self, questions: List[Question]):
        self.all_questions = questions
        self.quiz_items: List[Question] = []
        self.index = 0
        self.correct_count = 0
        self.history: List[Dict] = []

    def categories(self):
        return set(q.category for q in self.all_questions)

    def prepare_quiz(self, n: int, category: Optional[str], shuffle: bool):
        pool = [q for q in self.all_questions if (category is None or q.category == category)]
        if shuffle:
            random.shuffle(pool)
        self.quiz_items = pool[:max(1, n)]
        self.index = 0
        self.correct_count = 0
        self.history.clear()

    def current(self) -> Optional[Question]:
        if 0 <= self.index < len(self.quiz_items):
            return self.quiz_items[self.index]
        return None

    def check_and_record(self, chosen_index: int):
        q = self.current()
        if not q:
            return False, ""
        is_correct = (chosen_index == q.correct_index)
        if is_correct:
            self.correct_count += 1
        rec = {
            "id": q.id,
            "question": q.question,
            "chosen": q.choices[chosen_index] if 0 <= chosen_index < len(q.choices) else "",
            "correct_text": q.choices[q.correct_index] if 0 <= q.correct_index < len(q.choices) else "",
            "is_correct": is_correct,
            "rationale": q.rationale,
            "category": q.category,
            "difficulty": q.difficulty
        }
        self.history.append(rec)
        return is_correct, q.rationale

    def next(self):
        if self.index + 1 < len(self.quiz_items):
            self.index += 1
            return True
        return False

    def score(self):
        return self.correct_count

    def summary(self):
        total = len(self.quiz_items)
        s = [f"Your score: {self.correct_count}/{total} ({int(100*self.correct_count/max(1,total))}%)\n"]
        s.append("Review:\n")
        for i, rec in enumerate(self.history, start=1):
            s.append(f"{i}. {rec['question']}")
            s.append(f"   Your answer: {rec['chosen']}")
            s.append(f"   Correct answer: {rec['correct_text']}")
            if rec.get("rationale"):
                s.append(f"   Why: {rec['rationale']}")
            s.append("")
        return "\n".join(s)
