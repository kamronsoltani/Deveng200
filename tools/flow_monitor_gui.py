import re, time, queue, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np, serial, serial.tools.list_ports
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

LINE = re.compile(r"([\d.]+)\s*Hz\s+([\d.]+)\s*L/min\s+total\s+([\d.]+)\s*L")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Flow monitor")
        self.geometry("1100x720")
        self.ser = None
        self.q = queue.Queue()
        self.t0 = time.time()
        self.live = []      # (t, hz, lpm) rolling buffer
        self.rec = []       # recorded run
        self.recording = False
        self.rec_t0 = 0
        self.build()
        self.after(100, self.poll)

    def build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        self.port = ttk.Combobox(top, width=12, values=self.ports())
        self.port.pack(side="left")
        ttk.Button(top, text="Refresh", command=lambda: self.port.config(values=self.ports())).pack(side="left", padx=2)
        ttk.Button(top, text="Connect", command=self.connect).pack(side="left", padx=2)
        ttk.Label(top, text="Window (s)").pack(side="left", padx=(16, 2))
        self.win = tk.IntVar(value=60)
        ttk.Spinbox(top, from_=10, to=600, increment=10, width=5, textvariable=self.win).pack(side="left")
        ttk.Label(top, text="Smooth (samples)").pack(side="left", padx=(16, 2))
        self.smooth = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=20, width=3, textvariable=self.smooth).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8)
        left = ttk.Frame(mid)
        left.pack(side="left", fill="y")

        live = ttk.LabelFrame(left, text="Live")
        live.pack(fill="x", pady=4)
        self.big = tk.StringVar(value="--.--")
        ttk.Label(live, textvariable=self.big, font=("Consolas", 40, "bold")).pack(padx=10)
        ttk.Label(live, text="L/min").pack()
        self.hzv = tk.StringVar(value="Hz: --")
        self.totv = tk.StringVar(value="Device total: -- L")
        ttk.Label(live, textvariable=self.hzv, font=("Consolas", 11)).pack(anchor="w", padx=6)
        ttk.Label(live, textvariable=self.totv, font=("Consolas", 11)).pack(anchor="w", padx=6, pady=(0, 4))

        rec = ttk.LabelFrame(left, text="Recording")
        rec.pack(fill="x", pady=4)
        self.recbtn = ttk.Button(rec, text="Start recording", command=self.toggle_rec)
        self.recbtn.pack(fill="x", padx=4, pady=2)
        ttk.Button(rec, text="Clear recording", command=self.clear_rec).pack(fill="x", padx=4, pady=2)
        ttk.Button(rec, text="Save CSV", command=self.save_csv).pack(fill="x", padx=4, pady=2)
        ttk.Button(rec, text="Reset device total", command=self.reset_dev).pack(fill="x", padx=4, pady=2)

        st = ttk.LabelFrame(left, text="Run stats")
        st.pack(fill="both", expand=True, pady=4)
        self.stats = tk.StringVar(value="No recording yet")
        ttk.Label(st, textvariable=self.stats, font=("Consolas", 10), justify="left").pack(anchor="w", padx=6, pady=4)

        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True, padx=8)
        self.fig = Figure(figsize=(6, 4))
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.log = tk.Text(self, height=6)
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
        threading.Thread(target=self.reader, args=(self.ser,), daemon=True).start()

    def reader(self, ser):
        buf = b""
        while ser.is_open:
            try:
                buf += ser.read(256)
            except Exception:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.q.put(line.decode(errors="ignore").rstrip())

    def reset_dev(self):
        messagebox.showinfo("Reset", "Press the hardware button on the board to reset its total.")

    def toggle_rec(self):
        if not self.recording:
            self.rec = []
            self.rec_t0 = time.time()
            self.recording = True
            self.recbtn.config(text="Stop recording")
        else:
            self.recording = False
            self.recbtn.config(text="Start recording")
            self.update_stats()

    def clear_rec(self):
        self.rec = []
        self.recording = False
        self.recbtn.config(text="Start recording")
        self.stats.set("No recording yet")

    def poll(self):
        got = False
        try:
            while True:
                line = self.q.get_nowait()
                self.log.insert("end", line + "\n")
                self.log.see("end")
                if int(float(self.log.index("end"))) > 200:
                    self.log.delete("1.0", "50.0")
                m = LINE.search(line)
                if m:
                    hz, lpm, tot = map(float, m.groups())
                    t = time.time() - self.t0
                    self.live.append((t, hz, lpm))
                    if self.recording:
                        self.rec.append((time.time() - self.rec_t0, hz, lpm))
                    self.big.set(f"{lpm:5.2f}")
                    self.hzv.set(f"Hz: {hz:.2f}")
                    self.totv.set(f"Device total: {tot:.3f} L")
                    got = True
        except queue.Empty:
            pass
        if len(self.live) > 5000:
            self.live = self.live[-5000:]
        if got:
            self.redraw()
            if self.recording:
                self.update_stats()
        self.after(100, self.poll)

    def smoothed(self, y):
        n = max(1, self.smooth.get())
        if n == 1 or len(y) < n:
            return y
        return np.convolve(y, np.ones(n) / n, mode="valid")

    def redraw(self):
        self.ax.clear()
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Flow (L/min)")
        self.ax.grid(True)
        if self.recording or self.rec:
            d = np.array(self.rec)
            title = "Recording" if self.recording else "Recorded run"
        else:
            if not self.live:
                self.canvas.draw()
                return
            d = np.array(self.live)
            d = d[d[:, 0] >= d[-1, 0] - self.win.get()]
            d[:, 0] -= d[-1, 0]
            title = f"Live (last {self.win.get()} s)"
        if len(d) == 0:
            self.canvas.draw()
            return
        t, y = d[:, 0], d[:, 2]
        n = max(1, self.smooth.get())
        if n > 1 and len(y) >= n:
            ys = self.smoothed(y)
            self.ax.plot(t, y, color="0.8")
            self.ax.plot(t[n - 1:], ys, color="C0")
        else:
            self.ax.plot(t, y, color="C0")
        self.ax.set_title(title)
        self.canvas.draw()

    def update_stats(self):
        if len(self.rec) < 2:
            return
        d = np.array(self.rec)
        t, y = d[:, 0], d[:, 2]
        k = max(1, min(5, len(y) // 5))
        start, end = y[:k].mean(), y[-k:].mean()
        delta = end - start
        pct = delta / start * 100 if start > 0 else 0
        slope = np.polyfit(t, y, 1)[0] * 60 if t[-1] > 0 else 0
        self.stats.set(
            f"Duration  {t[-1]:.1f} s\n"
            f"Samples   {len(y)}\n"
            f"Start     {start:.2f} L/min\n"
            f"End       {end:.2f} L/min\n"
            f"Delta     {delta:+.2f} L/min ({pct:+.1f}%)\n"
            f"Min       {y.min():.2f}\n"
            f"Max       {y.max():.2f}\n"
            f"Mean      {y.mean():.2f}\n"
            f"Std dev   {y.std():.2f}\n"
            f"Drift     {slope:+.3f} L/min per min\n"
            f"Volume    {np.trapz(y, t) / 60:.3f} L"
        )

    def save_csv(self):
        if not self.rec:
            messagebox.showinfo("Save", "Nothing recorded yet")
            return
        f = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="flow_run.csv")
        if not f:
            return
        with open(f, "w") as fh:
            fh.write("time_s,hz,L_per_min\n")
            for t, hz, lpm in self.rec:
                fh.write(f"{t:.3f},{hz:.3f},{lpm:.4f}\n")


App().mainloop()