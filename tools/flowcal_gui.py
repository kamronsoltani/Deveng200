import re, queue, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np, serial, serial.tools.list_ports
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

ROW = re.compile(r"\s*(\d+):\s*([\d.]+)\s*Hz\s*->\s*([\d.]+)\s*pulses/L")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Flow sensor calibration")
        self.geometry("1100x700")
        self.ser = None
        self.q = queue.Queue()
        self.points = []
        self.fit = None
        self.build()
        self.after(100, self.poll)

    def build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        self.port = ttk.Combobox(top, width=12, values=self.ports())
        self.port.pack(side="left")
        ttk.Button(top, text="Refresh", command=lambda: self.port.config(values=self.ports())).pack(side="left", padx=2)
        ttk.Button(top, text="Connect", command=self.connect).pack(side="left", padx=2)
        ttk.Label(top, text="Fit degree").pack(side="left", padx=(16, 2))
        self.deg = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=3, width=3, textvariable=self.deg, command=self.redraw).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8)
        left = ttk.Frame(mid)
        left.pack(side="left", fill="y")

        run = ttk.LabelFrame(left, text="Run")
        run.pack(fill="x", pady=4)
        ttk.Button(run, text="Start / Stop capture", command=lambda: self.send("s")).pack(fill="x", padx=4, pady=2)
        row = ttk.Frame(run)
        row.pack(fill="x", padx=4)
        ttk.Label(row, text="Grams").grid(row=0, column=0)
        self.g = ttk.Entry(row, width=9)
        self.g.grid(row=0, column=1)
        ttk.Label(row, text="Seconds").grid(row=1, column=0)
        self.t = ttk.Entry(row, width=9)
        self.t.grid(row=1, column=1)
        ttk.Label(run, text="Blank seconds = device time").pack()
        ttk.Button(run, text="Submit run", command=self.submit).pack(fill="x", padx=4, pady=2)
        ttk.Button(run, text="Discard run", command=lambda: self.send("x")).pack(fill="x", padx=4, pady=2)

        tbl = ttk.LabelFrame(left, text="Points")
        tbl.pack(fill="both", expand=True, pady=4)
        self.tree = ttk.Treeview(tbl, columns=("n", "hz", "ppl", "lpm"), show="headings", height=10)
        for c, w in (("n", 30), ("hz", 60), ("ppl", 70), ("lpm", 60)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)
        b = ttk.Frame(tbl)
        b.pack(fill="x")
        ttk.Button(b, text="Delete sel.", command=self.delete).pack(side="left", expand=True, fill="x")
        ttk.Button(b, text="Undo last", command=lambda: self.send("u")).pack(side="left", expand=True, fill="x")
        ttk.Button(b, text="Clear all", command=self.clear).pack(side="left", expand=True, fill="x")
        ttk.Button(tbl, text="Refresh from device", command=lambda: self.send("l")).pack(fill="x")

        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True, padx=8)
        self.fig = Figure(figsize=(5, 3.5))
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.eq = tk.StringVar(value="Equation: needs 2+ points")
        ttk.Label(right, textvariable=self.eq, font=("Consolas", 11)).pack(anchor="w", pady=4)
        ex = ttk.Frame(right)
        ex.pack(fill="x")
        ttk.Button(ex, text="Save CSV", command=self.save_csv).pack(side="left", padx=2)
        ttk.Button(ex, text="Save C++ header", command=self.save_h).pack(side="left", padx=2)
        ttk.Button(ex, text="Copy equation", command=self.copy_eq).pack(side="left", padx=2)

        self.log = tk.Text(self, height=9)
        self.log.pack(fill="x", padx=8, pady=6)

    def ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self):
        try:
            if self.ser:
                self.ser.close()
            self.ser = serial.Serial(self.port.get(), 115200, timeout=0.1)
        except Exception as e:
            messagebox.showerror("Serial", str(e))
            return
        threading.Thread(target=self.reader, daemon=True).start()
        self.after(1500, lambda: self.send("l"))

    def reader(self):
        buf = b""
        ser = self.ser
        while ser and ser.is_open:
            try:
                buf += ser.read(256)
            except Exception:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.q.put(line.decode(errors="ignore").rstrip())

    def send(self, s):
        if not self.ser or not self.ser.is_open:
            messagebox.showinfo("Serial", "Connect first")
            return
        self.ser.write((s + "\n").encode())

    def submit(self):
        g, t = self.g.get().strip(), self.t.get().strip()
        if not g:
            return
        self.send(g)
        self.after(300, lambda: self.send(t if t else "a"))
        self.g.delete(0, "end")
        self.t.delete(0, "end")

    def delete(self):
        sel = self.tree.selection()
        if sel:
            self.send("d" + str(self.tree.item(sel[0])["values"][0]))

    def clear(self):
        if messagebox.askyesno("Clear", "Clear all calibration points?"):
            self.send("c")

    def poll(self):
        try:
            while True:
                line = self.q.get_nowait()
                self.log.insert("end", line + "\n")
                self.log.see("end")
                if line.startswith("Calibration points"):
                    self.points = []
                    self.redraw()
                m = ROW.match(line)
                if m:
                    self.points.append((float(m.group(2)), float(m.group(3))))
                    self.redraw()
                if line.startswith("Added:") or line.startswith("Calibration cleared"):
                    self.after(200, lambda: self.send("l"))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def redraw(self):
        self.tree.delete(*self.tree.get_children())
        hz = np.array([p[0] for p in self.points])
        ppl = np.array([p[1] for p in self.points])
        lpm = hz * 60 / ppl if len(hz) else np.array([])
        for i, (h, p) in enumerate(self.points, 1):
            self.tree.insert("", "end", values=(i, f"{h:.2f}", f"{p:.2f}", f"{h * 60 / p:.2f}"))
        self.ax.clear()
        self.ax.set_xlabel("Frequency (Hz)")
        self.ax.set_ylabel("Flow (L/min)")
        self.ax.grid(True)
        self.fit = None
        if len(hz):
            self.ax.plot(hz, lpm, "o", label="runs")
        d = self.deg.get()
        if len(hz) > d:
            c = np.polyfit(hz, lpm, d)
            fx = np.linspace(hz.min(), hz.max(), 100)
            self.ax.plot(fx, np.polyval(c, fx), "-", label=f"poly deg {d}")
            res = lpm - np.polyval(c, hz)
            sst = ((lpm - lpm.mean()) ** 2).sum()
            r2 = 1 - (res ** 2).sum() / sst if sst > 0 else 1
            terms = []
            for i, v in enumerate(c):
                p = d - i
                terms.append(f"{v:.6g}*Hz^{p}" if p > 1 else (f"{v:.6g}*Hz" if p == 1 else f"{v:.6g}"))
            maxerr = float(np.abs(res / lpm).max() * 100)
            self.fit = (c, r2, maxerr)
            self.eq.set("L/min = " + " + ".join(terms) + f"\nR2 = {r2:.5f}, max error = {maxerr:.2f}%")
            self.ax.legend()
        else:
            self.eq.set("Equation: needs more points than the fit degree")
        self.canvas.draw()

    def copy_eq(self):
        self.clipboard_clear()
        self.clipboard_append(self.eq.get())

    def save_csv(self):
        f = filedialog.asksaveasfilename(defaultextension=".csv")
        if not f:
            return
        with open(f, "w") as fh:
            fh.write("point,hz,pulses_per_L,L_per_min\n")
            for i, (h, p) in enumerate(self.points, 1):
                fh.write(f"{i},{h:.3f},{p:.3f},{h * 60 / p:.4f}\n")

    def save_h(self):
        if not self.points:
            return
        f = filedialog.asksaveasfilename(defaultextension=".h", initialfile="flow_cal.h")
        if not f:
            return
        hz = ", ".join(f"{p[0]:.3f}" for p in self.points)
        ppl = ", ".join(f"{p[1]:.3f}" for p in self.points)
        with open(f, "w") as fh:
            fh.write("#pragma once\n")
            fh.write(f"const int N_CAL = {len(self.points)};\n")
            fh.write(f"const float calHz[N_CAL]  = {{{hz}}};\n")
            fh.write(f"const float calPpl[N_CAL] = {{{ppl}}};\n")
            if self.fit:
                c = ", ".join(f"{v:.8g}" for v in self.fit[0])
                fh.write("// polynomial coeffs, highest power first: L/min = poly(Hz)\n")
                fh.write(f"const float calPoly[] = {{{c}}};\n")
            fh.write("""
inline float pplAt(float hz) {
  if (hz <= calHz[0]) return calPpl[0];
  if (hz >= calHz[N_CAL - 1]) return calPpl[N_CAL - 1];
  for (int i = 0; i < N_CAL - 1; i++)
    if (hz >= calHz[i] && hz < calHz[i + 1]) {
      float f = (hz - calHz[i]) / (calHz[i + 1] - calHz[i]);
      return calPpl[i] + f * (calPpl[i + 1] - calPpl[i]);
    }
  return calPpl[N_CAL - 1];
}
inline float hzToLpm(float hz) { return hz * 60.0f / pplAt(hz); }
""")


App().mainloop()