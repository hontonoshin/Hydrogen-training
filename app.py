#!/usr/bin/env python3
# app.py — Hydrogen Safety Trainer (GUI) with:
# - pass threshold (default 70%) gates certificate
# - topic recommendations from incorrect answers
# - improved status/flow
# Requires: reportlab; Optional (for QR) qrcode[pil]

import os
import json
import csv
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from quiz_engine import QuizEngine, Question
from certificate import generate_certificate
from resources import SAFETY_TIPS

APP_TITLE = "Hydrogen Safety Trainer — v1.2"
LOG_DIR = "outputs"
os.makedirs(LOG_DIR, exist_ok=True)

PASS_THRESHOLD_DEFAULT = 0.70  # 70%

# ---------------- Improved conceptual simulation (same as previous v1.1) ----------------
class SafetyAnimation(ttk.Frame):
    """
    Grid-based scalar concentration model (conceptual, not CFD):
      - 2D grid in a rectangular 'room'. Each tick:
        * inject source mass near leak
        * upward advection (buoyancy)
        * simple 4-neighbor diffusion (mixing)
        * vent removal at top slot
      - Sliders: leak rate, vent strength, buoyancy (advection), diffusion.
    """
    def __init__(self, master):
        super().__init__(master)
        self.W, self.H = 700, 380
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg="#f7f7f9", highlightthickness=0)
        self.canvas.pack(fill="both", expand=False)

        self.NX, self.NY = 70, 35
        self.room_px = (50, 20, 650, 360)
        self.leak_cell = (6, self.NY-4)
        self.vent_x0, self.vent_x1 = 20, self.NX-20
        self.after_id = None
        self.running = False

        self.leak_rate = tk.DoubleVar(value=0.8)
        self.vent_strength = tk.DoubleVar(value=0.6)
        self.buoyancy = tk.DoubleVar(value=0.45)
        self.diffusion = tk.DoubleVar(value=0.20)

        ctrl = ttk.Frame(self); ctrl.pack(fill="x", pady=(6,2))
        ttk.Button(ctrl, text="Start", command=self.start).pack(side="left", padx=4)
        ttk.Button(ctrl, text="Pause", command=self.pause).pack(side="left", padx=4)
        ttk.Button(ctrl, text="Reset", command=self.reset).pack(side="left", padx=12)

        def add_slider(label, var, frm, to):
            f = ttk.Frame(ctrl); f.pack(side="left", padx=10)
            ttk.Label(f, text=label).pack()
            ttk.Scale(f, from_=frm, to=to, orient="horizontal", variable=var, length=130).pack()
        add_slider("Leak", self.leak_rate, 0.0, 2.0)
        add_slider("Vent", self.vent_strength, 0.0, 1.0)
        add_slider("Buoyancy", self.buoyancy, 0.0, 1.0)
        add_slider("Diffusion", self.diffusion, 0.0, 0.6)

        ttk.Label(self, text="Conceptual model: buoyant gas rises, ventilates at ceiling (not CFD).",
                  foreground="#666").pack(anchor="w", padx=8, pady=(2,8))

        self._init_grid()
        self._init_cells()

    def _init_grid(self):
        import numpy as np
        self.c = np.zeros((self.NY, self.NX), dtype=float)
        self.tmp = np.zeros_like(self.c)

    def _init_cells(self):
        x0, y0, x1, y1 = self.room_px
        gw = (x1-x0) / self.NX
        gh = (y1-y0) / self.NY
        self.cells = []
        for j in range(self.NY):
            row = []
            for i in range(self.NX):
                rx0 = x0 + i*gw
                ry0 = y0 + j*gh
                rid = self.canvas.create_rectangle(rx0, ry0, rx0+gw+1, ry0+gh+1, outline="", fill="#ffffff")
                row.append(rid)
            self.cells.append(row)
        self.canvas.create_rectangle(*self.room_px, outline="#888", width=2)
        # vent
        x0v = self.room_px[0] + (self.vent_x0/self.NX)*(self.room_px[2]-self.room_px[0])
        x1v = self.room_px[0] + (self.vent_x1/self.NX)*(self.room_px[2]-self.room_px[0])
        self.canvas.create_rectangle(x0v, self.room_px[1]-4, x1v, self.room_px[1], fill="#d0f0ff", outline="#4aa", width=1)
        self.canvas.create_text(x1v+20, self.room_px[1]-8, text="Vent", fill="#0a6", anchor="w")
        # leak marker
        lx = self.room_px[0] + (self.leak_cell[0]+0.5)/self.NX * (self.room_px[2]-self.room_px[0])
        ly = self.room_px[1] + (self.leak_cell[1]+0.5)/self.NY * (self.room_px[3]-self.room_px[1])
        self.canvas.create_oval(lx-6, ly-6, lx+6, ly+6, fill="#b33", outline="#933")
        self.canvas.create_text(lx+28, ly-8, text="Leak source", fill="#b33", anchor="w")

    def _step(self):
        import numpy as np
        c, tmp = self.c, self.tmp
        li, lj = self.leak_cell

        # inject
        c[lj, li] += 0.5 * self.leak_rate.get()

        # buoyancy (upward advection)
        up = self.buoyancy.get()
        if up > 0:
            tmp[:] = c[:]
            tmp[:-1, :] += up * c[1:, :]
            tmp[1:,  :] -= up * c[1:, :]
            c[:] = np.maximum(tmp, 0.0)

        # diffusion
        d = self.diffusion.get()
        if d > 0:
            tmp[:] = c[:]
            tmp[1:-1,1:-1] = (
                (1-4*d) * c[1:-1,1:-1]
                + d * (c[2:,1:-1] + c[:-2,1:-1] + c[1:-1,2:] + c[1:-1,:-2])
            )
            c[:] = np.maximum(tmp, 0.0)

        # vent removal
        vent = self.vent_strength.get()
        if vent > 0:
            i0, i1 = self.vent_x0, self.vent_x1
            c[0, i0:i1] *= (1 - 0.6*vent)

        # clip
        np.clip(c, 0.0, 5.0, out=c)

    def _render(self):
        cmax = 2.5
        for j, row in enumerate(self.c):
            for i, v in enumerate(row):
                v = max(0.0, min(1.0, v / cmax))
                b = int(255 * (0.3 + 0.7*v))
                g = int(255 * (0.9 - 0.6*v))
                r = int(255 * (1.0 - 0.9*v))
                color = f"#{r:02x}{g:02x}{b:02x}"
                self.canvas.itemconfig(self.cells[j][i], fill=color)

    def loop(self):
        self._step(); self._render()
        if self.running:
            self.after_id = self.after(40, self.loop)

    def start(self):
        if self.running: return
        self.running = True; self.loop()

    def pause(self):
        self.running = False
        if self.after_id:
            self.after_cancel(self.after_id); self.after_id = None

    def reset(self):
        self.pause(); self._init_grid(); self._render()

