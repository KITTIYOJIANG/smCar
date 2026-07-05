#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small GUI for RT1064 mecanum chassis turn tests over USB CDC serial."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - depends on the user's PC environment
    serial = None
    list_ports = None


DEFAULT_BAUD = 115200
READ_POLL_MS = 50


def set_line_state(ser, mode: str) -> None:
    if mode == "none":
        ser.dtr = False
        ser.rts = False
    elif mode == "both":
        ser.dtr = True
        ser.rts = True
    else:
        raise ValueError(f"bad line state: {mode}")


def seekfree_cdc_handshake(ser) -> None:
    time.sleep(0.6)
    set_line_state(ser, "none")
    time.sleep(0.35)
    set_line_state(ser, "both")
    time.sleep(0.35)
    set_line_state(ser, "none")
    time.sleep(0.2)


class TurnTestGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("麦轮底盘原地转测试")
        self.geometry("1040x720")
        self.minsize(960, 640)

        self.ser = None
        self.reader_thread: threading.Thread | None = None
        self.reader_running = threading.Event()
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        self.angle_var = tk.StringVar(value="90")
        self.spin_wz_var = tk.StringVar(value="120")
        self.spin_duration_var = tk.StringVar(value="1.0")
        self.turn_max_var = tk.StringVar(value="150")
        self.turn_min_var = tk.StringVar(value="120")
        self.left_vx_var = tk.StringVar(value="-10")
        self.left_vy_var = tk.StringVar(value="10")
        self.right_vx_var = tk.StringVar(value="-25")
        self.right_vy_var = tk.StringVar(value="0")

        self._build_ui()
        self.refresh_ports()
        self.after(READ_POLL_MS, self._drain_log_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        conn = ttk.LabelFrame(root, text="串口连接", padding=8)
        conn.pack(fill=tk.X)

        ttk.Label(conn, text="COM").grid(row=0, column=0, sticky=tk.W)
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var, width=18, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=6, sticky=tk.W)
        ttk.Button(conn, text="刷新", command=self.refresh_ports).grid(row=0, column=2, padx=4)
        ttk.Label(conn, text="波特率").grid(row=0, column=3, padx=(16, 0), sticky=tk.W)
        ttk.Entry(conn, textvariable=self.baud_var, width=10).grid(row=0, column=4, padx=6, sticky=tk.W)
        self.connect_btn = ttk.Button(conn, text="连接", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=5, padx=4)
        ttk.Button(conn, text="停止", command=lambda: self.send_command("s")).grid(row=0, column=6, padx=4)
        ttk.Button(conn, text="状态", command=lambda: self.send_command("status")).grid(row=0, column=7, padx=4)
        ttk.Button(conn, text="清空日志", command=self.clear_log).grid(row=0, column=8, padx=4)

        body = ttk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        controls = ttk.Frame(body)
        controls.pack(side=tk.LEFT, fill=tk.Y)

        turn_box = ttk.LabelFrame(controls, text="Yaw 闭环转角", padding=8)
        turn_box.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(turn_box, text="左转 90°", command=lambda: self.turn_angle(90)).grid(row=0, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(turn_box, text="右转 90°", command=lambda: self.turn_angle(-90)).grid(row=0, column=1, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(turn_box, text="左转 180°", command=lambda: self.turn_angle(180)).grid(row=1, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(turn_box, text="右转 180°", command=lambda: self.turn_angle(-180)).grid(row=1, column=1, padx=4, pady=4, sticky=tk.EW)
        ttk.Label(turn_box, text="自定义角度").grid(row=2, column=0, padx=4, pady=(10, 4), sticky=tk.W)
        ttk.Entry(turn_box, textvariable=self.angle_var, width=8).grid(row=2, column=1, padx=4, pady=(10, 4), sticky=tk.W)
        ttk.Button(turn_box, text="左转发送", command=lambda: self.turn_custom(+1)).grid(row=3, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(turn_box, text="右转发送", command=lambda: self.turn_custom(-1)).grid(row=3, column=1, padx=4, pady=4, sticky=tk.EW)

        prep_box = ttk.LabelFrame(controls, text="测试准备", padding=8)
        prep_box.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(prep_box, text="IMU 静止校准", command=lambda: self.send_command("imu cal")).grid(row=0, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(prep_box, text="Yaw 归零", command=lambda: self.send_command("yaw reset")).grid(row=0, column=1, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(prep_box, text="Turn 状态", command=lambda: self.send_command("turn status")).grid(row=1, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(prep_box, text="补偿清零", command=lambda: self.send_command("turn compreset")).grid(row=1, column=1, padx=4, pady=4, sticky=tk.EW)

        param_box = ttk.LabelFrame(controls, text="Turn 参数", padding=8)
        param_box.pack(fill=tk.X, pady=(0, 10))
        self._labeled_entry(param_box, "max wz", self.turn_max_var, 0, 0)
        self._labeled_entry(param_box, "min wz", self.turn_min_var, 0, 2)
        self._labeled_entry(param_box, "左 vx", self.left_vx_var, 1, 0)
        self._labeled_entry(param_box, "左 vy", self.left_vy_var, 1, 2)
        self._labeled_entry(param_box, "右 vx", self.right_vx_var, 2, 0)
        self._labeled_entry(param_box, "右 vy", self.right_vy_var, 2, 2)
        ttk.Button(param_box, text="应用参数", command=self.apply_turn_params).grid(row=3, column=0, columnspan=4, padx=4, pady=(8, 4), sticky=tk.EW)

        spin_box = ttk.LabelFrame(controls, text="开环原地转圈", padding=8)
        spin_box.pack(fill=tk.X, pady=(0, 10))
        self._labeled_entry(spin_box, "wz", self.spin_wz_var, 0, 0)
        self._labeled_entry(spin_box, "秒", self.spin_duration_var, 0, 2)
        ttk.Button(spin_box, text="左转圈", command=lambda: self.spin_open_loop(+1)).grid(row=1, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(spin_box, text="右转圈", command=lambda: self.spin_open_loop(-1)).grid(row=1, column=1, padx=4, pady=4, sticky=tk.EW)

        raw_box = ttk.LabelFrame(controls, text="原始命令", padding=8)
        raw_box.pack(fill=tk.X)
        self.raw_var = tk.StringVar(value="turn status")
        ttk.Entry(raw_box, textvariable=self.raw_var, width=34).grid(row=0, column=0, padx=4, pady=4, sticky=tk.EW)
        ttk.Button(raw_box, text="发送", command=lambda: self.send_command(self.raw_var.get())).grid(row=0, column=1, padx=4, pady=4)

        log_box = ttk.LabelFrame(body, text="串口日志", padding=8)
        log_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        self.log = tk.Text(log_box, wrap=tk.NONE, height=28, font=("Consolas", 10))
        yscroll = ttk.Scrollbar(log_box, orient=tk.VERTICAL, command=self.log.yview)
        xscroll = ttk.Scrollbar(log_box, orient=tk.HORIZONTAL, command=self.log.xview)
        self.log.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.log.grid(row=0, column=0, sticky=tk.NSEW)
        yscroll.grid(row=0, column=1, sticky=tk.NS)
        xscroll.grid(row=1, column=0, sticky=tk.EW)
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)

    def _labeled_entry(self, parent, label: str, var: tk.StringVar, row: int, col: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=col, padx=4, pady=4, sticky=tk.W)
        ttk.Entry(parent, textvariable=var, width=8).grid(row=row, column=col + 1, padx=4, pady=4, sticky=tk.W)

    def refresh_ports(self) -> None:
        if serial is None or list_ports is None:
            messagebox.showerror("缺少依赖", "未安装 pyserial，请运行：python -m pip install pyserial")
            return
        ports = list(list_ports.comports())
        values = [p.device for p in ports]
        self.port_combo["values"] = values
        if values and (not self.port_var.get() or self.port_var.get() not in values):
            self.port_var.set(values[0])
        self._append_log("可用串口: " + (", ".join(values) if values else "无"))

    def toggle_connection(self) -> None:
        if self.ser is not None:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        if serial is None:
            messagebox.showerror("缺少依赖", "未安装 pyserial，请运行：python -m pip install pyserial")
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("未选择串口", "请先选择 COM 口。")
            return
        try:
            baud = int(self.baud_var.get())
            self.ser = serial.Serial(port=port, baudrate=baud, timeout=0.1, write_timeout=1.0, rtscts=False, dsrdtr=False)
            seekfree_cdc_handshake(self.ser)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as exc:
            self.ser = None
            messagebox.showerror("连接失败", str(exc))
            return

        self.reader_running.set()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self.connect_btn.configure(text="断开")
        self._append_log(f"已连接 {port}")
        self.send_command("status")

    def disconnect(self) -> None:
        self.reader_running.clear()
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connect_btn.configure(text="连接")
        self._append_log("已断开")

    def send_command(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        if self.ser is None or not self.ser.is_open:
            messagebox.showwarning("未连接", "请先连接串口。")
            return
        try:
            self.ser.write((command + "\n").encode("ascii", errors="ignore"))
            self.ser.flush()
            self._append_log(f">> {command}")
        except Exception as exc:
            messagebox.showerror("发送失败", str(exc))

    def turn_angle(self, angle: int) -> None:
        self.send_command(f"turn {angle}")

    def turn_custom(self, sign: int) -> None:
        try:
            angle = abs(int(float(self.angle_var.get())))
        except ValueError:
            messagebox.showwarning("角度错误", "请输入数字角度，例如 90 或 180。")
            return
        self.turn_angle(sign * angle)

    def apply_turn_params(self) -> None:
        commands = [
            f"turn max {self.turn_max_var.get()}",
            f"turn min {self.turn_min_var.get()}",
            f"turn lvx {self.left_vx_var.get()}",
            f"turn lvy {self.left_vy_var.get()}",
            f"turn rvx {self.right_vx_var.get()}",
            f"turn rvy {self.right_vy_var.get()}",
            "turn status",
        ]
        for command in commands:
            self.send_command(command)
            time.sleep(0.03)

    def spin_open_loop(self, sign: int) -> None:
        try:
            wz = abs(int(float(self.spin_wz_var.get()))) * sign
            duration = max(0.1, float(self.spin_duration_var.get()))
        except ValueError:
            messagebox.showwarning("参数错误", "wz 和秒数必须是数字。")
            return
        self.send_command(f"vel 0 0 {wz}")
        threading.Thread(target=self._delayed_stop, args=(duration,), daemon=True).start()

    def _delayed_stop(self, duration: float) -> None:
        time.sleep(duration)
        self.send_command("s")

    def _reader_loop(self) -> None:
        while self.reader_running.is_set() and self.ser is not None:
            try:
                data = self.ser.readline()
            except Exception as exc:
                self.log_queue.put(f"读取错误: {exc}")
                break
            if data:
                self.log_queue.put(data.decode("utf-8", errors="ignore").strip())
        self.reader_running.clear()

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line:
                    self._append_log(line)
        except queue.Empty:
            pass
        self.after(READ_POLL_MS, self._drain_log_queue)

    def _append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def destroy(self) -> None:
        self.disconnect()
        super().destroy()


if __name__ == "__main__":
    app = TurnTestGui()
    app.mainloop()
