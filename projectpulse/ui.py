"""Настольный UI на Tkinter (stdlib): панель, динамика, граф, сравнение, экспорт."""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import analysis, graph, report
from .db import open_db
from .gitio import GitError
from .indexer import Cancelled, Indexer

SEV_COLOR = {"high": "#c0392b", "medium": "#d68910", "low": "#2874a6"}


def run_ui(data_dir):
    App(data_dir).mainloop()


class App(tk.Tk):
    def __init__(self, data_dir):
        super().__init__()
        self.title("ProjectPulse")
        self.geometry("980x640")
        self.db_path = os.path.join(data_dir, "projectpulse.db")
        self.q, self.cancel_ev, self.result = queue.Queue(), threading.Event(), None
        self._top()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tabs = {n: ttk.Frame(nb) for n in ("Панель", "Динамика", "Граф", "Сравнение", "Экспорт")}
        for n, f in self.tabs.items():
            nb.add(f, text=n)
        self._panel(); self._timeline(); self._graph(); self._compare(); self._export()
        self.refresh_repos()
        self.after(100, self._poll)

    # ---------- верхняя панель ----------
    def _top(self):
        f = ttk.Frame(self); f.pack(fill="x", padx=6, pady=4)
        self.path_var, self.repo_var = tk.StringVar(), tk.StringVar()
        ttk.Entry(f, textvariable=self.path_var, width=44).pack(side="left")
        ttk.Button(f, text="Обзор…", command=lambda: self.path_var.set(filedialog.askdirectory() or self.path_var.get())).pack(side="left")
        ttk.Button(f, text="Импорт / обновить", command=lambda: self.start_index(False)).pack(side="left", padx=2)
        ttk.Button(f, text="Пересобрать с нуля", command=lambda: self.start_index(True)).pack(side="left")
        ttk.Button(f, text="Отмена", command=self.cancel_ev.set).pack(side="left", padx=2)
        self.repo_cb = ttk.Combobox(f, textvariable=self.repo_var, width=18, state="readonly")
        self.repo_cb.pack(side="left", padx=6)
        self.repo_cb.bind("<<ComboboxSelected>>", lambda e: self.reanalyze())
        self.pb = ttk.Progressbar(f, length=140); self.pb.pack(side="left")
        self.status = tk.StringVar(value="готов")
        ttk.Label(self, textvariable=self.status).pack(fill="x", padx=8)

    def refresh_repos(self):
        db = open_db(self.db_path)
        names = [r[0] for r in db.execute("SELECT name FROM repos ORDER BY name")]
        db.close()
        for cb in (self.repo_cb, self.cmp_a, self.cmp_b, self.tl_other):
            cb["values"] = names if cb is not self.tl_other else [""] + names
        if names and not self.repo_var.get():
            self.repo_var.set(names[0]); self.reanalyze()

    # ---------- индексация в потоке ----------
    def start_index(self, rebuild):
        path = self.path_var.get().strip()
        if not path:
            return messagebox.showinfo("ProjectPulse", "Укажите путь к git-репозиторию")
        self.cancel_ev.clear()

        def work():
            db = open_db(self.db_path)
            try:
                idx = Indexer(db, path, progress=lambda s, d, t: self.q.put(("p", s, d, t)), cancel=self.cancel_ev)
                self.q.put(("done", idx.name, idx.run(rebuild=rebuild)))
            except Cancelled:
                self.q.put(("err", "Отменено пользователем"))
            except GitError as e:
                self.q.put(("err", f"Ошибка git: {e}"))
            except Exception as e:                      # битые данные не должны ронять UI
                self.q.put(("err", f"Ошибка: {e}"))
            finally:
                db.close()
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "p":
                    self.status.set(m[1]); self.pb["value"] = 100 * m[2] / m[3] if m[3] else 0
                elif m[0] == "err":
                    self.status.set(m[1]); messagebox.showwarning("ProjectPulse", m[1])
                else:
                    r = m[2]
                    self.status.set(f"{m[1]}: {r['mode']}, {r['n_commits']} коммитов, {r['duration']:.2f} с")
                    self.repo_var.set(m[1]); self.refresh_repos(); self.reanalyze()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def reanalyze(self):
        name = self.repo_var.get()
        if not name:
            return
        db = open_db(self.db_path)
        self.result = analysis.analyze(db, name)
        t = analysis.timings(db, name)
        self.draw_panel(t); self.draw_series(); self.load_graph(db)
        db.close()

    # ---------- панель ----------
    def _panel(self):
        f = self.tabs["Панель"]
        self.score = tk.Label(f, text="—", font=("Arial", 42, "bold")); self.score.pack(pady=4)
        self.timing = ttk.Label(f, text=""); self.timing.pack()
        self.risks = ttk.Treeview(f, columns=("sev", "rule", "why"), show="headings", height=14)
        for c, w in (("sev", 70), ("rule", 160), ("why", 700)):
            self.risks.heading(c, text={"sev": "Уровень", "rule": "Правило", "why": "Почему сработало"}[c])
            self.risks.column(c, width=w)
        self.risks.pack(fill="both", expand=True, padx=6, pady=6)

    def draw_panel(self, t):
        r = self.result
        self.score.config(text=f"{r.health} / 100", fg="#1e8449" if r.health >= 70 else "#d68910" if r.health >= 40 else "#c0392b")
        self.risks.delete(*self.risks.get_children())
        for f in r.findings:
            self.risks.insert("", "end", values=(f.severity, f.rule, f.message))
        fmt = lambda x: f"{x[0]:.2f} с ({x[1]} коммитов)" if x else "—"
        self.timing.config(text=f"Полная индексация: {fmt(t['full'])}   |   Инкрементальная: {fmt(t['incremental'])}")

    # ---------- динамика ----------
    def _timeline(self):
        f = self.tabs["Динамика"]
        bar = ttk.Frame(f); bar.pack(fill="x")
        self.tl_series = ttk.Combobox(bar, values=["weekly_commits", "weekly_churn", "weekly_fixes", "weekly_fix_ratio"], state="readonly")
        self.tl_series.set("weekly_churn"); self.tl_series.pack(side="left", padx=4, pady=4)
        ttk.Label(bar, text="сравнить с:").pack(side="left")
        self.tl_other = ttk.Combobox(bar, state="readonly"); self.tl_other.pack(side="left")
        for c in (self.tl_series, self.tl_other):
            c.bind("<<ComboboxSelected>>", lambda e: self.draw_series())
        self.cv = tk.Canvas(f, bg="white"); self.cv.pack(fill="both", expand=True, padx=6, pady=6)
        self.cv.bind("<Configure>", lambda e: self.draw_series())

    def draw_series(self):
        if not self.result:
            return
        self.cv.delete("all")
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        sets = [(self.result.mv.series(self.tl_series.get()), "#2874a6", self.result.repo)]
        if self.tl_other.get():
            db = open_db(self.db_path)
            sets.append((analysis.analyze(db, self.tl_other.get()).mv.series(self.tl_series.get()), "#c0392b", self.tl_other.get()))
            db.close()
        mx = max((v for s, _, _ in sets for _, v in s), default=0) or 1
        for i, (s, col, name) in enumerate(sets):
            pts = []
            for k, (_, v) in enumerate(s):
                pts += [30 + k * (w - 50) / max(len(s) - 1, 1), h - 20 - v / mx * (h - 40)]
            if len(pts) >= 4:
                self.cv.create_line(*pts, fill=col, width=2)
            self.cv.create_text(40, 12 + 14 * i, text=name, fill=col, anchor="w")
        self.cv.create_text(w - 10, 12, text=f"max={mx:.2f}", anchor="e")

    # ---------- граф ----------
    def _graph(self):
        f = self.tabs["Граф"]
        bar = ttk.Frame(f); bar.pack(fill="x", pady=4)
        self.g_q, self.g_depth, self.g_mod = tk.StringVar(), tk.IntVar(value=2), tk.StringVar()
        self.g_proj = ttk.Combobox(bar, values=["file", "class"], state="readonly", width=6); self.g_proj.set("file")
        self.g_rel = ttk.Combobox(bar, values=["все", "import", "inherit", "call", "compose"], state="readonly", width=8); self.g_rel.set("все")
        for lab, wdg in (("Поиск:", ttk.Entry(bar, textvariable=self.g_q, width=22)), ("Проекция:", self.g_proj),
                         ("Связь:", self.g_rel), ("Глубина:", ttk.Spinbox(bar, from_=1, to=6, textvariable=self.g_depth, width=3)),
                         ("Модуль:", ttk.Entry(bar, textvariable=self.g_mod, width=14))):
            ttk.Label(bar, text=lab).pack(side="left", padx=2); wdg.pack(side="left")
        ttk.Button(bar, text="Найти", command=self.show_neighbors).pack(side="left", padx=4)
        self.g_list = tk.Listbox(f, font=("Courier", 10)); self.g_list.pack(fill="both", expand=True, padx=6, pady=4)
        self.g_list.bind("<Double-Button-1>", self._jump)
        self.g_data = None

    def load_graph(self, db):
        vs = graph.versions(db, self.result.repo)
        self.g_data = {p: (graph.load_nodes(db, vs[-1][0], p), graph.load_edges(db, vs[-1][0], p)) for p in ("file", "class")} if vs else None

    def show_neighbors(self):
        self.g_list.delete(0, "end")
        if not self.g_data:
            return
        nodes, edges = self.g_data[self.g_proj.get()]
        rel, mod = self.g_rel.get(), self.g_mod.get()
        edges = [e for e in edges if (rel == "все" or e[2] == rel) and (not mod or mod in e[0] or mod in e[1])]
        q = self.g_q.get()
        hits = [n for n in nodes if q in n]
        if not hits:
            return self.g_list.insert("end", "ничего не найдено")
        start = hits[0]
        out, inn = {}, {}
        for s, d, r in edges:
            out.setdefault(s, set()).add(d); inn.setdefault(d, set()).add(s)
        both = {n: out.get(n, set()) | inn.get(n, set()) for n in set(out) | set(inn)}
        self.g_list.insert("end", f"[узел] {start}   (совпадений: {len(hits)}; двойной клик — перейти)")
        for n, d in sorted(graph.bfs(both, start, self.g_depth.get()).items(), key=lambda kv: (kv[1], kv[0])):
            if n != start:
                arrow = "→" if n in out.get(start, ()) else "←" if n in inn.get(start, ()) else "·"
                self.g_list.insert("end", f"{'  ' * d}{arrow} d={d} {n}")
                self.g_list.itemconfig("end", fg="#1e8449" if d == 1 else "black")

    def _jump(self, _):
        sel = self.g_list.curselection()
        if sel and sel[0] > 0:
            self.g_q.set(self.g_list.get(sel[0]).strip().split(" ", 2)[-1])
            self.show_neighbors()

    # ---------- сравнение ----------
    def _compare(self):
        f = self.tabs["Сравнение"]
        bar = ttk.Frame(f); bar.pack(fill="x", pady=4)
        self.cmp_a = ttk.Combobox(bar, state="readonly"); self.cmp_b = ttk.Combobox(bar, state="readonly")
        ttk.Label(bar, text="«Здоровый»:").pack(side="left"); self.cmp_a.pack(side="left")
        ttk.Label(bar, text="«Проблемный»:").pack(side="left"); self.cmp_b.pack(side="left")
        ttk.Button(bar, text="Сравнить", command=self.do_compare).pack(side="left", padx=6)
        self.cmp_t = ttk.Treeview(f, columns=("k", "a", "b"), show="headings", height=8)
        for c, t in (("k", "Показатель"), ("a", "A"), ("b", "B")):
            self.cmp_t.heading(c, text=t)
        self.cmp_t.pack(fill="both", expand=True, padx=6, pady=6)

    def do_compare(self):
        if not (self.cmp_a.get() and self.cmp_b.get()):
            return
        db = open_db(self.db_path)
        self.cmp_t.delete(*self.cmp_t.get_children())
        for k, a, b in analysis.compare(db, self.cmp_a.get(), self.cmp_b.get()):
            self.cmp_t.insert("", "end", values=(k, f"{a:.2f}" if isinstance(a, float) else a, f"{b:.2f}" if isinstance(b, float) else b))
        db.close()

    # ---------- экспорт ----------
    def _export(self):
        ttk.Button(self.tabs["Экспорт"], text="Сохранить отчёт HTML…", command=self.do_export).pack(pady=30)

    def do_export(self):
        if not self.result:
            return
        out = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if out:
            db = open_db(self.db_path)
            with open(out, "w", encoding="utf-8") as f:
                f.write(report.build_html(db, self.result))
            db.close()
            self.status.set(f"отчёт сохранён: {out}")