# ---------------- Main App (now with pass threshold + recommendations) ----------------
class TrainerApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.pack(fill="both", expand=True)
        self.engine = None
        self.user_name = ""
        self.result_summary = None
        self.passed = False
        self.pass_threshold = PASS_THRESHOLD_DEFAULT

        ttk.Label(self, text=APP_TITLE, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=10, pady=(10,6))

        self.nb = ttk.Notebook(self); self.nb.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Quiz tab
        self.tab_quiz = ttk.Frame(self.nb); self.nb.add(self.tab_quiz, text="Quiz")

        toolbar = ttk.Frame(self.tab_quiz); toolbar.pack(fill="x", padx=6, pady=(6,2))
        ttk.Button(toolbar, text="Load Question Bank…", command=self.load_questions).pack(side="left", padx=4)
        self.btn_start = ttk.Button(toolbar, text="Start Quiz", command=self.start_quiz); self.btn_start.pack(side="left", padx=4)
        self.btn_cert = ttk.Button(toolbar, text="Generate Certificate", command=self.generate_cert, state="disabled")
        self.btn_cert.pack(side="left", padx=4)
        ttk.Button(toolbar, text="Save Results CSV", command=self.save_results_csv).pack(side="left", padx=4)

        # Threshold control
        self.thr_var = tk.StringVar(value=str(int(PASS_THRESHOLD_DEFAULT*100)))
        ttk.Label(toolbar, text="Pass ≥").pack(side="left", padx=(18,4))
        ttk.Entry(toolbar, textvariable=self.thr_var, width=4).pack(side="left")
        ttk.Label(toolbar, text="%").pack(side="left")

        # Quiz settings
        self.num_q_var = tk.StringVar(value="10")
        self.shuffle_var = tk.BooleanVar(value=True)
        ttk.Label(toolbar, text="Questions:").pack(side="left", padx=(18,4))
        ttk.Entry(toolbar, textvariable=self.num_q_var, width=5).pack(side="left")
        ttk.Checkbutton(toolbar, text="Shuffle", variable=self.shuffle_var).pack(side="left", padx=6)
        ttk.Label(toolbar, text="Category:").pack(side="left", padx=(14,4))
        self.category_cb = ttk.Combobox(toolbar, values=["All"], width=18, state="readonly")
        self.category_cb.set("All"); self.category_cb.pack(side="left")

        self.progress = ttk.Progressbar(self.tab_quiz, mode="determinate"); self.progress.pack(fill="x", padx=8, pady=4)
        self.status = tk.StringVar(value="Load a question bank to begin."); ttk.Label(self.tab_quiz, textvariable=self.status).pack(anchor="w", padx=8)

        self.q_text = tk.Text(self.tab_quiz, height=6, wrap="word", state="disabled"); self.q_text.pack(fill="both", expand=False, padx=8, pady=6)

        self.choice_var = tk.IntVar(value=-1)
        self.choices_frame = ttk.Frame(self.tab_quiz); self.choices_frame.pack(fill="x", padx=8, pady=(0,8))

        nav = ttk.Frame(self.tab_quiz); nav.pack(fill="x", padx=8, pady=6)
        ttk.Button(nav, text="Submit Answer", command=self.submit_answer).pack(side="left", padx=4)
        ttk.Button(nav, text="Next Question", command=self.next_question).pack(side="left", padx=4)
        ttk.Button(nav, text="Retake Quiz", command=self.retake_quiz).pack(side="right", padx=4)

        self.feedback = tk.Text(self.tab_quiz, height=9, wrap="word", state="disabled", bg="#f9fff6")
        self.feedback.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # --- Animation tab
        self.tab_anim = SafetyAnimation(self.nb); self.nb.add(self.tab_anim, text="Gas Dispersion (Concept)")

        # --- Tips tab
        self.tab_tips = ttk.Frame(self.nb); self.nb.add(self.tab_tips, text="Safety Tips")
        ttk.Label(self.tab_tips, text="Hydrogen Safety — Quick Tips", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=10, pady=(10,6))
        tips_box = tk.Text(self.tab_tips, height=18, wrap="word")
        tips_box.pack(fill="both", expand=True, padx=10, pady=(0,10))
        tips_box.insert("1.0", "\n".join(f"• {t}" for t in SAFETY_TIPS)); tips_box.config(state="disabled")

        # --- About tab
        self.tab_about = ttk.Frame(self.nb); self.nb.add(self.tab_about, text="About")
        tk.Label(self.tab_about, text=(
            "Hydrogen Safety Trainer — quiz, conceptual dispersion model, and certificates.\n"
            "Passing threshold is configurable. Recommendations highlight weak topics.\n"
            "NOTE: Visualization is qualitative, not a design or code-compliance tool."
        ), justify="left").pack(anchor="w", padx=10, pady=10)

        # Load default bank if present
        default_path = os.path.join(os.path.dirname(__file__), "questions.json")
        if os.path.exists(default_path):
            self.load_questions_from_path(default_path)

    # ---------------- Quiz flow ----------------
    def load_questions(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path: return
        self.load_questions_from_path(path)

    def load_questions_from_path(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            questions = [Question.from_dict(q) for q in raw]
            self.engine = QuizEngine(questions)
            cats = sorted(list(self.engine.categories()))
            self.category_cb["values"] = ["All"] + cats
            self.category_cb.set("All")
            self.status.set(f"Loaded {len(questions)} questions from {os.path.basename(path)}.")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def start_quiz(self):
        if not self.engine:
            messagebox.showwarning("No questions", "Please load a question bank first."); return
        try:
            self.pass_threshold = max(0.0, min(1.0, float(self.thr_var.get())/100.0))
        except Exception:
            self.pass_threshold = PASS_THRESHOLD_DEFAULT

        self.user_name = simpledialog.askstring("Your name", "Enter your full name (for the certificate):") or ""
        try:
            n = max(1, int(self.num_q_var.get()))
        except ValueError:
            n = 10
        category = self.category_cb.get()
        shuffle = self.shuffle_var.get()
        self.engine.prepare_quiz(n, category=None if category == "All" else category, shuffle=shuffle)
        self.progress["maximum"] = len(self.engine.quiz_items); self.progress["value"] = 0
        self.btn_cert.config(state="disabled")
        self.passed = False
        self.status.set(f"Quiz started. Passing threshold: {int(self.pass_threshold*100)}%. Good luck!")
        self.feedback_set(""); self.render_question()

    def render_question(self):
        self.choice_var.set(-1)
        for w in self.choices_frame.winfo_children(): w.destroy()
        self.q_text.config(state="normal"); self.q_text.delete("1.0", "end")
        q = self.engine.current()
        if not q: self.finish_quiz(); return
        self.q_text.insert("1.0", f"[{q.category}] {q.question}\n"); self.q_text.config(state="disabled")
        for i, choice in enumerate(q.choices):
            ttk.Radiobutton(self.choices_frame, text=choice, variable=self.choice_var, value=i).pack(anchor="w", pady=2)
        self.progress["value"] = self.engine.index

    def submit_answer(self):
        q = self.engine.current()
        if not q: return
        idx = self.choice_var.get()
        if idx < 0: messagebox.showinfo("Pick one", "Please select an answer."); return
        correct, rationale = self.engine.check_and_record(idx)
        if correct:
            self.feedback_set("✅ Correct!\n" + (rationale or ""))
        else:
            correct_text = q.choices[q.correct_index] if 0 <= q.correct_index < len(q.choices) else "(unknown)"
            self.feedback_set(f"❌ Incorrect.\nCorrect answer: {correct_text}\n" + (rationale or ""))

    def next_question(self):
        if not self.engine: return
        if self.engine.next():
            self.render_question(); self.feedback_set("")
        else:
            self.finish_quiz()

    def finish_quiz(self):
        score = self.engine.score(); total = len(self.engine.quiz_items)
        pct = int(100 * score / max(1, total))
        self.passed = (pct/100.0) >= self.pass_threshold
        self.btn_cert.config(state=("normal" if self.passed else "disabled"))

        # build recommendations: top categories where mistakes happened
        rec_text = self._build_recommendations()

        status_line = f"Quiz finished. Score: {score}/{total} ({pct}%). "
        if self.passed:
            status_line += "✅ PASSED."
        else:
            status_line += f"❌ NOT PASSED (need ≥ {int(self.pass_threshold*100)}%). Please retake."
        self.status.set(status_line)

        summary = self.engine.summary()
        final_text = summary + "\n" + rec_text
        self.feedback_set(final_text)
        self.result_summary = final_text

    def _build_recommendations(self):
        if not self.engine or not self.engine.history:
            return ""
        # Aggregate wrong answers by category and difficulty
        from collections import Counter, defaultdict
        wrong_by_cat = Counter()
        wrong_by_diff = Counter()
        rationales = defaultdict(list)
        for rec in self.engine.history:
            if not rec["is_correct"]:
                wrong_by_cat[rec["category"]] += 1
                wrong_by_diff[rec["difficulty"]] += 1
                if rec.get("rationale"):
                    rationales[rec["category"]].append(rec["rationale"])

        if not wrong_by_cat:
            return "\nRecommendations:\n• Great job — no missed questions. Review tips tab for reinforcement."

        top_cats = [c for c, _ in wrong_by_cat.most_common(3)]
        lines = ["\nRecommendations (focus on these topics):"]
        for cat in top_cats:
            lines.append(f"• {cat} — revise fundamentals and procedures.")
            # include up to 2 rationales as hints
            for i, r in enumerate(rationales.get(cat, [])[:2], start=1):
                lines.append(f"   ↳ Note {i}: {r}")
        # Optional difficulty hint
        if wrong_by_diff:
            hardest = wrong_by_diff.most_common(1)[0][0]
            if hardest:
                lines.append(f"• Your toughest level: {hardest}. Try more practice questions in this difficulty.")
        return "\n".join(lines)

    def retake_quiz(self):
        # just re-start with current settings
        self.start_quiz()

    def feedback_set(self, text):
        self.feedback.config(state="normal"); self.feedback.delete("1.0", "end")
        self.feedback.insert("1.0", text); self.feedback.config(state="disabled")

    # ---------------- Certificate & CSV ----------------
    def generate_cert(self):
        if not self.engine or not self.engine.quiz_items:
            messagebox.showwarning("No results", "Run a quiz first."); return
        if not self.passed:
            messagebox.showwarning("Threshold not met",
                                   f"Minimum {int(self.pass_threshold*100)}% required. Please retake the quiz.")
            return
        if not self.user_name:
            self.user_name = simpledialog.askstring("Your name", "Enter your full name (for the certificate):") or ""

        issuer = simpledialog.askstring("Issuer", "Issuer / Organization (optional):",
                                        initialvalue="Hydrogen Safety Trainer") or "Hydrogen Safety Trainer"
        verify = simpledialog.askstring("Verification URL base",
                                        "Verification URL base for QR (optional):\n(e.g., https://example.org/verify?id=)\nLeave blank for no QR.",
                                        initialvalue="")

        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF","*.pdf")],
                                            initialfile=f"certificate_{self.user_name.replace(' ','_')}.pdf")
        if not path: return

        left_logo = "logo_left.png" if os.path.exists("logo_left.png") else None
        right_logo = "logo_right.png" if os.path.exists("logo_right.png") else None
        watermark = "bg_watermark.png" if os.path.exists("bg_watermark.png") else None

        score = self.engine.score(); total = len(self.engine.quiz_items)
        generate_certificate(
            self.user_name, score, total, datetime.now(), path,
            issuer=issuer, left_logo_path=left_logo, right_logo_path=right_logo,
            watermark_path=watermark, verify_url_base=(verify.strip() or None)
        )
        messagebox.showinfo("Certificate", f"Saved: {path}")

    def save_results_csv(self):
        if not self.engine:
            messagebox.showwarning("No results", "Run a quiz first."); return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")],
                                            initialfile="quiz_results.csv")
        if not path: return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Name", "Date", "Score", "Total", "CategoryFilter", "Shuffled", "Passed", "Threshold"])
            w.writerow([self.user_name, datetime.now().strftime("%Y-%m-%d %H:%M"),
                        self.engine.correct_count, len(self.engine.quiz_items),
                        self.category_cb.get(), "Yes" if self.shuffle_var.get() else "No",
                        "Yes" if self.passed else "No", f"{int(self.pass_threshold*100)}%"])
            w.writerow([]); w.writerow(["#","Question","Chosen","Correct","IsCorrect","Rationale","Category","Difficulty"])
            for i, rec in enumerate(self.engine.history, start=1):
                w.writerow([i, rec["question"], rec["chosen"], rec["correct_text"],
                           "Yes" if rec["is_correct"] else "No", rec.get("rationale",""),
                           rec["category"], rec["difficulty"]])
        messagebox.showinfo("Saved", f"Results saved to {path}")

def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    app = TrainerApp(root)
    root.minsize(1000, 720)
    root.mainloop()

if __name__ == "__main__":
    main()
